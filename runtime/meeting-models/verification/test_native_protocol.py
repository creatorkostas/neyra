"""Protocol checks; NEYRA_TEST_MODELS=1 also runs synthetic model inference."""
import json
import math
import os
from pathlib import Path
import subprocess
import struct
import tempfile
import unittest
import wave

ROOT = Path(__file__).resolve().parents[3]
HELPER = Path(os.environ.get("NEYRA_MEETING_MODELS", str(ROOT / "assets/meeting-models/neyra-meeting-models.exe")))


@unittest.skipUnless(HELPER.is_file(), "Build the native helper first")
class NativeProtocolTests(unittest.TestCase):
    def request(self, payload):
        result = subprocess.run(
            [str(HELPER)], input=json.dumps(payload) + "\n", text=True,
            capture_output=True, timeout=120 if os.environ.get("NEYRA_TEST_MODELS") == "1" else 15,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        events = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertTrue(events, result.stderr)
        self.assertTrue(all(event.get("event") in {"result", "progress", "error"} for event in events))
        return result.returncode, events

    def test_capabilities_and_id(self):
        code, events = self.request({"id": "probe", "operation": "check"})
        self.assertEqual(code, 0)
        self.assertEqual(events[-1]["capabilities"], ["align", "who", "clear", "gist"])
        self.assertEqual(events[-1]["id"], "probe")

    def test_rejects_invalid_words_before_reading_audio(self):
        code, events = self.request({"operation": "analyze", "path": "missing.wav",
                                     "words": [{"text": "x", "start": 1, "end": 0}]})
        self.assertEqual(code, 1)
        self.assertEqual(events[-1]["event"], "error")
        self.assertIn("timestamps", events[-1]["message"])

    def test_rejects_unknown_operation(self):
        code, events = self.request({"operation": "unknown"})
        self.assertEqual(code, 1)
        self.assertEqual(events[-1]["event"], "error")

    def test_rejects_stereo_without_models(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stereo.wav"
            with wave.open(str(path), "wb") as audio:
                audio.setnchannels(2)
                audio.setsampwidth(2)
                audio.setframerate(48000)
                audio.writeframes(b"\0\0\0\0" * 4800)
            code, events = self.request({"operation": "analyze", "path": str(path),
                                         "words": [{"text": "x", "start": 0, "end": 0.1}]})
            self.assertEqual(code, 1)
            self.assertIn("mono", events[-1]["message"])

    @unittest.skipUnless(os.environ.get("NEYRA_TEST_MODELS") == "1", "Enable model inference explicitly")
    def test_analyzes_mono_16k_and_48k(self):
        with tempfile.TemporaryDirectory() as directory:
            for rate in (16000, 48000):
                with self.subTest(sample_rate=rate):
                    path = Path(directory) / f"{rate}.wav"
                    samples = [int(1000 * math.sin(2 * math.pi * 220 * i / rate)) for i in range(rate * 3)]
                    with wave.open(str(path), "wb") as audio:
                        audio.setnchannels(1)
                        audio.setsampwidth(2)
                        audio.setframerate(rate)
                        audio.writeframes(struct.pack(f"<{len(samples)}h", *samples))
                    code, events = self.request({"operation": "analyze", "path": str(path),
                        "speakers": True, "words": [{"text": "hello", "start": 1.2, "end": 1.6}]})
                    self.assertEqual(code, 0, events)
                    word = events[-1]["words"][0]
                    self.assertEqual(word["text"], "hello")
                    self.assertTrue(math.isfinite(word["start"]) and math.isfinite(word["end"]))
                    self.assertLessEqual(word["end"], 3.0)
                    self.assertIsInstance(word["refined"], bool)


if __name__ == "__main__":
    unittest.main()
