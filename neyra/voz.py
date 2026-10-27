"""Python/NumPy host for Voz's native ONNX export (no JavaScript runtime).

Pipeline adaptation from Desert-Ant-Labs/desert-ant-core at
541a9ce4a148e9308a99f1edbfd927906394b686, Sources/Voz.
Copyright 2026 Desert Ant Labs B.V. and Neyra contributors.
SPDX-License-Identifier: LicenseRef-DAL-Source-Available-1.0
See packaging/licenses/DesertAnt-LICENSE.md. Model weights are not bundled.
"""
import json
import os
import shutil
import sys
from pathlib import Path
import threading
import wave
import numpy as np

REVISION = '12802bf4e2b5e97e1289b723bc6283b6f1a1ace5'  # v0.5.0, immutable
FILES = ('meta.json', 'vocab.json', 'embedding.f16', 'mel.onnx', 'encoder.onnx', 'encoder.weights', 'decoder.onnx')

CPU_PROVIDER = 'CPUExecutionProvider'
GPU_SESSIONS = frozenset({'mel', 'encoder'})
PROVIDER_OPTIONS = {
    'CoreMLExecutionProvider': {'MLComputeUnits': 'ALL'},
    'DmlExecutionProvider': {'device_id': 0},
    'OpenVINOExecutionProvider': {'device_type': 'AUTO'},
    'WebGpuExecutionProvider': {},
}
PLATFORM_PROVIDERS = {
    'darwin': ('CoreMLExecutionProvider', 'WebGpuExecutionProvider'),
    'win32': ('WebGpuExecutionProvider', 'DmlExecutionProvider'),
    'linux': ('WebGpuExecutionProvider', 'OpenVINOExecutionProvider'),
}
PROVIDER_LABELS = {
    'CoreMLExecutionProvider': 'CoreML',
    'DmlExecutionProvider': 'DirectML',
    'OpenVINOExecutionProvider': 'OpenVINO',
    'WebGpuExecutionProvider': 'WebGPU',
}


def cache_directory():
    """Directory for compiled execution-provider kernels."""
    configured = os.environ.get('NEYRA_VOZ_CACHE_DIR')
    if configured:
        return Path(configured).expanduser()
    if sys.platform == 'win32':
        base = Path(os.environ.get('LOCALAPPDATA') or Path.home())
    else:
        base = Path(os.environ.get('XDG_CACHE_HOME') or Path.home() / '.cache')
    return base / 'neyra' / 'voz-cache'


def select_provider(available, platform=None, requested=None, device=None):
    """Pick the GPU execution provider for this machine, or None for CPU only.

    ``NEYRA_VOZ_ONNX_PROVIDER`` names an installed provider explicitly.
    ``NEYRA_VOZ_DEVICE`` accepts auto (default), cpu, gpu, or webgpu.
    """
    platform = platform or sys.platform
    requested = (os.environ.get('NEYRA_VOZ_ONNX_PROVIDER', '') if requested is None else requested).strip()
    device = (os.environ.get('NEYRA_VOZ_DEVICE', 'auto') if device is None else device).strip().lower()
    if requested:
        if requested not in available:
            raise ValueError(f'ONNX provider {requested} is unavailable in this Python installation.')
        return requested
    if device == 'cpu':
        return None
    if device == 'webgpu':
        preferred = ('WebGpuExecutionProvider',)
    elif device in ('gpu', 'auto'):
        preferred = PLATFORM_PROVIDERS.get(platform, ())
    else:
        raise ValueError('NEYRA_VOZ_DEVICE must be auto, cpu, gpu, or webgpu.')
    return next((name for name in preferred if name in available), None)


def provider_options(provider, device=None):
    """Session options for a provider, including the OpenVINO kernel cache."""
    options = dict(PROVIDER_OPTIONS.get(provider, {}))
    if provider == 'OpenVINOExecutionProvider':
        device = (os.environ.get('NEYRA_VOZ_DEVICE', 'auto') if device is None else device).strip().lower()
        options['device_type'] = 'GPU' if device == 'gpu' else 'AUTO'
        directory = cache_directory()
        try:
            directory.mkdir(parents=True, exist_ok=True)
            options['cache_dir'] = str(directory)
        except OSError:
            pass
    return options


def session_providers(provider, name, device=None):
    """Keep the autoregressive decoder on CPU; offload the front end and encoder."""
    if provider and name in GPU_SESSIONS:
        return [(provider, provider_options(provider, device)), CPU_PROVIDER]
    return [CPU_PROVIDER]


def model_directory(status):
    configured = os.environ.get('NEYRA_VOZ_MODEL_DIR')
    if configured:
        root = Path(configured).expanduser()
    else:
        from huggingface_hub import hf_hub_download
        from PySide6.QtCore import QStandardPaths
        root = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation)) / 'voz' / REVISION
        root.mkdir(parents=True, exist_ok=True)
        for index, name in enumerate(FILES):
            status('downloading', f'Voz: preparing {name} ({index + 1}/{len(FILES)})', round(index / len(FILES) * 100))
            if not (root / name).is_file():
                path = hf_hub_download('desert-ant-labs/voz', 'onnx-fp16/' + name, revision=REVISION)
                temporary = root / (name + '.part')
                shutil.copyfile(path, temporary)
                temporary.replace(root / name)
    if root is None or any(not (root / name).is_file() for name in FILES):
        raise RuntimeError('Incomplete Voz ONNX bundle. NEYRA_VOZ_MODEL_DIR must contain all native onnx-fp16 files.')
    return root


def frame_audio(samples, c):
    """Vectorized centered framing; preserves the upstream geometric right pad."""
    hop, rows, count = c['hop_length'], c['n_rows'], c['n_samples']
    padded = np.zeros(hop * rows, dtype=np.float32)
    pad = c['n_fft'] // 2
    total = min(c['n_padded_samples'], len(padded))
    n = min(len(samples), count, total - pad)
    padded[pad:pad + n] = samples[:n]
    if len(samples) == count and pad + count < total:
        tail = total - pad - count
        padded[pad + count:total] = samples[-1] * np.power(np.float32(c['preemph']), np.arange(1, tail + 1, dtype=np.float32))
    audio = np.ascontiguousarray(padded.reshape(rows, hop).T[None, :, None, :])
    valid_mel = max(1, min(c['valid_frames'], len(samples) // hop + 1))
    mel_mask = (np.arange(c['valid_frames']) < valid_mel).astype(np.float32).reshape(1, 1, 1, -1)
    attended = max(1, min(c['enc_frames'], (len(samples) + hop * 8 - 1) // (hop * 8)))
    bias = np.where(np.arange(c['enc_frames']) < attended, 0., -40000.).astype(np.float32).reshape(1, -1, 1, 1)
    return audio, mel_mask, bias, min(c['enc_frames'], (valid_mel + 7) // 8)


def boundary(samples, rate):
    frame = max(1, round(.02 * rate))
    begin = max(frame, len(samples) - 3 * rate)
    block = samples[begin:begin + ((len(samples) - begin) // frame) * frame]
    if len(block) < frame:
        return len(samples)
    energy = np.mean(block.reshape(-1, frame) ** 2, axis=1)
    positions = begin + np.arange(len(energy)) * frame + frame // 2
    floor = max(float(energy.min()), 1e-9)
    scores = energy * (1 + (len(samples) - positions) / (3 * rate))
    scores[energy > 2 * floor] = np.inf
    return int(positions[np.argmin(scores)])


def timed_words(tokens, vocabulary, seconds, offset):
    words = []
    current = None
    for token, start, end in tokens:
        if not 0 <= token < len(vocabulary):
            continue
        piece = vocabulary[token]
        if piece.startswith('<') and piece.endswith('>'):
            continue
        if piece.startswith('▁') or current is None:
            if current and current['text']:
                words.append(current)
            current = {'text': '', 'start': offset + start * seconds, 'end': offset + end * seconds}
        current['text'] += piece.replace('▁', '')
        current['end'] = max(current['start'], current['end'], offset + end * seconds)
    if current and current['text']:
        words.append(current)
    return words


def fold(word):
    return ''.join(c for c in word.casefold() if c.isalnum() or c == "'")


def splice(previous, following, at):
    if not previous or not following:
        return previous + following
    tail = [i for i, w in enumerate(previous) if w['start'] >= at - 3]
    head = [i for i, w in enumerate(following) if w['start'] < at + 3]
    best = (0, float('-inf'), 0, 0)
    for i in tail:
        for j in head:
            n = 0
            while i + n < len(previous) and j + n < len(following):
                a, b = previous[i + n], following[j + n]
                if abs(a['start'] - b['start']) > 1 or fold(a['text']) != fold(b['text']):
                    break
                n += 1
            if n >= 2:
                best = max(best, (n, -abs(previous[i]['start'] - following[j]['start']), i, j))
    n, _, i, j = best
    if n >= 2:
        left, right = previous[:i + n], following[j + n:]
    else:
        left = [w for w in previous if w['start'] < at]
        right = [w for w in following if w['start'] >= at]
    if left and right and fold(left[-1]['text']) == fold(right[0]['text']):
        if left[-1]['text'] != right[0]['text'] or right[0]['start'] < left[-1]['end']:
            right = right[1:]
    if left and right and right[0]['text'][:1].islower() and left[-1]['text'][-1:] in '.!?':
        left = [*left[:-1], {**left[-1], 'text': left[-1]['text'][:-1]}]
    return left + right


class VozEngine:
    def __init__(self, status=lambda *args: None, closed=None):
        import onnxruntime as ort
        self.closed = closed or threading.Event()
        self.directory = root = model_directory(status)
        self.config = c = json.loads((root / 'meta.json').read_text(encoding='utf-8'))
        required = ('sample_rate', 'hop_length', 'n_samples', 'n_rows', 'n_fft', 'n_padded_samples', 'valid_frames', 'enc_frames', 'joint_hidden', 'pred_hidden', 'pred_layers', 'vocab_size', 'decode_width')
        if any(type(c.get(k)) is not int or not 0 < c[k] < 10_000_000 for k in required):
            raise ValueError('Invalid Voz model geometry.')
        if c['sample_rate'] != 16000 or not 0 <= c['blank_idx'] <= c['vocab_size'] or not c['durations']:
            raise ValueError('Unsupported Voz model metadata.')
        self.vocabulary = json.loads((root / 'vocab.json').read_text(encoding='utf-8'))
        if len(self.vocabulary) < c['vocab_size']:
            raise ValueError('Voz vocabulary is too small.')
        self.embedding = np.fromfile(root / 'embedding.f16', dtype='<f2').astype(np.float32).reshape(c['vocab_size'] + 1, c['pred_hidden'])
        options = ort.SessionOptions()
        options.intra_op_num_threads = min(4, os.cpu_count() or 1)
        options.inter_op_num_threads = 1
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.device = os.environ.get('NEYRA_VOZ_DEVICE', 'auto').strip().lower()
        self.provider = select_provider(ort.get_available_providers(), device=self.device)
        if self.provider == 'DmlExecutionProvider':
            options.enable_mem_pattern = False
            options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        label = PROVIDER_LABELS.get(self.provider, 'CPU')
        status('loading', f'Loading Voz ONNX sessions in Python ({label})...', -1)
        try:
            self.sessions = self._load_sessions(ort, root, options, self.provider, self.device)
        except Exception:
            if self.provider is None:
                raise
            status('loading', f'Voz {label} acceleration is unavailable; using the CPU.', -1)
            self.provider = None
            self.device = 'cpu'
            self.sessions = self._load_sessions(ort, root, options, None, self.device)
        self.lanes = self.sessions['decoder'].get_inputs()[0].shape[0]
        if type(self.lanes) is not int or not 1 <= self.lanes <= 64:
            raise ValueError('Expected a fixed native Voz decoder batch of 1–64 lanes.')
        self._lock = threading.Lock()

    def _load_sessions(self, ort, root, options, provider, device):
        return {name: ort.InferenceSession(str(root / (name + '.onnx')), sess_options=options, providers=session_providers(provider, name, device))
                for name in ('mel', 'encoder', 'decoder')}

    def check(self):
        if self.closed.is_set():
            raise RuntimeError('Voz is shutting down.')

    def run(self, name, values):
        self.check()
        session = self.sessions[name]
        inputs = session.get_inputs()
        if len(inputs) != len(values):
            raise ValueError(f'Unexpected {name} ONNX signature.')
        return session.run(None, {node.name: value for node, value in zip(inputs, values)})

    def encode(self, audio):
        rows, mask, bias, valid = frame_audio(audio, self.config)
        mel = self.run('mel', [rows, mask])[0]
        return self.run('encoder', [mel, bias])[0][0, :, 0, :], valid

    def decode(self, encoded):
        c = self.config
        lanes, width = self.lanes, c['decode_width']
        hidden = c['pred_layers'] * c['pred_hidden']
        h = np.zeros((lanes, hidden, 1, 1), np.float32)
        state = np.zeros_like(h)
        embed = np.zeros((lanes, c['pred_hidden'], 1, 1), np.float32)
        step = np.zeros((lanes, c['joint_hidden'], 1, width), np.float32)
        positions = np.zeros(lanes, dtype=int)
        labels = np.full(lanes, c['blank_idx'], dtype=int)
        emissions = np.zeros(lanes, dtype=int)
        results = [[] for _ in encoded]
        while any(positions[i] < valid for i, (_, valid) in enumerate(encoded)):
            self.check()
            step.fill(0)
            for lane, (projection, valid) in enumerate(encoded):
                embed[lane, :, 0, 0] = self.embedding[labels[lane]]
                span = min(width, valid - positions[lane])
                if span > 0:
                    step[lane, :, 0, :span] = projection[:, positions[lane]:positions[lane] + span]
            logits, new_h, new_c = self.run('decoder', [embed, h, state, step])
            tokens = np.argmax(logits[:, :c['vocab_size'] + 1, 0, :], axis=1)
            durations = np.argmax(logits[:, c['vocab_size'] + 1:, 0, :], axis=1)
            for lane, (_, valid) in enumerate(encoded):
                span = min(width, valid - positions[lane])
                offset = 0
                while offset < span:
                    token = int(tokens[lane, offset])
                    duration = c['durations'][int(durations[lane, offset])]
                    if token != c['blank_idx']:
                        at = int(positions[lane]) + offset
                        results[lane].append((token, at, at + duration))
                        h[lane], state[lane] = new_h[lane], new_c[lane]
                        labels[lane] = token
                        emissions[lane] += 1
                        if duration == 0 and emissions[lane] >= 10:
                            duration, emissions[lane] = 1, 0
                        offset += duration
                        break
                    emissions[lane] = 0
                    offset += max(duration, 1)
                positions[lane] += offset
        return results

    def transcribe(self, path, progress=lambda value: None):
        with self._lock, wave.open(str(path), 'rb') as audio:
            if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (1, 2, 16000):
                raise ValueError('Voz expects mono, signed 16-bit, 16 kHz WAV.')
            c = self.config
            total = audio.getnframes()
            start, words, futile = 0, [], 0
            while start < total:
                self.check()
                windows = []
                # Bounded audio memory: at most one decoder batch of windows.
                while start < total and len(windows) < self.lanes:
                    audio.setpos(start)
                    samples = np.frombuffer(audio.readframes(c['n_samples']), dtype='<i2').astype(np.float32) / 32768
                    windows.append((start, samples))
                    start += boundary(samples, 16000) if len(samples) == c['n_samples'] and start + len(samples) < total else len(samples)
                encoded = [self.encode(samples) for _, samples in windows]
                decoded = self.decode(encoded)
                for (at, samples), tokens in zip(windows, decoded):
                    if not tokens and futile < 8 and np.mean(samples[::16] ** 2) > 1e-5:
                        tokens = self.decode([self.encode(samples[:int(len(samples) * .93)])])[0]
                        futile = 0 if tokens else futile + 1
                    produced = timed_words(tokens, self.vocabulary, c['hop_length'] * 8 / 16000, at / 16000)
                    for word in produced:
                        low = max(0, round((word['start'] - at / 16000) * 16000))
                        high = min(len(samples), round((word['end'] - at / 16000) * 16000))
                        block = samples[low:high]
                        if len(block) >= 160:
                            energies = np.array([np.mean(block[i:i + 160] ** 2) for i in range(0, len(block), 160)])
                            if energies.max() > 0:
                                last = np.flatnonzero(energies >= .05 * energies.max())[-1]
                                word['end'] = min(word['end'], (at + low + (int(last) + 1) * 160) / 16000)
                    words = splice(words, produced, at / 16000)
                progress(min(1., start / max(1, total)))
            previous = 0.
            duration = total / 16000
            for word in words:
                word['start'] = min(duration, max(previous, word['start']))
                word['end'] = min(duration, max(word['start'], word['end']))
                previous = word['start']
            for word, following in zip(words, words[1:]):
                word['end'] = min(word['end'], following['start'])
            return {'text': ' '.join(w['text'] for w in words), 'words': words, 'duration': duration}

    def close(self):
        self.closed.set()
