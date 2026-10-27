"""Voz's monthly install reporting, retained for the Python runtime port.

Adapted from desert-ant-core Sources/Usage, revision
541a9ce4a148e9308a99f1edbfd927906394b686.
Copyright 2026 Desert Ant Labs B.V. and Neyra contributors.
SPDX-License-Identifier: LicenseRef-DAL-Source-Available-1.0
"""
import base64
from datetime import datetime
import json
import os
from pathlib import Path
import threading
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import uuid

KEYS = {'prod-20261008': 'BHkp0y3mP25qGm6pUkD52BxFH9NB2/px8QMf/fPemZH45msFUHbn+pVE0hgJ2QRmuou1QEFQru3zbUTQY2udOp8='}


def verified(token):
    import jwt
    from cryptography.hazmat.primitives.asymmetric import ec
    header = jwt.get_unverified_header(token)
    if header.get('typ') != 'dal-license+jwt' or header.get('alg') != 'ES256':
        raise ValueError('Unexpected Voz license token.')
    key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), base64.b64decode(KEYS[header['kid']]))
    payload = jwt.decode(token, key, algorithms=['ES256'], options={'verify_aud': False, 'verify_iat': False})
    if payload.get('v') != 1:
        raise ValueError('Unsupported Voz license version.')
    return payload


class VozUsage:
    def __init__(self):
        from PySide6.QtCore import QStandardPaths
        root = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.GenericConfigLocation)) / 'Neyra'
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / 'voz-usage.json'
        self.stop = threading.Event()
        try:
            self.data = json.loads(self.path.read_text())
            uuid.UUID(self.data['installId'])
        except (OSError, ValueError, KeyError, TypeError):
            self.data = {'installId': str(uuid.uuid4())}
            self.save()

    def save(self):
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.data), encoding='utf-8')
        try:
            temporary.chmod(0o600)
        except OSError:
            pass
        temporary.replace(self.path)

    def post(self, route, data):
        headers = {'Content-Type': 'application/json'}
        if os.environ.get('DAL_API_KEY'):
            headers['Authorization'] = 'Bearer ' + os.environ['DAL_API_KEY']
        request = Request('https://events.desertant.com/api/v1/' + route, data=json.dumps(data).encode(), headers=headers)
        with urlopen(request, timeout=10) as response:
            return json.load(response)

    def advance(self):
        token = self.data.get('token')
        if token:
            try:
                payload = verified(token)
            except Exception:
                token = None
            if token and not self.data.get('activated'):
                response = self.post('activate', {'license': token})
                if response.get('activated') is not True:
                    raise ValueError('Voz license activation was not acknowledged.')
                self.data['activated'] = True
                self.save()
            if token and time.time() < datetime.fromisoformat(payload['periodEnd'].replace('Z', '+00:00')).timestamp():
                return
        grant = self.post('license', {'installId': self.data['installId'], 'model': 'voz', 'modelVersion': 'v0.5.0',
                                      'sdk': {'name': 'neyra-python-voz', 'version': '0.1.0'},
                                      'platform': 'server', 'app': {'id': 'com.neyra.desktop'}})
        token = grant['token']
        verified(token)
        self.data.update(token=token, activated=False)
        self.save()
        response = self.post('activate', {'license': token})
        if response.get('activated') is not True:
            raise ValueError('Voz license activation was not acknowledged.')
        self.data['activated'] = True
        self.save()

    def start(self):
        def run():
            while not self.stop.is_set():
                delay = 300
                try:
                    self.advance()
                    delay = 3600
                except HTTPError as exc:
                    delay = 86400 if exc.code in (400, 422) else 300
                except Exception:
                    pass  # Reporting is best effort; offline transcription remains available.
                if self.stop.wait(delay):
                    return
        threading.Thread(target=run, name='voz-monthly-usage', daemon=True).start()

    def close(self):
        self.stop.set()
