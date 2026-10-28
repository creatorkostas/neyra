import queue
import sys
import types
import unittest
from unittest.mock import patch

import numpy as np

from neyra.stt import SAMPLE_RATE, SILENCE, WINDOW_SAMPLES, Transcriber, window_end


def speech(seconds, pauses=(), amplitude=.1, seed=0):
    """Room-noise-like speech with float silence where pauses are, in seconds."""
    rng = np.random.default_rng(seed)
    samples = rng.normal(0, amplitude, round(seconds * SAMPLE_RATE)).astype(np.float32)
    for at, length in pauses:
        samples[round(at * SAMPLE_RATE):round((at + length) * SAMPLE_RATE)] = 0
    return samples


def chunks(samples, size=4000):
    audio = queue.Queue()
    for at in range(0, len(samples), size):
        audio.put(samples[at:at + size])
    audio.put(None)
    return audio


class WindowEndTests(unittest.TestCase):
    def test_waits_for_the_minimum_window(self):
        self.assertIsNone(window_end(np.zeros(16000, np.float32)))

    def test_caps_the_window_on_the_encoder_fast_path(self):
        self.assertEqual(window_end(speech(12)), WINDOW_SAMPLES)

    def test_ends_on_a_pause_inside_the_window(self):
        cut = window_end(speech(8, pauses=[(3.0, .12)]))
        self.assertGreaterEqual(cut, round(3.0 * SAMPLE_RATE))
        self.assertLessEqual(cut, round(3.2 * SAMPLE_RATE))

    def test_a_brief_dip_inside_a_word_is_not_a_cut(self):
        cut = window_end(speech(6, pauses=[(3.0, .02)]))
        self.assertEqual(cut, WINDOW_SAMPLES)

    def test_never_returns_more_than_the_cap(self):
        for seconds in (2.5, 3.0, 5.0, 5.12, 5.2, 9.0):
            for pause in ((), ((3.0, .1),)):
                cut = window_end(speech(seconds, pauses=pause, seed=round(seconds * 10)))
                if cut is not None:
                    self.assertLessEqual(cut, WINDOW_SAMPLES)


class WhistleWindowTests(unittest.TestCase):
    def run_whistle(self, worker, chunks, keywords=()):
        texts, windows, order = [], [], []

        class Engine:
            def transcribe(self, window, language=None, keywords=None):
                windows.append(len(window))
                order.append((language, tuple(keywords or ())))
                texts.append(f"w{len(windows)}")
                return {"text": texts[-1]}

        module = types.SimpleNamespace(Whistle=lambda: Engine())
        with patch.dict(sys.modules, {"needle": module}):
            return worker._run_whistle(chunks, keywords), windows, order

    def test_joins_the_text_of_every_window(self):
        worker = Transcriber()
        self.addCleanup(worker.close)
        result, windows, order = self.run_whistle(worker, chunks(speech(9, pauses=[(2.9, .12), (5.9, .12), (8.4, .12)])))
        self.assertEqual(result, " ".join(f"w{n}" for n in range(1, len(windows) + 1)))
        self.assertGreater(len(windows), 2)
        self.assertTrue(all(size <= WINDOW_SAMPLES for size in windows))
        self.assertEqual(order[0], ("en", ()))

    def test_every_valid_chunk_is_sent_as_soon_as_it_closes_a_window(self):
        worker = Transcriber()
        self.addCleanup(worker.close)
        partials = []
        worker.partial.connect(partials.append)
        result, windows, _ = self.run_whistle(worker, chunks(speech(6, pauses=[(3.0, .12)])))
        self.assertTrue(result)
        self.assertEqual(len(partials), len(windows))
        self.assertEqual(partials[-1], result)

    def test_room_noise_is_not_sent_to_the_model(self):
        worker = Transcriber()
        self.addCleanup(worker.close)
        result, windows, _ = self.run_whistle(worker, chunks(np.zeros(4 * SAMPLE_RATE, np.float32)))
        self.assertEqual(result, "")
        self.assertEqual(windows, [])
        self.assertAlmostEqual(float(np.mean(np.zeros(1600, np.float32) ** 2)), 0.0)
        self.assertGreater(SILENCE, 1e-6)

    def test_empty_recording_finishes_with_no_text(self):
        worker = Transcriber()
        self.addCleanup(worker.close)
        result, windows, _ = self.run_whistle(worker, chunks(np.zeros(0, np.float32)))
        self.assertEqual(result, "")
        self.assertEqual(windows, [])

    def test_a_closing_stream_flushes_the_last_partial_window(self):
        worker = Transcriber()
        self.addCleanup(worker.close)
        result, windows, _ = self.run_whistle(worker, chunks(speech(1.5)))
        self.assertEqual(result, "w1")
        self.assertEqual(windows, [round(1.5 * SAMPLE_RATE)])

    def test_keywords_reach_every_window(self):
        worker = Transcriber()
        self.addCleanup(worker.close)
        _, _, order = self.run_whistle(worker, chunks(speech(6, pauses=[(3.0, .12)])), keywords=["Neyra", "Voz"])
        self.assertTrue(order)
        self.assertTrue(all(item == ("en", ("Neyra", "Voz")) for item in order))


if __name__ == "__main__":
    unittest.main()
