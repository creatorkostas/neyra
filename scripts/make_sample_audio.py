"""Create a mono 16-bit 16 kHz WAV for Voz benchmarks from the local Piper voice.

The voice is downloaded once into the Neyra voice cache and reused afterwards.
Output works on Linux, macOS, and Windows, so the same file can be compared
across machines with ``scripts/benchmark_voz.py``.
"""
import argparse
import os
import threading
import wave
from pathlib import Path

import numpy as np

from neyra.speech import _FILES, VOICE, _download

TEXT = ('Neyra turns speech into text on your own computer. The quick brown fox jumps over the lazy dog, '
        'then it reads the note out loud and schedules a reminder for tomorrow morning.')
SAMPLE_RATE = 16000


def cache_base():
    if os.name == 'nt':
        return Path(os.environ.get('LOCALAPPDATA') or Path.home())
    return Path(os.environ.get('XDG_CACHE_HOME') or Path.home() / '.cache')


def voice_candidates():
    """Neyra voice caches, which depend on the Qt application name of each build."""
    base = cache_base()
    return [base / 'Neyra' / 'Neyra' / 'piper', base / 'Neyra' / 'cache' / 'Neyra' / 'piper',
            base / 'Neyra' / 'piper']


def default_voice_dir(voice=VOICE):
    for directory in voice_candidates():
        if (directory / f'{voice}.onnx').is_file():
            return directory
    return voice_candidates()[-1]


def voice_file(directory, voice):
    """Return the voice model path, downloading the pinned files when missing."""
    directory = Path(directory).expanduser()
    model = directory / f'{voice}.onnx'
    if not model.is_file() or not model.with_suffix('.onnx.json').is_file():
        print(f'Downloading Piper voice {voice} into {directory}')
        cancel = threading.Event()
        for name in (f'{voice}.onnx', f'{voice}.onnx.json'):
            if not (directory / name).is_file():
                _download(directory, name, cancel, voice)
    return model


def resample(samples, source_rate, target_rate=SAMPLE_RATE):
    if source_rate == target_rate:
        return samples
    count = int(round(len(samples) * target_rate / source_rate))
    return np.interp(np.arange(count) * source_rate / target_rate, np.arange(len(samples)), samples)


def synthesize(output, directory, voice, text):
    from piper import PiperVoice

    model = voice_file(directory, voice)
    with wave.open(str(output), 'wb') as destination:
        PiperVoice.load(model, use_cuda=False, download_dir=model.parent).synthesize_wav(text, destination)
    with wave.open(str(output), 'rb') as source:
        rate, channels, width = source.getframerate(), source.getnchannels(), source.getsampwidth()
        if width != 2:
            raise ValueError('Expected 16-bit Piper output.')
        samples = np.frombuffer(source.readframes(source.getnframes()), dtype='<i2').astype(np.float32) / 32768
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    pcm = np.clip(resample(samples, rate) * 32767, -32768, 32767).astype('<i2')
    with wave.open(str(output), 'wb') as destination:
        destination.setnchannels(1)
        destination.setsampwidth(2)
        destination.setframerate(SAMPLE_RATE)
        destination.writeframes(pcm.tobytes())
    return len(pcm) / SAMPLE_RATE


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='voz-sample.wav', help='WAV file to write (mono, 16-bit, 16 kHz)')
    parser.add_argument('--voice', default=VOICE, help='Piper voice id to synthesize with')
    parser.add_argument('--voice-dir', help='voice cache directory (default: an existing Neyra cache)')
    parser.add_argument('--text', default=TEXT, help='text to synthesize')
    options = parser.parse_args()
    output = Path(options.output).expanduser().resolve()
    voice_dir = options.voice_dir or default_voice_dir(options.voice)
    seconds = synthesize(output, voice_dir, options.voice, options.text)
    print(f'Wrote {output} ({seconds:.2f} s of 16 kHz mono audio) with {options.voice}.')


if __name__ == '__main__':
    main()
