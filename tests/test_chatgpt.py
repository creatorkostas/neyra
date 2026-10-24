"""Synthetic OAuth, credential storage, and streaming protocol checks."""
import io
import base64
import hashlib
import errno
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import urlopen
from urllib.error import HTTPError

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from neyra.chatgpt import (ChatGPTClient, ChatGPTError, ChatGPTCancelled,
                          DIRECT_SCOPE, ISSUER, RESOURCE, _protect)


class Response(io.BytesIO):
    status = 200


def stream(*events):
    return Response(b"".join(b"data: " + json.dumps(event).encode() + b"\n\n" for event in events))


def image_data_url(image_format="PNG"):
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QImage

    image = QImage(2, 2, QImage.Format.Format_RGB32)
    image.fill(0xff427ac4)
    encoded = QByteArray()
    buffer = QBuffer(encoded)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, image_format)
    buffer.close()
    mime = "jpeg" if image_format == "JPEG" else "png"
    return f"data:image/{mime};base64," + base64.b64encode(bytes(encoded)).decode("ascii")


class ChatGPTTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="neyra-chatgpt-")
        self.addCleanup(self.directory.cleanup)
        self.client = ChatGPTClient(Path(self.directory.name))
        self.cancel = threading.Event()
        self.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.private_key.public_key()))
        self.jwk.update(kid="test-key", alg="RS256")

    def token(self, nonce="nonce", audience="issued-client", **changes):
        claims = {"iss": ISSUER, "aud": audience, "sub": "subject", "iat": int(time.time()),
                  "exp": int(time.time()) + 3600, "nonce": nonce, "email": "person@example.test"}
        claims.update(changes)
        return jwt.encode(claims, self.private_key, algorithm="RS256", headers={"kid": "test-key"})

    def tokens(self, **changes):
        result = {"access_token": "synthetic-access", "refresh_token": "synthetic-refresh",
                  "token_type": "Bearer", "expires_in": 3600,
                  "scope": DIRECT_SCOPE, "id_token": "synthetic-id"}
        result.update(changes)
        return result

    def save_account(self, key="account", **changes):
        record = {"subject": "subject", "client_id": "issued-client", "email": "person@example.test",
                  "label": "Person · account", **self.client._tokens(self.tokens())}
        record.update(changes)
        with self.client._locked():
            data = self.client._load()
            data["accounts"][key] = record
            data["active_id"] = key
            self.client._save(data)

    def identity_network(self, url, fields=None, cancel=None):
        if url.endswith("openid-configuration"):
            return {"issuer": ISSUER, "jwks_uri": ISSUER + "/keys",
                    "revocation_endpoint": ISSUER + "/revoke"}
        return {"keys": [self.jwk]}

    def test_host_and_accounts_persist_without_exposing_tokens(self):
        self.save_account()
        second = ChatGPTClient(Path(self.directory.name))
        self.assertEqual(self.client._load()["host_id"], second._load()["host_id"])
        self.assertTrue(second._load()["host_id"].startswith("urn:uuid:"))
        self.assertEqual(second.accounts(), [{"id": "account", "label": "Person · account", "connected": True}])
        self.assertEqual(second.active_id, "account")

    def test_reject_storage_in_repository(self):
        with self.assertRaises(ChatGPTError):
            ChatGPTClient(Path(__file__).resolve().parent.parent / "credentials")

    def test_account_selection_is_separate(self):
        self.save_account("first")
        self.save_account("second", client_id="another-client")
        self.client.select_account("first")
        self.assertEqual(self.client.active_id, "first")
        with self.assertRaises(ChatGPTError):
            self.client.select_account("missing")

    def test_identity_verifies_signature_issuer_audience_expiry_and_nonce(self):
        with patch.object(self.client, "_json", side_effect=self.identity_network):
            self.assertEqual(self.client._identity(self.token(), "issued-client", "nonce", self.cancel)["sub"], "subject")
            invalid = [self.token(iss="https://invalid.example"), self.token(audience="other"),
                       self.token(exp=1), self.token(nonce="wrong"), self.token(sub="")]
            wrong_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            invalid.append(jwt.encode({"sub": "subject"}, wrong_key, algorithm="RS256", headers={"kid": "test-key"}))
            for token in invalid:
                with self.subTest(token=invalid.index(token)), self.assertRaises(ChatGPTError):
                    self.client._identity(token, "issued-client", "nonce", self.cancel)

    def test_identity_rejects_unsigned_token(self):
        token = jwt.encode({"sub": "subject"}, "", algorithm="none")
        with patch.object(self.client, "_json", side_effect=self.identity_network), self.assertRaises(ChatGPTError):
            self.client._identity(token, "issued-client", "nonce", self.cancel)

    def test_plan_scope_required(self):
        with self.assertRaisesRegex(ChatGPTError, "plan usage was not granted"):
            self.client._tokens(self.tokens(scope="openid email"))

    def sign_in(self, issued="issued-client", account_id=None, callback_changes=None):
        queries, exchanges, threads = [], [], []

        def open_browser(url):
            query = {key: values[0] for key, values in parse_qs(urlsplit(url).query).items()}
            queries.append(query)
            callback = {"code": "synthetic-code", "state": query["state"], "client_id": issued}
            callback.update(callback_changes or {})

            def visit():
                with urlopen(query["redirect_uri"] + "?" + urlencode(callback), timeout=3) as response:
                    response.read()
            thread = threading.Thread(target=visit)
            threads.append(thread)
            thread.start()

        def exchange(url, fields=None, cancel=None):
            if fields and fields.get("grant_type") == "authorization_code":
                exchanges.append(fields)
                return self.tokens(id_token=self.token(queries[-1]["nonce"], audience=issued))
            return self.identity_network(url, fields, cancel)

        try:
            with patch.object(self.client, "_json", side_effect=exchange):
                label = self.client.sign_in(open_browser, self.cancel, account_id)
            return label, queries, exchanges
        finally:
            for thread in threads:
                thread.join(4)

    def test_dynamic_sign_in_and_reauthorization(self):
        label, queries, exchanges = self.sign_in()
        query, exchange = queries[0], exchanges[0]
        self.assertIn("person@example.test", label)
        self.assertEqual(query["client_id"], "dynamic_agent_client")
        self.assertEqual(query["agent_name_hint"], "Neyra")
        self.assertEqual(query["resource"], RESOURCE)
        self.assertEqual(exchange["client_id"], "issued-client")
        self.assertEqual(query["redirect_uri"], exchange["redirect_uri"])
        self.assertTrue(query["redirect_uri"].startswith("http://127.0.0.1:"))
        import base64
        import hashlib
        challenge = base64.urlsafe_b64encode(hashlib.sha256(exchange["code_verifier"].encode()).digest()).rstrip(b"=").decode()
        self.assertEqual(query["code_challenge"], challenge)
        active = self.client.active_id
        _, returning, _ = self.sign_in(account_id=active)
        self.assertEqual(returning[0]["client_id"], "issued-client")
        self.assertNotIn("agent_name_hint", returning[0])
        self.assertIn("id_token_hint", returning[0])
        self.assertEqual(len(self.client.accounts()), 1)

    def test_missing_or_changed_issued_id_rejected(self):
        with self.assertRaisesRegex(ChatGPTError, "registration was incomplete"):
            self.sign_in(issued="")
        self.save_account()
        with self.assertRaisesRegex(ChatGPTError, "registration was incomplete"):
            self.sign_in(issued="different-client", account_id="account")
        self.assertEqual(self.client.active_id, "account")

    def test_callback_access_denied_preserves_previous_account(self):
        self.save_account()
        with self.assertRaisesRegex(ChatGPTError, "declined"):
            self.sign_in(callback_changes={"error": "access_denied"})
        self.assertEqual(self.client.active_id, "account")

    def test_login_cancelled_without_opening_browser(self):
        self.cancel.set()
        with self.assertRaises(ChatGPTCancelled):
            self.client.sign_in(lambda url: self.fail("browser should not open"), self.cancel)

    def test_failed_exchange_keeps_issued_registration_for_retry(self):
        with patch.object(self.client, "_identity", side_effect=ChatGPTError("synthetic validation failure")):
            with self.assertRaises(ChatGPTError):
                self.sign_in()
        self.assertIsNone(self.client.active_id)
        _, query, _ = self.sign_in()
        self.assertEqual(query[0]["client_id"], "issued-client")
        self.assertNotIn("agent_name_hint", query[0])

    def test_wrong_state_does_not_exchange_code(self):
        threads = []
        def browser(url):
            query = parse_qs(urlsplit(url).query)
            def callback():
                try:
                    urlopen(query["redirect_uri"][0] + "?state=wrong&code=synthetic", timeout=3)
                except HTTPError as error:
                    self.assertEqual(error.code, 400)
                    error.close()
                finally:
                    self.cancel.set()
            thread = threading.Thread(target=callback)
            threads.append(thread)
            thread.start()
        with patch.object(self.client, "_json") as network, self.assertRaises(ChatGPTCancelled):
            self.client.sign_in(browser, self.cancel)
        for thread in threads:
            thread.join(4)
        network.assert_not_called()
        self.assertEqual(self.client.accounts(), [])

    def test_credentials_protected_at_rest(self):
        self.save_account()
        if os.name == "nt":
            self.assertNotIn(b"synthetic-access", self.client._path.read_bytes())
            self.assertNotIn(b"synthetic-refresh", self.client._path.read_bytes())
        else:
            self.assertEqual(self.client._path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(self.client.storage_dir.stat().st_mode & 0o777, 0o700)

    @unittest.skipUnless(os.name == "nt", "requires actual Windows DPAPI")
    def test_actual_windows_dpapi_roundtrip(self):
        plaintext = b"Neyra synthetic credentials\x00" + bytes(range(256))
        ciphertext = _protect(plaintext)
        self.assertNotEqual(ciphertext, plaintext)
        self.assertEqual(_protect(ciphertext, decrypt=True), plaintext)

    def test_thread_lock_wait_is_bounded_and_cancellable(self):
        held, release = threading.Event(), threading.Event()
        def holder():
            with self.client._locked():
                held.set()
                release.wait(5)
        thread = threading.Thread(target=holder)
        thread.start()
        self.assertTrue(held.wait(3))
        try:
            with patch("neyra.chatgpt.LOCK_TIMEOUT", 0.1):
                started = time.monotonic()
                with self.assertRaisesRegex(ChatGPTError, "storage is busy"):
                    with self.client._locked():
                        self.fail("must not acquire held lock")
                self.assertLess(time.monotonic() - started, 1)
            timer = threading.Timer(0.05, self.cancel.set)
            timer.start()
            try:
                with self.assertRaises(ChatGPTCancelled):
                    self.client.respond("", "", self.cancel, lambda _: None)
            finally:
                timer.join(1)
        finally:
            release.set()
            thread.join(3)

    def test_file_lock_wait_is_bounded_and_cancellable(self):
        busy = OSError(errno.EACCES, "synthetic busy lock")
        with patch.object(self.client, "_file_lock", side_effect=busy):
            with patch("neyra.chatgpt.LOCK_TIMEOUT", 0.1):
                with self.assertRaisesRegex(ChatGPTError, "storage is busy"):
                    with self.client._locked():
                        self.fail("must not acquire held lock")
            timer = threading.Timer(0.05, self.cancel.set)
            timer.start()
            try:
                with self.assertRaises(ChatGPTCancelled):
                    with self.client._locked(self.cancel):
                        self.fail("must not acquire held lock")
            finally:
                timer.join(1)

    def test_unexpected_file_lock_error_fails_without_retry(self):
        with patch.object(self.client, "_file_lock", side_effect=OSError(errno.EBADF, "synthetic invalid fd")) as lock:
            with self.assertRaisesRegex(ChatGPTError, "could not lock"):
                with self.client._locked():
                    self.fail("must not acquire broken lock")
        self.assertEqual(lock.call_count, 1)
        with self.client._locked():
            pass  # Error path releases the thread mutex and file descriptor.

    def test_refresh_rotates_and_is_shared_by_client_instances(self):
        self.save_account(expires_at=1)
        second = ChatGPTClient(Path(self.directory.name))
        calls = []
        def refresh(url, fields=None, cancel=None):
            calls.append(fields)
            time.sleep(0.05)
            return self.tokens(access_token="new-access", refresh_token="rotated-refresh")
        outputs = []
        with patch.object(self.client, "_json", side_effect=refresh), patch.object(second, "_json", side_effect=refresh):
            threads = [threading.Thread(target=lambda client=c: outputs.append(client._access(self.cancel))) for c in (self.client, second)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(5)
        self.assertEqual(outputs, ["new-access", "new-access"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["client_id"], "issued-client")
        self.assertNotIn("scope", calls[0])
        self.assertEqual(second._load()["accounts"]["account"]["refresh_token"], "rotated-refresh")

    def test_sign_out_revokes_and_keeps_registration(self):
        self.save_account()
        requests = []
        def opened(request, timeout):
            requests.append(request)
            return Response()
        with patch.object(self.client, "_json", side_effect=self.identity_network), patch.object(self.client._opener, "open", side_effect=opened):
            self.assertEqual(self.client.sign_out(), "Signed out of ChatGPT.")
        form = parse_qs(requests[0].data.decode())
        self.assertEqual(form["client_id"], ["issued-client"])
        self.assertEqual(form["token_type_hint"], ["refresh_token"])
        record = self.client._load()["accounts"]["account"]
        self.assertEqual(record["client_id"], "issued-client")
        self.assertNotIn("access_token", record)
        self.assertNotIn("id_token", record)
        self.assertFalse(self.client.accounts()[0]["connected"])

    def test_unconfirmed_revocation_removes_local_tokens_and_says_so(self):
        self.save_account()
        with patch.object(self.client, "_discovery", side_effect=ChatGPTError("offline")), patch("neyra.chatgpt.time.sleep"):
            self.assertIn("Remote revocation was not confirmed", self.client.sign_out())
        self.assertFalse(self.client.accounts()[0]["connected"])

    def test_response_exact_model_payload_and_completed_required(self):
        self.save_account()
        response = stream({"type": "response.output_text.delta", "delta": "Hello"},
                          {"type": "response.output_text.delta", "delta": " world"},
                          {"type": "response.completed", "response": {"status": "completed"}})
        deltas = []
        with patch.object(self.client._opener, "open", return_value=response) as opened:
            text = self.client.respond("instructions", "input", self.cancel, deltas.append)
        self.assertEqual(text, "Hello world")
        self.assertEqual(deltas, ["Hello", " world"])
        request = opened.call_args.args[0]
        self.assertEqual(request.full_url, RESOURCE + "/responses")
        self.assertEqual(json.loads(request.data), {"model": "gpt-6-luna", "reasoning": {"effort": "low"},
                         "instructions": "instructions", "input": [{"role": "user", "content": "input"}],
                         "store": False, "stream": True, "max_output_tokens": 4096,
                         "prompt_cache_key": "neyra:" + hashlib.sha256(b"account").hexdigest()[:32]})
        self.assertTrue(response.closed)

    def test_response_image_payload_uses_inline_high_detail_and_preserves_stream_contract(self):
        self.save_account()
        for image_format in ("JPEG", "PNG"):
            image = image_data_url(image_format)
            response = stream({"type": "response.output_text.delta", "delta": "A synthetic image."},
                              {"type": "response.completed", "response": {"status": "completed"}})
            deltas = []
            with self.subTest(image_format=image_format), patch.object(self.client._opener, "open", return_value=response) as opened:
                result = self.client.respond("instructions", "Describe this screen", self.cancel, deltas.append,
                                             image_data_url=image, max_output_tokens=2048)
            payload = json.loads(opened.call_args.args[0].data)
            self.assertEqual(payload["input"], [{"role": "user", "content": [
                {"type": "input_text", "text": "Describe this screen"},
                {"type": "input_image", "image_url": image, "detail": "high"},
            ]}])
            self.assertEqual(payload["model"], "gpt-6-luna")
            self.assertEqual(payload["max_output_tokens"], 2048)
            self.assertFalse(payload["store"])
            self.assertEqual(result, "A synthetic image.")
            self.assertEqual(deltas, [result])
            self.assertTrue(response.closed)

    def test_invalid_image_inputs_are_rejected_before_authentication_or_network(self):
        png = image_data_url()
        bad_images = (
            "https://example.test/screen.png", "file:///private/screen.png", "",
            "data:image/svg+xml;base64,PHN2Zy8+", "data:image/jpeg;base64,not base64!",
            "data:image/png;base64,", "data:image/png;base64," + base64.b64encode(b"not an image").decode(),
            png.replace("image/png", "image/jpeg"), png + "\n", png + "=", 42,
            "data:image/png;base64," + "A" * (6 * 1024 * 1024),
        )
        with patch.object(self.client, "_access") as access, patch.object(self.client._opener, "open") as opened:
            for image in bad_images:
                with self.subTest(image=str(image)[:65]), self.assertRaises(ValueError):
                    self.client.respond("", "screen", self.cancel, lambda _: None, image_data_url=image)
            access.assert_not_called()
            opened.assert_not_called()
        self.assertEqual(self.client._sessions, set())

    def test_completed_response_records_usage_for_the_request_account(self):
        self.save_account()
        usage = {"input_tokens": 120, "input_tokens_details": {"cached_tokens": 80}, "output_tokens": 35, "total_tokens": 155}
        response = stream({"type": "response.output_text.delta", "delta": "Done"},
                          {"type": "response.completed", "response": {"id": "response-1", "usage": usage}})
        notified = []
        self.client.on_usage = lambda: notified.append(True)
        with patch.object(self.client._opener, "open", return_value=response):
            self.assertEqual(self.client.respond("", "", self.cancel, lambda _: None), "Done")
        counts = self.client.analytics.snapshot("account")
        self.assertEqual(counts["total_tokens"], 155)
        self.assertEqual(counts["cached_input_tokens"], 80)
        self.assertEqual(counts["requests"], 1)
        self.assertEqual(notified, [True])
        self.client._record_usage("account", {"id": "response-1", "usage": usage})
        self.assertEqual(self.client.analytics.snapshot("account")["requests"], 1)
        self.assertEqual(self.client.analytics.snapshot("different-account")["total_tokens"], 0)

    def test_token_tracking_failure_does_not_fail_inference(self):
        self.save_account()
        response = stream({"type": "response.completed", "response": {
            "usage": {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3}}})
        with patch.object(self.client._opener, "open", return_value=response), patch.object(self.client.analytics, "record", side_effect=OSError("disk full")):
            self.assertEqual(self.client.respond("", "", self.cancel, lambda _: None), "")
        self.assertIn("incomplete", self.client.usage_error)

    def test_failed_terminal_usage_is_counted_without_marking_response_success(self):
        self.save_account()
        response = stream({"type": "response.incomplete", "response": {
            "id": "incomplete-1", "usage": {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12}}})
        with patch.object(self.client._opener, "open", return_value=response), self.assertRaises(ChatGPTError):
            self.client.respond("", "", self.cancel, lambda _: None)
        self.assertEqual(self.client.analytics.snapshot("account")["total_tokens"], 12)

    def test_output_limits_validate_and_cache_key_is_stable_and_account_scoped(self):
        self.save_account()
        keys = []
        for _ in range(2):
            response = stream({"type": "response.completed"})
            with patch.object(self.client._opener, "open", return_value=response) as opened:
                self.client.respond("same prefix", "changing suffix", self.cancel, lambda _: None, max_output_tokens=2048)
            payload = json.loads(opened.call_args.args[0].data)
            keys.append(payload["prompt_cache_key"])
            self.assertEqual(payload["max_output_tokens"], 2048)
            self.assertFalse(payload["store"])
            self.assertNotIn("prompt_cache_options", payload)
        self.assertEqual(keys[0], keys[1])
        for limit in (True, 0, 32769):
            with self.assertRaises(ValueError):
                self.client.respond("", "", self.cancel, lambda _: None, max_output_tokens=limit)

    def test_partial_text_does_not_make_truncated_or_failed_stream_successful(self):
        self.save_account()
        for terminal in (None, {"type": "response.incomplete"},
                         {"type": "response.failed", "response": {"error": {"code": "subscription_sharing_usage_limit_exceeded"}}},
                         {"type": "error", "code": "model_not_found"}):
            events = [{"type": "response.output_text.delta", "delta": "Partial"}]
            if terminal:
                events.append(terminal)
            response = stream(*events)
            deltas = []
            with self.subTest(terminal=terminal), patch.object(self.client._opener, "open", return_value=response):
                with self.assertRaises(ChatGPTError):
                    self.client.respond("", "", self.cancel, deltas.append)
                self.assertEqual(deltas, ["Partial"])
                self.assertTrue(response.closed)

    def test_response_cancellation_closes_stream(self):
        self.save_account()
        response = stream({"type": "response.output_text.delta", "delta": "Partial"},
                          {"type": "response.completed"})
        with patch.object(self.client._opener, "open", return_value=response), self.assertRaises(ChatGPTCancelled):
            self.client.respond("", "", self.cancel, lambda _: self.cancel.set())
        self.assertTrue(response.closed)

    def test_http_failures_are_helpful_and_never_expose_server_secrets(self):
        self.save_account()
        for status, code, phrase in ((401, "invalid_token", "session expired"),
                                     (403, "denied", "plan permission"),
                                     (404, "model_not_found", "gpt-6-luna"),
                                     (429, "rate_limit_exceeded", "rate limited"),
                                     (500, "server_error", "could not complete")):
            error = HTTPError(RESOURCE + "/responses", status, "secret-server-message", {},
                              io.BytesIO(json.dumps({"error": {"code": code, "message": "secret-token-value"}}).encode()))
            with self.subTest(status=status), patch.object(self.client._opener, "open", side_effect=error):
                with self.assertRaisesRegex(ChatGPTError, phrase) as caught:
                    self.client.respond("", "", self.cancel, lambda _: None)
                self.assertNotIn("secret", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
