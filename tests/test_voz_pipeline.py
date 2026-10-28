import tempfile
import threading
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import numpy as np
import onnx
from onnx import TensorProto, helper

from neyra.voz import ENCODER_BATCH, VozEngine, relaxed_decoder

C = dict(hop_length=160, n_rows=1503, n_samples=240000, n_fft=512, n_padded_samples=240480,
         valid_frames=1500, enc_frames=188, preemph=.97, decode_width=2, durations=[0, 1, 2, 3, 4],
         blank_idx=4, vocab_size=4, joint_hidden=2, pred_hidden=2, pred_layers=1, decode_lanes=16)


def lane_model(path, batch=16):
    """Tiny decoder-shaped graph whose lane batch is either fixed or symbolic."""
    lane = batch
    node = helper.make_node('Identity', ['x'], ['y'])
    inputs = [helper.make_tensor_value_info('x', TensorProto.FLOAT, [lane, 4])]
    outputs = [helper.make_tensor_value_info('y', TensorProto.FLOAT, [lane, 4])]
    model = helper.make_model(helper.make_graph([node], 'lanes', inputs, outputs), opset_imports=[helper.make_opsetid('', 17)])
    model.ir_version = 10  # readable by every supported onnxruntime build
    onnx.save(model, str(path))


def fake_engine(dynamic=True, lanes=16):
    engine = object.__new__(VozEngine)
    engine.config = dict(C)
    engine.embedding = np.zeros((C['vocab_size'] + 1, C['pred_hidden']), np.float32)
    engine.closed = threading.Event()
    engine.provider = 'WebGpuExecutionProvider'
    engine.dynamic_lanes = dynamic
    engine.lanes = lanes
    engine._lock = threading.Lock()
    engine.vocabulary = ['▁a', '▁b', '▁c', '▁d', '<blank>']
    return engine


class DecoderBatchTests(unittest.TestCase):
    def test_relaxed_decoder_makes_the_lane_batch_dynamic(self):
        with tempfile.TemporaryDirectory() as directory:
            root, cache = Path(directory) / 'models', Path(directory) / 'cache'
            root.mkdir()
            lane_model(root / 'decoder.onnx')
            relaxed = relaxed_decoder(root, cache)
            self.assertIsNotNone(relaxed)
            self.assertEqual(relaxed.parent, cache)
            import onnxruntime
            session = onnxruntime.InferenceSession(str(relaxed), providers=['CPUExecutionProvider'])
            self.assertNotIsInstance(session.get_inputs()[0].shape[0], int)
            for lanes in (1, 3, 16):
                values = np.arange(lanes * 4, dtype=np.float32).reshape(lanes, 4)
                np.testing.assert_array_equal(session.run(None, {'x': values})[0], values)

    def test_relaxed_decoder_is_cached_and_stale_builds_are_dropped(self):
        with tempfile.TemporaryDirectory() as directory:
            root, cache = Path(directory) / 'models', Path(directory) / 'cache'
            root.mkdir()
            lane_model(root / 'decoder.onnx')
            first = relaxed_decoder(root, cache)
            stale = cache / 'decoder-dynamic-16-1-1.onnx'
            stale.write_bytes(b'')
            second = relaxed_decoder(root, cache)
            self.assertEqual(first, second)
            self.assertFalse(stale.exists())

    def test_dynamic_model_is_left_alone(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lane_model(root / 'decoder.onnx', batch='batch')
            self.assertIsNone(relaxed_decoder(root, root / 'cache'))

    def test_decode_batches_only_the_active_lanes(self):
        engine = fake_engine(dynamic=True)
        seen = []

        def run(name, values):
            seen.append(values[0].shape[0])
            lanes = values[0].shape[0]
            logits = np.zeros((lanes, C['vocab_size'] + 1 + len(C['durations']), 1, C['decode_width']), np.float32)
            logits[:, C['blank_idx'], 0, :] = 10.0  # blanks only: one decoder run finishes a one-frame lane
            zeros = np.zeros_like(values[1])
            return [logits, zeros, zeros]

        engine.run = run
        encoded = [(np.zeros((C['joint_hidden'], 1), np.float32), 1)] * 2
        self.assertEqual(engine.decode(encoded), [[], []])
        self.assertEqual(seen, [2])

    def test_fixed_model_keeps_its_declared_batch(self):
        engine = fake_engine(dynamic=False, lanes=16)
        seen = []

        def run(name, values):
            seen.append(values[0].shape[0])
            lanes = values[0].shape[0]
            logits = np.zeros((lanes, C['vocab_size'] + 1 + len(C['durations']), 1, C['decode_width']), np.float32)
            logits[:, C['blank_idx'], 0, :] = 10.0
            zeros = np.zeros_like(values[1])
            return [logits, zeros, zeros]

        engine.run = run
        engine.decode([(np.zeros((C['joint_hidden'], 1), np.float32), 1)])
        self.assertEqual(seen, [16])


class EncoderBatchTests(unittest.TestCase):
    def test_encode_many_runs_one_batched_mel_and_encoder(self):
        engine = fake_engine(dynamic=True)
        batches = []

        def run(name, values):
            if name == 'mel':
                lanes = values[0].shape[0]
                batches.append(('mel', lanes))
                return [np.zeros((lanes, 128, 1, C['valid_frames']), np.float32)]
            lanes = values[0].shape[0]
            batches.append(('encoder', lanes))
            return [np.zeros((lanes, 640, 1, 1), np.float32)]

        engine.run = run
        encoded = engine.encode_many([np.zeros(16000, np.float32)] * 3)
        self.assertEqual(len(encoded), 3)
        self.assertEqual(batches, [('mel', 3), ('encoder', 3)])
        self.assertEqual({item[0].shape for item in encoded}, {(640, 1)})

    def test_empty_batch_skips_the_sessions(self):
        engine = fake_engine()
        engine.run = lambda *args: self.fail('sessions must not run')
        self.assertEqual(engine.encode_many([]), [])

    def test_encode_windows_chunks_by_the_encoder_batch(self):
        engine = fake_engine()
        calls = []
        engine.encode_many = lambda audios: (calls.append(len(audios)), [([], 1) for _ in audios])[1]
        windows = [(index, np.zeros(1600, np.float32)) for index in range(ENCODER_BATCH + 1)]
        encoded = engine._encode_windows(windows)
        self.assertEqual(calls, [ENCODER_BATCH, 1])
        self.assertEqual(len(encoded), ENCODER_BATCH + 1)


class TranscriptionLoopTests(unittest.TestCase):
    def wav(self, directory, windows):
        path = Path(directory) / 'audio.wav'
        with wave.open(str(path), 'wb') as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16000)
            audio.writeframes(np.zeros(windows * C['n_samples'], '<i2').tobytes())
        return path

    def test_encoder_runs_ahead_of_the_decoder_on_gpu(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = fake_engine(dynamic=True, lanes=2)
            engine.lanes = 2
            encoded_started = threading.Event()
            overlap = []

            def encode(windows):
                if windows and windows[0][0] > 0:
                    encoded_started.set()
                return [([], 1) for _ in windows]

            def decode(encoded):
                if len(encoded) == 2:
                    overlap.append(encoded_started.wait(5))
                return [[] for _ in encoded]

            engine._encode_windows = encode
            engine.decode = decode
            path = self.wav(directory, 3)  # two batches: window 2 encodes while batch 1 decodes
            result = engine.transcribe(path)
            self.assertEqual(result['text'], '')
            self.assertTrue(overlap)
            self.assertTrue(all(overlap))

    def test_cpu_only_runs_sessions_in_order(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = fake_engine(dynamic=True, lanes=2)
            engine.provider = None
            order = []
            engine._encode_windows = lambda windows: (order.append(('encode', len(windows))), [([], 1) for _ in windows])[1]

            def decode(encoded):
                order.append(('decode', len(encoded)))
                return [[] for _ in encoded]

            engine.decode = decode
            engine.transcribe(self.wav(directory, 3))
            self.assertEqual([name for name, _ in order], ['encode', 'decode', 'encode', 'decode'])
            self.assertEqual(order[0][1], order[1][1])

    def test_windows_are_read_in_decoder_batches(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = fake_engine(dynamic=True, lanes=2)
            path = self.wav(directory, 3)
            with wave.open(str(path), 'rb') as audio:
                windows, start = engine._read_windows(audio, 0, audio.getnframes())
                remaining, after = engine._read_windows(audio, start, audio.getnframes())
            self.assertEqual(len(windows), 2)
            self.assertLessEqual(len(remaining), 2)
            self.assertGreater(start, 0)
            self.assertGreaterEqual(after, start)

    def test_closed_engine_cancels_pending_batches(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = fake_engine(dynamic=True, lanes=2)
            engine._encode_windows = lambda windows: [([], 1) for _ in windows]

            def decode(encoded):
                engine.closed.set()
                return [[] for _ in encoded]

            engine.decode = decode
            with self.assertRaises(RuntimeError):
                engine.transcribe(self.wav(directory, 3))


if __name__ == '__main__':
    unittest.main()
