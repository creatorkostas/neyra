"""Real loopback TLS tests with isolated synthetic credentials and fake dispatch."""
import http.client
import json
import ssl
import tempfile
import threading
import unittest
from neyra.companion import CompanionServer


class CompanionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.calls = []
        def dispatch(path, body):
            self.calls.append((path, body))
            return {'message': 'saved'}
        self.server = CompanionServer(self.directory.name, dispatch, host='127.0.0.1')
        self.server.thread = threading.Thread(target=self.server.server.serve_forever, daemon=True)
        self.server.thread.start()
        self.addCleanup(self.server.close)
        self.token = self.server.new_phone_token()

    def request(self, path='/v1/snapshot', body=None, token=None):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.load_verify_locations(str(self.server.directory / 'cert.pem'))
        connection = http.client.HTTPSConnection('127.0.0.1', self.server.port, context=context, timeout=3)
        self.addCleanup(connection.close)
        headers = {'Authorization': 'Bearer ' + (self.token if token is None else token)}
        connection.request('POST' if body is not None else 'GET', path, json.dumps(body) if body is not None else None, headers)
        response = connection.getresponse()
        return response.status, json.loads(response.read())

    def test_requires_auth_and_revocation_is_immediate(self):
        self.assertEqual(self.request(token='wrong')[0], 401)
        self.assertEqual(self.request()[0], 200)
        self.server.revoke_all()
        self.assertEqual(self.request()[0], 401)
        self.assertEqual(len(self.calls), 1)

    def test_duplicate_request_only_dispatches_once_and_conflicting_reuse_fails(self):
        body = {'requestId': 'synthetic-1', 'text': 'test', 'mode': 'NOTE'}
        self.assertEqual(self.request('/v1/capture', body)[0], 200)
        self.assertEqual(self.request('/v1/capture', body)[0], 200)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.request('/v1/capture', dict(body, text='different'))[0], 409)

    def test_rejects_unknown_paths_and_missing_request_ids(self):
        self.assertEqual(self.request('/v1/shell', {'requestId': 'a'})[0], 404)
        self.assertEqual(self.request('/v1/capture', {'text': 'test'})[0], 400)
        self.assertFalse(self.calls)

    def test_identity_and_tokens_survive_restart(self):
        replacement = CompanionServer(self.directory.name, lambda *_: {}, host='127.0.0.1')
        self.addCleanup(replacement.close)
        self.assertEqual(self.server.fingerprint, replacement.fingerprint)
        self.assertEqual(self.server.machine_id, replacement.machine_id)
        self.assertEqual(replacement.tokens, [self.token])
