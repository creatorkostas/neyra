"""Neyra's own ChatGPT OAuth registrations and streaming Responses client.

Never reads another application's credentials. All methods are synchronous and
intended for a worker thread. Credential-bearing exceptions are not propagated.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
import ctypes
import errno
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import secrets
import tempfile
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
import uuid

import jwt

from .analytics import AnalyticsStore


ISSUER = "https://auth.openai.com"
RESOURCE = "https://api.openai.com/v1"
MODEL = "gpt-6-luna"
DIRECT_SCOPE = "chatgpt.tokens.use.direct"
TOKEN_ENDPOINT = ISSUER + "/api/accounts/oauth/token"
LOCK_TIMEOUT = 20.0


class ChatGPTError(RuntimeError):
    """Safe to display to the user."""


class ChatGPTCancelled(ChatGPTError):
    pass


def _check(cancel):
    if cancel is not None and cancel.is_set():
        raise ChatGPTCancelled("ChatGPT request cancelled.")


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _DataBlob(ctypes.Structure):
    _fields_ = [("size", ctypes.c_ulong), ("data", ctypes.POINTER(ctypes.c_byte))]


def _protect(data: bytes, decrypt=False) -> bytes:
    if os.name != "nt":
        return data

    buffer = ctypes.create_string_buffer(data)
    source = _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    result = _DataBlob()
    api = ctypes.windll.crypt32
    blob_pointer = ctypes.POINTER(_DataBlob)
    api.CryptProtectData.argtypes = [blob_pointer, ctypes.c_wchar_p, blob_pointer,
                                     ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong, blob_pointer]
    api.CryptProtectData.restype = ctypes.c_int
    api.CryptUnprotectData.argtypes = [blob_pointer, ctypes.POINTER(ctypes.c_wchar_p),
                                       blob_pointer, ctypes.c_void_p, ctypes.c_void_p,
                                       ctypes.c_ulong, blob_pointer]
    api.CryptUnprotectData.restype = ctypes.c_int
    local_free = ctypes.windll.kernel32.LocalFree
    local_free.argtypes = [ctypes.c_void_p]
    local_free.restype = ctypes.c_void_p
    if decrypt:
        ok = api.CryptUnprotectData(ctypes.byref(source), None, None, None, None,
                                    1, ctypes.byref(result))
    else:
        ok = api.CryptProtectData(ctypes.byref(source), "Neyra ChatGPT", None,
                                 None, None, 1, ctypes.byref(result))
    if not ok:
        raise ChatGPTError("Windows could not protect or unlock Neyra's ChatGPT credentials.")
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        local_free(ctypes.cast(result.data, ctypes.c_void_p))


class ChatGPTClient:
    def __init__(self, storage_dir: Path):
        self.storage_dir = Path(storage_dir).expanduser().resolve()
        # A caller cannot accidentally put refresh tokens in this checkout.
        repository = Path(__file__).resolve().parent.parent
        if self.storage_dir == repository or repository in self.storage_dir.parents:
            raise ChatGPTError("ChatGPT credentials must be stored outside the project folder.")
        self.storage_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name != "nt":
            self.storage_dir.chmod(0o700)
        self._path = self.storage_dir / "chatgpt.credentials"
        self._mutex = threading.RLock()
        self._sessions_mutex = threading.Lock()
        self._opener = build_opener(_NoRedirect())
        self._discovery_cache = None
        self._sessions = set()
        self.analytics = AnalyticsStore(self.storage_dir / "usage.json")
        self.on_usage = None
        self.usage_error = ""
        with self._locked():
            data = self._load()
            if not data.get("host_id"):
                data["host_id"] = "urn:uuid:" + str(uuid.uuid4())
                self._save(data)

    @contextmanager
    def _locked(self, cancel=None):
        deadline = time.monotonic() + LOCK_TIMEOUT
        while True:
            _check(cancel)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ChatGPTError("ChatGPT account storage is busy. Please try again shortly.")
            if self._mutex.acquire(timeout=min(0.05, remaining)):
                break
        try:
            _check(cancel)
            try:
                fd = os.open(self.storage_dir / "chatgpt.lock", os.O_CREAT | os.O_RDWR, 0o600)
            except OSError:
                raise ChatGPTError("Neyra could not access its ChatGPT account lock.") from None
            try:
                if os.fstat(fd).st_size == 0:
                    os.write(fd, b"0")
                while True:
                    _check(cancel)
                    if time.monotonic() >= deadline:
                        raise ChatGPTError("ChatGPT account storage is busy. Please try again shortly.")
                    try:
                        self._file_lock(fd)
                        break
                    except OSError as error:
                        if error.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                            raise ChatGPTError("Neyra could not lock its ChatGPT account storage.") from None
                        pause = min(0.05, max(0, deadline - time.monotonic()))
                        if cancel is not None:
                            cancel.wait(pause)
                        else:
                            time.sleep(pause)
                try:
                    yield
                finally:
                    if os.name == "nt":
                        import msvcrt
                        os.lseek(fd, 0, os.SEEK_SET)
                        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)
        finally:
            self._mutex.release()

    @staticmethod
    def _file_lock(fd):
        os.lseek(fd, 0, os.SEEK_SET)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _load(self):
        if not self._path.exists():
            return {"accounts": {}, "active_id": None}
        try:
            data = json.loads(_protect(self._path.read_bytes(), decrypt=True))
            if not isinstance(data.get("accounts"), dict):
                raise ValueError()
            return data
        except (ValueError, OSError):
            raise ChatGPTError("Neyra could not read its saved ChatGPT accounts.") from None

    def _save(self, data):
        raw = _protect(json.dumps(data).encode())
        fd, name = tempfile.mkstemp(prefix=".chatgpt-", dir=self.storage_dir)
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(raw)
                output.flush()
                os.fsync(output.fileno())
            os.replace(name, self._path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    @property
    def active_id(self):
        with self._locked():
            return self._load().get("active_id")

    def accounts(self):
        with self._locked():
            return [{"id": key, "label": value["label"],
                     "connected": bool(value.get("access_token"))}
                    for key, value in self._load()["accounts"].items()]

    def select_account(self, account_id):
        with self._locked():
            data = self._load()
            if account_id not in data["accounts"]:
                raise ChatGPTError("Choose a saved ChatGPT account first.")
            data["active_id"] = account_id
            self._save(data)

    @staticmethod
    def _error(status, code=""):
        if code in {"subscription_sharing_usage_limit_exceeded", "subscription_sharing_usage_unavailable"}:
            return ChatGPTError("ChatGPT plan usage is unavailable or its limit was reached. Check ChatGPT Settings → Usage.")
        if status == 401 or code in {"invalid_grant", "invalid_token"}:
            return ChatGPTError("Your ChatGPT session expired. Continue with ChatGPT again.")
        if status == 429:
            return ChatGPTError("ChatGPT is rate limited or its usage limit was reached. Try again later.")
        if status == 403:
            return ChatGPTError("ChatGPT did not permit this request. Check the app's plan permission in ChatGPT Settings.")
        if code in {"model_not_found", "unsupported_model", "model_not_available"} or status == 404:
            return ChatGPTError("The selected ChatGPT account cannot use gpt-6-luna. Neyra requires that exact model.")
        return ChatGPTError("ChatGPT could not complete the request. Try again or reconnect your account.")

    @contextmanager
    def _open(self, request, cancel=None):
        _check(cancel)
        response = None
        stopped = threading.Event()
        # Closing the response interrupts a live stream when possible. Socket
        # timeout also bounds connection establishment and stalled reads.
        def watch():
            while not stopped.wait(0.1):
                if cancel is not None and cancel.is_set():
                    if response is not None:
                        try:
                            response.close()
                        except OSError:
                            pass
                    return
        watcher = threading.Thread(target=watch, daemon=True)
        watcher.start()
        try:
            response = self._opener.open(request, timeout=20)
            _check(cancel)
            yield response
            _check(cancel)
        except HTTPError as exc:
            try:
                body = json.loads(exc.read(65536))
                error = body.get("error", {})
                code = error.get("code", "") if isinstance(error, dict) else error
            except (ValueError, OSError):
                code = ""
            finally:
                exc.close()
            raise self._error(exc.code, code) from None
        except (URLError, OSError, TimeoutError, ValueError) as exc:
            _check(cancel)
            raise ChatGPTError("ChatGPT connection failed or timed out. Check your network and try again.") from None
        finally:
            stopped.set()
            if response is not None:
                response.close()

    def _json(self, url, fields=None, cancel=None):
        body = urlencode(fields).encode() if fields is not None else None
        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        with self._open(Request(url, data=body, headers=headers), cancel) as response:
            try:
                result = json.loads(response.read(2_000_000))
                if not isinstance(result, dict):
                    raise ValueError()
                return result
            except ValueError:
                raise ChatGPTError("ChatGPT returned an invalid response.") from None

    def _discovery(self, cancel=None):
        if self._discovery_cache is None:
            config = self._json(ISSUER + "/.well-known/openid-configuration", cancel=cancel)
            if config.get("issuer") != ISSUER:
                raise ChatGPTError("ChatGPT identity configuration could not be verified.")
            for key in ("jwks_uri", "revocation_endpoint"):
                url = urlsplit(config.get(key, ""))
                if url.scheme != "https" or url.netloc != "auth.openai.com":
                    raise ChatGPTError("ChatGPT identity configuration could not be verified.")
            self._discovery_cache = config
        return self._discovery_cache

    def _identity(self, token, client_id, nonce, cancel):
        config = self._discovery(cancel)
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") not in {"RS256", "ES256"}:
                raise ValueError()
            keys = self._json(config["jwks_uri"], cancel=cancel).get("keys", [])
            candidates = [key for key in keys if key.get("kid") == header.get("kid")]
            if len(candidates) != 1:
                raise ValueError()
            key = jwt.PyJWK.from_dict(candidates[0], algorithm=header["alg"])
            claims = jwt.decode(token, key.key, algorithms=[header["alg"]],
                                audience=client_id, issuer=ISSUER, leeway=5,
                                options={"require": ["sub", "exp", "iat", "nonce"]})
            if not isinstance(claims["sub"], str) or not claims["sub"]:
                raise ValueError()
            if not secrets.compare_digest(str(claims["nonce"]), nonce):
                raise ValueError()
            if isinstance(claims.get("aud"), list) and len(claims["aud"]) > 1 and claims.get("azp") != client_id:
                raise ValueError()
            return claims
        except (jwt.PyJWTError, ValueError, KeyError, TypeError):
            raise ChatGPTError("ChatGPT identity could not be verified. Please sign in again.") from None

    @staticmethod
    def _tokens(tokens, previous=None):
        previous = previous or {}
        scopes = tokens.get("scope", " ".join(previous.get("scopes", []))).split()
        if DIRECT_SCOPE not in scopes:
            raise ChatGPTError("ChatGPT plan usage was not granted. Enable the app's plan permission and sign in again.")
        access = tokens.get("access_token")
        refresh = tokens.get("refresh_token", previous.get("refresh_token"))
        if not isinstance(access, str) or not access or not isinstance(refresh, str) or not refresh:
            raise ChatGPTError("ChatGPT did not return a renewable session. Please sign in again.")
        if str(tokens.get("token_type", "")).lower() != "bearer":
            raise ChatGPTError("ChatGPT returned an unsupported session type.")
        try:
            expires = float(tokens["expires_in"])
            if not 0 < expires < 365 * 86400:
                raise ValueError()
        except (KeyError, ValueError, TypeError):
            raise ChatGPTError("ChatGPT returned an invalid session lifetime.") from None
        return {"access_token": access, "refresh_token": refresh, "scopes": scopes,
                "expires_at": time.time() + expires,
                "id_token": tokens.get("id_token", previous.get("id_token"))}

    def sign_in(self, open_url, cancel: threading.Event, account_id=None):
        with self._locked(cancel):
            data = self._load()
            saved = data["accounts"].get(account_id) if account_id else None
            if account_id and saved is None:
                raise ChatGPTError("That saved ChatGPT account no longer exists.")
            saved = dict(saved) if saved else None
            host = data["host_id"]
            pending_client = data.get("pending_client_id")
        state, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(3))
        result = {}

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                parsed = urlsplit(self.path)
                query = parse_qs(parsed.query)
                valid = (parsed.path == "/auth/callback" and
                         query.get("state") == [state] and
                         all(len(value) == 1 for value in query.values()))
                if valid and not result:
                    result.update({key: value[0] for key, value in query.items()})
                self.send_response(200 if valid else 400)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(b"Return to Neyra to finish signing in." if valid else b"Invalid sign-in callback.")

        class CallbackServer(HTTPServer):
            def get_request(self):
                connection, address = super().get_request()
                connection.settimeout(1)
                return connection, address

        server = CallbackServer(("127.0.0.1", 0), Handler)
        server.timeout = 0.2
        redirect = f"http://127.0.0.1:{server.server_port}/auth/callback"
        client_id = saved["client_id"] if saved else pending_client or "dynamic_agent_client"
        registering = client_id == "dynamic_agent_client"
        params = {"client_id": client_id, "ext_agent_host_id": host,
                  "response_type": "code", "redirect_uri": redirect,
                  "scope": "openid profile email offline_access resource.invoke " + DIRECT_SCOPE,
                  "resource": RESOURCE, "state": state, "nonce": nonce,
                  "code_challenge_method": "S256",
                  "code_challenge": base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()}
        if saved:
            if saved.get("id_token"):
                params["id_token_hint"] = saved["id_token"]
            if saved.get("email"):
                params["login_hint"] = saved["email"]
        elif registering:
            params["agent_name_hint"] = "Neyra"
        try:
            _check(cancel)
            try:
                opened = open_url(ISSUER + "/api/accounts/authorize?" + urlencode(params))
                if opened is False:
                    raise ChatGPTError("Could not open the browser for ChatGPT sign-in.")
            except ChatGPTError:
                raise
            except Exception:
                raise ChatGPTError("Could not open the browser for ChatGPT sign-in.") from None
            deadline = time.monotonic() + 300
            while not result:
                _check(cancel)
                if time.monotonic() >= deadline:
                    raise ChatGPTError("ChatGPT sign-in timed out. Please try again.")
                server.handle_request()
        finally:
            server.server_close()
        _check(cancel)
        if result.get("error"):
            raise ChatGPTError("ChatGPT sign-in was declined or could not complete. Please try again.")
        issued = result.get("client_id", "" if registering else client_id)
        if not issued or issued == "dynamic_agent_client" or (not registering and issued != client_id):
            raise ChatGPTError("ChatGPT registration was incomplete or did not match the selected account.")
        if not result.get("code"):
            raise ChatGPTError("ChatGPT did not return a sign-in code.")
        if not saved:
            # Keep an issued registration even if code exchange fails. Its next
            # attempt uses fresh state/PKCE rather than registering another client.
            with self._locked(cancel):
                data = self._load()
                data["pending_client_id"] = issued
                self._save(data)
        tokens = self._json(TOKEN_ENDPOINT, {"grant_type": "authorization_code", "client_id": issued,
                            "code": result["code"], "code_verifier": verifier,
                            "redirect_uri": redirect, "resource": RESOURCE}, cancel)
        claims = self._identity(tokens.get("id_token", ""), issued, nonce, cancel)
        if saved and claims["sub"] != saved["subject"]:
            raise ChatGPTError("ChatGPT signed in to a different account. Add it as a separate account.")
        credentials = self._tokens(tokens)
        key = hashlib.sha256((ISSUER + "\0" + issued + "\0" + claims["sub"]).encode()).hexdigest()
        email = claims.get("email") if isinstance(claims.get("email"), str) else "ChatGPT account"
        record = {"issuer": ISSUER, "subject": claims["sub"], "client_id": issued,
                  "email": email, "label": f"{email} · {key[:8]}", **credentials}
        with self._locked(cancel):
            data = self._load()
            data["accounts"][key] = record
            data["active_id"] = key
            if data.get("pending_client_id") == issued:
                data.pop("pending_client_id", None)
            self._save(data)
        return record["label"]

    def _access(self, cancel, with_account=False):
        with self._locked(cancel):
            data = self._load()
            account_id = data.get("active_id")
            record = data["accounts"].get(account_id)
            if not record or not record.get("access_token"):
                raise ChatGPTError("Continue with ChatGPT to connect an account first.")
            if record.get("expires_at", 0) <= time.time() + 60:
                tokens = self._json(TOKEN_ENDPOINT, {"grant_type": "refresh_token",
                                    "client_id": record["client_id"],
                                    "refresh_token": record["refresh_token"], "resource": RESOURCE}, cancel)
                updated = self._tokens(tokens, record)
                # Keep the already verified ID token for returning-login hints;
                # refresh responses do not carry the original login nonce.
                updated["id_token"] = record.get("id_token")
                record.update(updated)
                self._save(data)
            if DIRECT_SCOPE not in record.get("scopes", []):
                raise ChatGPTError("ChatGPT plan usage permission is missing. Sign in again.")
            return (record["access_token"], account_id) if with_account else record["access_token"]

    def sign_out(self):
        # Stop this client's current streams before revoking the active session.
        with self._sessions_mutex:
            for cancel in self._sessions:
                cancel.set()
        confirmed = False
        with self._locked():
            data = self._load()
            record = data["accounts"].get(data.get("active_id"))
            if not record:
                return "No ChatGPT account is selected."
            refresh = record.get("refresh_token")
            if refresh:
                for attempt in range(2):
                    try:
                        endpoint = self._discovery()["revocation_endpoint"]
                        body = urlencode({"token": refresh, "token_type_hint": "refresh_token",
                                          "client_id": record["client_id"]}).encode()
                        with self._open(Request(endpoint, data=body, headers={
                                "Content-Type": "application/x-www-form-urlencoded"})) as response:
                            confirmed = response.status == 200
                        if confirmed:
                            break
                    except ChatGPTError:
                        if attempt == 0:
                            time.sleep(0.25)
            for key in ("access_token", "refresh_token", "id_token", "scopes", "expires_at"):
                record.pop(key, None)
            self._save(data)
        if confirmed or not refresh:
            return "Signed out of ChatGPT."
        return "Signed out locally. Remote revocation was not confirmed; disconnect Neyra in ChatGPT Settings."

    def _record_usage(self, account_id, response):
        usage = response.get("usage")
        if not isinstance(usage, dict):
            return
        try:
            self.analytics.record(account_id, usage, request_id=response.get("id"))
            self.usage_error = ""
        except (OSError, ValueError):
            self.usage_error = "Token tracking could not be saved. Counts may be incomplete."
        if self.on_usage:
            try:
                self.on_usage()
            except Exception:
                pass

    def respond(self, instructions: str, input_text: str, cancel: threading.Event, on_delta, *, max_output_tokens=4096) -> str:
        if not isinstance(max_output_tokens, int) or isinstance(max_output_tokens, bool) or not 128 <= max_output_tokens <= 32768:
            raise ValueError("Invalid response token limit.")
        with self._sessions_mutex:
            self._sessions.add(cancel)
        try:
            token, account_id = self._access(cancel, with_account=True)
            payload = {"model": MODEL, "reasoning": {"effort": "low"},
                       "instructions": instructions,
                       "input": [{"role": "user", "content": input_text}],
                       "store": False, "stream": True,
                       "max_output_tokens": max_output_tokens,
                       "prompt_cache_key": "neyra:" + hashlib.sha256(account_id.encode()).hexdigest()[:32]}
            request = Request(RESOURCE + "/responses", data=json.dumps(payload).encode(),
                              headers={"Authorization": "Bearer " + token,
                                       "Content-Type": "application/json", "Accept": "text/event-stream"})
            chunks, completed, event_data = [], False, []
            with self._open(request, cancel) as response:
                while True:
                    _check(cancel)
                    line = response.readline(1_000_001)
                    if len(line) > 1_000_000:
                        raise ChatGPTError("ChatGPT returned an oversized stream event.")
                    if not line:
                        break
                    if line.rstrip(b"\r\n"):
                        if line.startswith(b"data:"):
                            event_data.append(line[5:].strip())
                            if sum(map(len, event_data)) > 2_000_000:
                                raise ChatGPTError("ChatGPT returned an oversized stream event.")
                        continue
                    if not event_data:
                        continue
                    raw = b"\n".join(event_data)
                    event_data.clear()
                    if raw == b"[DONE]":
                        break
                    try:
                        event = json.loads(raw)
                        kind = event["type"]
                    except (ValueError, KeyError, TypeError):
                        raise ChatGPTError("ChatGPT returned an invalid stream event.") from None
                    if kind == "response.output_text.delta":
                        delta = event.get("delta")
                        if not isinstance(delta, str):
                            raise ChatGPTError("ChatGPT returned invalid text.")
                        chunks.append(delta)
                        on_delta(delta)
                    elif kind == "response.completed":
                        final_response = event.get("response", {})
                        if not isinstance(final_response, dict) or final_response.get("status", "completed") != "completed":
                            raise ChatGPTError("ChatGPT did not complete the response.")
                        self._record_usage(account_id, final_response)
                        completed = True
                        break
                    elif kind in {"response.failed", "response.incomplete", "error"}:
                        failed_response = event.get("response")
                        if isinstance(failed_response, dict):
                            self._record_usage(account_id, failed_response)
                        error = ((failed_response.get("error") if isinstance(failed_response, dict) else None)
                                 or event.get("error") or event)
                        if not isinstance(error, dict):
                            error = {}
                        raise self._error(0, error.get("code", ""))
            _check(cancel)
            if not completed:
                raise ChatGPTError("ChatGPT's stream ended before completion. Any partial text is incomplete.")
            return "".join(chunks)
        finally:
            with self._sessions_mutex:
                self._sessions.discard(cancel)
