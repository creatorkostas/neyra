"""Piper speech checks use fake voice files and mocked audio only."""
import hashlib
import io
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from neyra import speech


class PiperSpeechTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="neyra-speech-")
        self.addCleanup(folder.cleanup)
        self.cache = Path(folder.name)
        self.play = patch.object(speech, "_play").start()
        self.addCleanup(patch.stopall)

    def helper(self, voice=None):
        errors, statuses = [], []
        ready = threading.Event()

        def status(value):
            statuses.append(value)
            if value in ("Ready", "Speech unavailable"):
                ready.set()

        helper = speech.PiperSpeech(self.cache, errors.append, status)
        if voice is not None:
            helper._load_voice = Mock(return_value=voice)

        def finish():
            helper.close()
            if helper._thread:
                helper._thread.join(2)
                self.assertFalse(helper._thread.is_alive())

        self.addCleanup(finish)
        return helper, errors, statuses, ready

    def test_constructor_is_lazy_and_close_without_speech_is_safe(self):
        helper, _, _, _ = self.helper()
        self.assertIsNone(helper._thread)
        self.assertIsNone(helper._voice)
        helper.stop()
        helper.close()
        helper.speak("ignored")
        self.assertIsNone(helper._thread)

    def test_speech_streams_bounded_sentences_and_callbacks_use_worker(self):
        voice = Mock()
        voice.synthesize.side_effect = lambda text: iter([Mock()])
        helper, errors, statuses, ready = self.helper(voice)
        threads = []
        original = helper._on_status
        helper._on_status = lambda value: (threads.append(threading.current_thread()), original(value))
        helper.speak("Hello **there**. " + "word " * 250)
        self.assertTrue(ready.wait(2))
        self.assertFalse(errors)
        self.assertFalse(helper.is_busy)
        self.assertIn("Speaking", statuses)
        self.assertTrue(all(thread is helper._thread for thread in threads))
        self.assertGreater(voice.synthesize.call_count, 2)
        self.assertTrue(all(len(call.args[0]) <= 400 for call in voice.synthesize.call_args_list))
        self.assertEqual(self.play.call_count, voice.synthesize.call_count)

    def test_stop_during_native_synthesis_prevents_stale_playback(self):
        entered, release = threading.Event(), threading.Event()
        voice = Mock()

        def synthesize(text):
            entered.set()
            release.wait(2)
            yield Mock()

        voice.synthesize.side_effect = synthesize
        helper, errors, _, _ = self.helper(voice)
        try:
            helper.speak("Old text.")
            self.assertTrue(entered.wait(1))
            self.assertTrue(helper.is_busy)
            helper.stop()
            self.assertFalse(helper.is_busy)
            helper.close()
        finally:
            release.set()
        helper._thread.join(2)
        self.play.assert_not_called()
        self.assertFalse(errors)

    def test_new_utterance_replaces_pending_and_inflight_text(self):
        entered, release = threading.Event(), threading.Event()
        voice = Mock()

        def synthesize(text):
            if text == "Old text.":
                entered.set()
                release.wait(2)
            yield text

        voice.synthesize.side_effect = synthesize
        helper, errors, _, ready = self.helper(voice)
        try:
            helper.speak("Old text.")
            self.assertTrue(entered.wait(1))
            helper.speak("Superseded text.")
            helper.speak("Latest text.")
        finally:
            release.set()
        self.assertTrue(ready.wait(2))
        self.assertEqual([call.args[0] for call in self.play.call_args_list], ["Latest text."])
        self.assertEqual([call.args[0] for call in voice.synthesize.call_args_list], ["Old text.", "Latest text."])
        self.assertFalse(errors)

    def test_stop_sets_playback_cancellation_without_waiting(self):
        entered, release = threading.Event(), threading.Event()
        voice = Mock()
        voice.synthesize.side_effect = lambda text: iter([Mock()])
        cancelled = []

        def play(chunk, cancel):
            entered.set()
            release.wait(2)
            cancelled.append(cancel.is_set())
            speech._check_cancel(cancel)

        self.play.side_effect = play
        helper, errors, _, _ = self.helper(voice)
        try:
            helper.speak("Hello.")
            self.assertTrue(entered.wait(1))
            helper.stop()
            helper.close()
        finally:
            release.set()
        helper._thread.join(2)
        self.assertEqual(cancelled, [True])
        self.assertFalse(errors)

    def test_lazy_piper_load_uses_external_cache_once_and_cpu(self):
        voice = Mock()
        voice.synthesize.side_effect = lambda text: iter([])
        fake_piper = Mock()
        fake_piper.PiperVoice.load.return_value = voice
        helper, errors, _, ready = self.helper()
        with patch.dict(sys.modules, {"piper": fake_piper}), patch.object(speech, "_verified", return_value=True), patch.object(
            speech, "_download"
        ) as download:
            helper.speak("First.")
            self.assertTrue(ready.wait(2))
            ready.clear()
            helper.speak("Second.")
            self.assertTrue(ready.wait(2))
            fake_piper.PiperVoice.load.assert_called_once_with(
                self.cache / f"{speech.VOICE}.onnx", use_cuda=False, download_dir=self.cache)
            self.assertEqual(download.call_count, 2)
        self.assertFalse(errors)

    def test_failure_is_reported_without_a_qt_or_system_tts_fallback(self):
        helper, errors, statuses, ready = self.helper()
        helper._load_voice = Mock(side_effect=ImportError("piper missing"))
        helper.speak("Hello.")
        self.assertTrue(ready.wait(2))
        self.assertIn("piper missing", errors[0])
        self.assertEqual(statuses[-1], "Speech unavailable")
        self.play.assert_not_called()

    def test_prose_sanitization_omits_code_syntax_and_retains_natural_words(self):
        text = '# Title\n**Hello** [friend](https://example.com).\n```python\nprint({"raw": [1]})\n```\n- Use `voice_name()` today.'
        cleaned = speech.spoken_text(text)
        self.assertIn("Title Hello friend.", cleaned)
        self.assertIn("Code example shown in the response.", cleaned)
        self.assertIn("Use voice name today.", cleaned)
        self.assertNotIn("print", cleaned)
        self.assertFalse(any(char in cleaned for char in "`*_{}[]()#"))
        self.assertNotIn("example.com", cleaned)

    def test_stream_keeps_waiting_for_late_sentences_and_drains_in_order(self):
        voice = Mock()
        voice.synthesize.side_effect = lambda text: iter([text])
        first_played = threading.Event()
        self.play.side_effect = lambda chunk, cancel: first_played.set()
        helper, errors, statuses, ready = self.helper(voice)
        stream = helper.begin_stream()
        self.assertTrue(helper.is_busy)
        self.assertTrue(helper.append_stream(stream, "First sentence."))
        self.assertTrue(first_played.wait(2))
        self.assertTrue(helper.is_busy)
        self.assertFalse(ready.is_set())
        self.assertTrue(helper.append_stream(stream, "The late second sentence."))
        self.assertTrue(helper.finish_stream(stream))
        self.assertFalse(helper.append_stream(stream, "Too late."))
        self.assertTrue(ready.wait(2))
        self.assertFalse(helper.is_busy)
        self.assertEqual([call.args[0] for call in self.play.call_args_list],
                         ["First sentence.", "The late second sentence."])
        self.assertEqual(statuses.count("Ready"), 1)
        self.assertFalse(errors)

    def test_finish_does_not_truncate_queued_speech(self):
        entered, release = threading.Event(), threading.Event()
        voice = Mock()

        def synthesize(text):
            if text == "First.":
                entered.set()
                release.wait(2)
            yield text

        voice.synthesize.side_effect = synthesize
        helper, errors, _, ready = self.helper(voice)
        stream = helper.begin_stream()
        try:
            helper.append_stream(stream, "First.")
            self.assertTrue(entered.wait(1))
            helper.append_stream(stream, "Second.")
            helper.append_stream(stream, "Third.")
            helper.finish_stream(stream)
            self.assertTrue(helper.is_busy)
            self.assertFalse(ready.is_set())
        finally:
            release.set()
        self.assertTrue(ready.wait(2))
        self.assertEqual([call.args[0] for call in self.play.call_args_list], ["First.", "Second.", "Third."])
        self.assertFalse(errors)

    def test_stop_and_new_speech_invalidate_stream_tokens_and_queued_chunks(self):
        voice = Mock()
        voice.synthesize.side_effect = lambda text: iter([text])
        helper, errors, _, ready = self.helper(voice)
        with helper._condition:
            stream = helper.begin_stream()
            helper.append_stream(stream, "Discarded.")
            helper.stop()
            self.assertFalse(helper.is_busy)
            self.assertFalse(helper.append_stream(stream, "Stale."))
            self.assertFalse(helper.finish_stream(stream))
            next_stream = helper.begin_stream()
            helper.append_stream(next_stream, "Also discarded.")
            helper.speak("Latest speech.")
            self.assertFalse(helper.append_stream(next_stream, "Stale again."))
        self.assertTrue(ready.wait(2))
        self.assertEqual([call.args[0] for call in self.play.call_args_list], ["Latest speech."])
        self.assertFalse(errors)

    def test_stream_queue_and_total_text_are_bounded_without_truncation(self):
        voice = Mock()
        voice.synthesize.side_effect = lambda text: iter([text])
        helper, errors, _, ready = self.helper(voice)
        with patch.object(speech, "MAX_STREAM_PENDING", 2), patch.object(speech, "MAX_STREAM_CHARS", 12):
            with helper._condition:
                stream = helper.begin_stream()
                self.assertTrue(helper.append_stream(stream, "First."))
                self.assertTrue(helper.append_stream(stream, "Next."))
                self.assertFalse(helper.append_stream(stream, "X"))
                helper.finish_stream(stream)
            self.assertTrue(ready.wait(2))
            ready.clear()
            with helper._condition:
                stream = helper.begin_stream()
                self.assertFalse(helper.append_stream(stream, "x" * 13))
                self.assertTrue(helper.append_stream(stream, "x" * 12))
                self.assertFalse(helper.append_stream(stream, "x"))
                helper.finish_stream(stream)
            self.assertTrue(ready.wait(2))
        self.assertEqual([call.args[0] for call in self.play.call_args_list], ["First.", "Next.", "x" * 12])
        self.assertFalse(errors)

    def test_configure_selects_voice_and_inverse_speed_for_future_speech(self):
        voice = Mock()
        voice.synthesize.side_effect = lambda text, **kwargs: iter([text])
        fake_piper = Mock()
        helper, errors, _, ready = self.helper(voice)
        with helper._condition:
            stream = helper.begin_stream()
            helper.append_stream(stream, "Old voice.")
            helper.configure("en_GB-alan-medium", 1.25)
            self.assertFalse(helper.is_busy)
            self.assertFalse(helper.append_stream(stream, "Stale."))
        with patch.dict(sys.modules, {"piper": fake_piper}):
            helper.speak("New voice.")
            self.assertTrue(ready.wait(2))
        fake_piper.SynthesisConfig.assert_called_once_with(length_scale=0.8)
        self.assertEqual(helper._load_voice.call_args.args[1], "en_GB-alan-medium")
        voice.synthesize.assert_called_once_with("New voice.", syn_config=fake_piper.SynthesisConfig.return_value)
        self.assertFalse(errors)

    def test_configure_rejects_unsupported_voice_and_unsafe_speed(self):
        helper, _, _, _ = self.helper()
        for voice in ("unknown", "../voice", None, 1):
            with self.subTest(voice=voice), self.assertRaises(ValueError):
                helper.configure(voice, 1)
        for speed in (0.74, 1.51, True, "1", None, float("inf"), float("nan")):
            with self.subTest(speed=speed), self.assertRaises(ValueError):
                helper.configure(speech.VOICE, speed)
        self.assertEqual(helper.voice_id, speech.VOICE)
        self.assertEqual(helper.speed, 1.0)

    def test_empty_stream_finishes_and_close_rejects_streams(self):
        helper, _, _, ready = self.helper()
        stream = helper.begin_stream()
        self.assertTrue(helper.is_busy)
        self.assertTrue(helper.finish_stream(stream))
        self.assertTrue(ready.wait(2))
        self.assertFalse(helper.is_busy)
        helper.close()
        self.assertIsNone(helper.begin_stream())
        self.assertFalse(helper.append_stream(stream, "Closed."))

    def test_catalog_contains_pinned_english_and_greek_voice_pairs(self):
        self.assertEqual(len(speech.VOICE_CATALOG), 3)
        for voice_id, metadata in speech.VOICE_CATALOG.items():
            self.assertTrue(metadata["label"])
            self.assertTrue(metadata["sample"])
            for suffix in (".onnx", ".onnx.json"):
                size, digest = speech._FILES[voice_id + suffix]
                self.assertGreater(size, 0)
                self.assertRegex(digest, r"^[0-9a-f]{64}$")
            self.assertIn(speech._REVISION, speech._VOICE_URLS[voice_id])
        self.assertEqual(speech.VOICE_CATALOG["el_GR-rapunzelina-low"]["language"], "el-GR")


class VoiceDownloadTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="neyra-voice-")
        self.addCleanup(folder.cleanup)
        self.cache = Path(folder.name)
        self.data = b"fake voice data"
        patcher = patch.object(speech, "_FILES", {"voice.onnx": (len(self.data), hashlib.sha256(self.data).hexdigest())})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.cancel = threading.Event()

    def response(self, raw):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.geturl.return_value = "https://cas-bridge.xethub.hf.co/voice"
        response.headers = {}
        response.read.side_effect = io.BytesIO(raw).read
        return response

    def test_verified_download_is_atomic_and_cached_without_redownload(self):
        with patch.object(speech, "build_opener") as opener:
            opener.return_value.open.return_value = self.response(self.data)
            destination = speech._download(self.cache, "voice.onnx", self.cancel)
            self.assertEqual(destination.read_bytes(), self.data)
            self.assertEqual(list(self.cache.glob("*.tmp")), [])
            speech._download(self.cache, "voice.onnx", self.cancel)
            opener.assert_called_once()
            self.assertEqual(opener.return_value.open.call_args.kwargs["timeout"], 10)

    def test_bad_hash_and_oversize_never_replace_existing_cache(self):
        destination = self.cache / "voice.onnx"
        destination.write_bytes(b"old invalid voice")
        for data in (b"x" * len(self.data), self.data + b"extra"):
            with self.subTest(data=data), patch.object(speech, "build_opener") as opener:
                opener.return_value.open.return_value = self.response(data)
                with self.assertRaises(OSError):
                    speech._download(self.cache, "voice.onnx", self.cancel)
                self.assertEqual(destination.read_bytes(), b"old invalid voice")
                self.assertEqual(list(self.cache.glob("*.tmp")), [])

    def test_cancelled_partial_download_is_removed(self):
        response = self.response(self.data)

        def read(size):
            self.cancel.set()
            return self.data[:3]

        response.read.side_effect = read
        with patch.object(speech, "build_opener") as opener:
            opener.return_value.open.return_value = response
            with self.assertRaises(speech._Cancelled):
                speech._download(self.cache, "voice.onnx", self.cancel)
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_untrusted_or_insecure_redirect_is_rejected(self):
        for url in ("http://huggingface.co/file", "https://example.com/file", "https://huggingface.co.evil.test/file", "https://user@huggingface.co/file"):
            with self.subTest(url=url), self.assertRaises(OSError):
                speech._safe_url(url)
        speech._safe_url("https://cdn-lfs-us-1.hf.co/file")


class PlaybackTests(unittest.TestCase):
    def chunk(self):
        return Mock(sample_width=2, sample_channels=1, sample_rate=22050, audio_int16_bytes=b"\x01\x00" * 4)

    def test_playback_callback_writes_pcm_and_closes_stream(self):
        sd = Mock()
        sd.CallbackStop = type("CallbackStop", (Exception,), {})
        sd.CallbackAbort = type("CallbackAbort", (Exception,), {})
        output = bytearray(16)

        def start():
            callback = sd.RawOutputStream.call_args.kwargs["callback"]
            with self.assertRaises(sd.CallbackStop):
                callback(output, 8, None, None)
            sd.RawOutputStream.call_args.kwargs["finished_callback"]()

        sd.RawOutputStream.return_value.start.side_effect = start
        with patch.dict(sys.modules, {"sounddevice": sd}):
            speech._play(self.chunk(), threading.Event())
        self.assertEqual(output[:8], b"\x01\x00" * 4)
        self.assertEqual(output[8:], bytes(8))
        sd.RawOutputStream.return_value.close.assert_called_once()

    def test_cancelled_callback_aborts_and_cleanup_closes_even_if_abort_fails(self):
        cancel = threading.Event()
        sd = Mock()
        sd.CallbackAbort = type("CallbackAbort", (Exception,), {})

        def start():
            cancel.set()
            with self.assertRaises(sd.CallbackAbort):
                sd.RawOutputStream.call_args.kwargs["callback"](bytearray(16), 8, None, None)

        sd.RawOutputStream.return_value.start.side_effect = start
        sd.RawOutputStream.return_value.abort.side_effect = OSError("disconnected")
        with patch.dict(sys.modules, {"sounddevice": sd}), self.assertRaises(OSError):
            speech._play(self.chunk(), cancel)
        sd.RawOutputStream.return_value.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
