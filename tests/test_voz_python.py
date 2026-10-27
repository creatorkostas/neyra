import unittest
import numpy as np
from neyra.voz import frame_audio, boundary, timed_words, splice

C = dict(hop_length=160, n_rows=1503, n_samples=240000, n_fft=512, n_padded_samples=240480,
         valid_frames=1500, enc_frames=188, preemph=.97)


class VozPythonTests(unittest.TestCase):
    def test_centered_framing_and_short_clip_masks(self):
        samples = np.arange(16000, dtype=np.float32)
        rows, mask, bias, valid = frame_audio(samples, C)
        flat = rows[0, :, 0, :].T.flatten()
        np.testing.assert_array_equal(flat[:256], 0)
        np.testing.assert_array_equal(flat[256:16256], samples)
        self.assertEqual(mask.sum(), 101)
        self.assertEqual(valid, 13)
        self.assertEqual((bias == 0).sum(), 13)

    def test_full_window_geometric_tail(self):
        samples = np.ones(240000, np.float32)
        rows, _, _, _ = frame_audio(samples, C)
        flat = rows[0, :, 0, :].T.flatten()
        self.assertAlmostEqual(float(flat[240256]), .97, places=5)

    def test_words_and_overlap_do_not_duplicate(self):
        words = timed_words([(0, 0, 1), (1, 1, 2), (2, 3, 5)], ['▁hello', '!', '▁world'], .08, 2)
        self.assertEqual([w['text'] for w in words], ['hello!', 'world'])
        self.assertEqual(words[0]['start'], 2)
        merged = splice(words, [dict(w) for w in words] + [{'text': 'again', 'start': 3, 'end': 3.1}], 2)
        self.assertEqual([w['text'] for w in merged], ['hello!', 'world', 'again'])

    def test_quiet_boundary_is_inside_window(self):
        samples = np.ones(240000, np.float32)
        samples[220000:221000] = 0
        self.assertTrue(220000 <= boundary(samples, 16000) <= 221000)
