"""Opt-in TLS LAN transport. Domain operations are marshalled by companion_ui."""
from collections import OrderedDict
from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import socket
import ssl
import threading
import time
import sqlite3
import uuid

MAX_BODY = 2_600_000


def identity(directory):
    """Generate private per-install TLS identity, outside the source tree."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    key_path, cert_path = directory / 'key.pem', directory / 'cert.pem'
    if not key_path.exists() or not cert_path.exists():
        key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Neyra companion')])
        now = datetime.now(timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                .public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=3650))
                .sign(key, hashes.SHA256()))
        for path, content in ((key_path, key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())),
                              (cert_path, cert.public_bytes(serialization.Encoding.PEM))):
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, 'wb') as output:
                output.write(content)
    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    return key_path, cert_path, cert.fingerprint(hashes.SHA256()).hex()


class CompanionServer:
    def __init__(self, directory, dispatch, host='0.0.0.0', port=0):
        self.directory = Path(directory)
        key, cert, self.fingerprint = identity(directory)
        self.name = socket.gethostname()
        self.dispatch = dispatch
        self.lock = threading.Lock()
        self.mutation_lock = threading.Lock()
        self.slots = threading.BoundedSemaphore(8)
        self.requests = OrderedDict()
        self.invites = {}
        self.credentials = self.directory / 'peers.json'
        try:
            state = json.loads(self.credentials.read_text())
            self.machine_id, self.tokens = state['id'], state['tokens']
        except (OSError, ValueError, KeyError):
            self.machine_id, self.tokens = uuid.uuid4().hex, []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass  # Never log tokens or personal content.

            def setup(self):
                super().setup()
                self.connection.settimeout(10)

            def reply(self, status, value):
                body = json.dumps(value, allow_nan=False).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(body)

            def handle_request(self):
                auth = self.headers.get('Authorization', '')
                with owner.lock:
                    authorized = any(secrets.compare_digest(auth, 'Bearer ' + token) for token in owner.tokens)
                    invitation = self.path == '/v1/enroll' and owner.invites.get(auth.removeprefix('Bearer '), 0) > time.monotonic()
                if not authorized and not invitation:
                    return self.reply(401, {'error': 'Pair this phone in desktop Companion settings.'})
                if not owner.slots.acquire(blocking=False):
                    return self.reply(503, {'error': 'Desktop is busy. Try again.'})
                try:
                    body = {}
                    if self.command == 'POST':
                        try:
                            length = int(self.headers.get('Content-Length', '-1'))
                            if not 0 < length <= MAX_BODY:
                                raise ValueError()
                            body = json.loads(self.rfile.read(length))
                            if not isinstance(body, dict):
                                raise ValueError()
                        except (ValueError, UnicodeError):
                            return self.reply(400, {'error': 'Invalid request body.'})
                    if self.path == '/v1/enroll' and self.command == 'POST':
                        return self.reply(200, owner.enroll(auth.removeprefix('Bearer ')))
                    if (self.command, self.path) not in {('GET', '/v1/snapshot'), ('POST', '/v1/capture'), ('POST', '/v1/reminder'), ('POST', '/v1/transcribe'), ('POST', '/v1/chat'), ('POST', '/v1/job'), ('POST', '/v1/forget')}:
                        return self.reply(404, {'error': 'Unknown companion operation.'})
                    request_id = body.get('requestId')
                    if self.path in ('/v1/job', '/v1/forget'):
                        return self.reply(200, owner.dispatch(self.path, dict(body, _peer=hashlib.sha256(auth.encode()).hexdigest())))
                    if self.command == 'POST':
                        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 128:
                            return self.reply(400, {'error': 'A request ID is required.'})
                        cache_key = (auth, request_id)
                        payload = hashlib.sha256(json.dumps([self.path, body], sort_keys=True).encode()).hexdigest()
                        # Serialize mutations through completion so retries cannot duplicate work.
                        with owner.mutation_lock:
                            durable = self.path == '/v1/capture' and body.get('mode') in ('NOTE', 'REMINDER')
                            persisted = owner.receipt(auth, request_id) if durable else None
                            if persisted:
                                owner.requests[cache_key] = persisted
                            if cache_key in owner.requests:
                                previous, result = owner.requests[cache_key]
                                if previous != payload:
                                    return self.reply(409, {'error': 'Request ID reused with different content.'})
                            else:
                                result = owner.dispatch(self.path, dict(body, _peer=hashlib.sha256(auth.encode()).hexdigest()))
                                if durable:
                                    owner.save_receipt(auth, request_id, payload, result)
                                owner.requests[cache_key] = (payload, result)
                                while len(owner.requests) > 512:
                                    owner.requests.popitem(last=False)
                    else:
                        result = owner.dispatch(self.path, body)
                    self.reply(200, result)
                except ValueError as exc:
                    self.reply(400, {'error': str(exc)})
                except TimeoutError:
                    self.reply(503, {'error': 'Desktop did not respond. Check its status before retrying.'})
                except Exception:
                    self.reply(500, {'error': 'Desktop could not complete this request.'})
                finally:
                    owner.slots.release()

            do_GET = handle_request
            do_POST = handle_request

        class BoundedServer(ThreadingHTTPServer):
            request_queue_size = 8
            workers = threading.BoundedSemaphore(8)

            def process_request(self, request, client_address):
                if not self.workers.acquire(blocking=False):
                    self.shutdown_request(request)
                    return
                try:
                    super().process_request(request, client_address)
                except Exception:
                    self.workers.release()
                    raise

            def process_request_thread(self, request, client_address):
                try:
                    super().process_request_thread(request, client_address)
                finally:
                    self.workers.release()

        self.server = BoundedServer((host, port), Handler)
        self.server.daemon_threads = True
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(cert, key)
        # Wrap accepted sockets with a timeout, not the listening socket: slow TLS
        # clients must not stall the server's accept loop.
        original_get = self.server.get_request
        def get_request():
            connection, address = original_get()
            connection.settimeout(5)
            try:
                return context.wrap_socket(connection, server_side=True), address
            except Exception:
                connection.close()
                raise
        self.server.get_request = get_request
        self.port = self.server.server_port
        self.thread = None
        self.zeroconf = None
        self.service = None

    @contextmanager
    def _receipts(self):
        """Short-lived receipts connection that also closes over the file.

        sqlite3's own context manager commits the transaction but leaves the
        connection open until garbage collection, and Windows refuses to delete
        or move the file while a handle is open. Close it with the transaction.
        """
        with closing(sqlite3.connect(self.directory / 'receipts.sqlite')) as db, db:
            yield db

    def receipt(self, auth, request_id):
        with self._receipts() as db:
            db.execute('CREATE TABLE IF NOT EXISTS receipts (peer TEXT, request TEXT, payload TEXT, result TEXT, created REAL, PRIMARY KEY(peer, request))')
            row = db.execute('SELECT payload, result FROM receipts WHERE peer=? AND request=?', (hashlib.sha256(auth.encode()).hexdigest(), request_id)).fetchone()
            return (row[0], json.loads(row[1])) if row else None

    def save_receipt(self, auth, request_id, payload, result):
        with self._receipts() as db:
            db.execute('INSERT OR REPLACE INTO receipts VALUES (?, ?, ?, ?, ?)', (hashlib.sha256(auth.encode()).hexdigest(), request_id, payload, json.dumps(result), time.time()))
            db.execute('DELETE FROM receipts WHERE rowid NOT IN (SELECT rowid FROM receipts ORDER BY created DESC LIMIT 2000)')

    def new_invite(self):
        with self.lock:
            self.invites = {k: v for k, v in self.invites.items() if v > time.monotonic()}
            invite = secrets.token_hex(32)
            self.invites[invite] = time.monotonic() + 300
            return invite

    def enroll(self, invite):
        with self.lock:
            if self.invites.pop(invite, 0) <= time.monotonic():
                raise ValueError('QR invitation expired or already used. Generate another on the computer.')
            token = secrets.token_hex(32)
            self.tokens.append(token)
            self._save_tokens()
            return {'token': token, 'machineId': self.machine_id}

    def _save_tokens(self):
        temporary = self.credentials.with_suffix('.tmp')
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as output:
            json.dump({'id': self.machine_id, 'tokens': self.tokens}, output)
        temporary.replace(self.credentials)

    def new_phone_token(self):
        with self.lock:
            token = secrets.token_hex(32)
            self.tokens.append(token)
            self._save_tokens()
            return token

    def revoke_all(self):
        with self.lock:
            self.tokens.clear()
            self.invites.clear()
            self.requests.clear()
            self._save_tokens()

    def start(self):
        from zeroconf import IPVersion, ServiceInfo, Zeroconf
        self.zeroconf = Zeroconf(ip_version=IPVersion.V4Only)
        addresses = []
        import ifaddr
        for adapter in ifaddr.get_adapters():
            for ip in adapter.ips:
                if ip.is_IPv4 and not ip.ip.startswith('127.'):
                    addresses.append(socket.inet_aton(ip.ip))
        if not addresses:
            # A route lookup sends no packets, and finds the active LAN interface.
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route:
                route.connect(('192.0.2.1', 9))
                addresses = [route.getsockname()[0]]
                addresses = [socket.inet_aton(addresses[0])]
        self.addresses = [socket.inet_ntoa(address) for address in addresses]
        self.service = ServiceInfo('_neyra._tcp.local.', f'Neyra-{self.machine_id[:8]}._neyra._tcp.local.',
                                   addresses=addresses, port=self.port,
                                   properties={'id': self.machine_id, 'name': self.name, 'version': '1'},
                                   server=f'neyra-{self.machine_id}.local.')
        self.zeroconf.register_service(self.service)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True, name='companion-https')
        self.thread.start()

    def close(self):
        if self.thread:
            self.server.shutdown()
            self.thread.join(timeout=2)
            self.thread = None
        self.server.server_close()
        if self.zeroconf:
            if self.service:
                self.zeroconf.unregister_service(self.service)
            self.zeroconf.close()
            self.zeroconf = None
