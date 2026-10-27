"""Benchmark Voz transcription across ONNX Runtime execution providers.

Runs in the current environment by default. ``--variants`` creates isolated
virtual environments with uv and compares CPU, OpenVINO, WebGPU, or DirectML on
the same audio file. GPU variants need the matching system drivers.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VARIANTS = {
    'cpu': ('onnxruntime>=1.23,<2', 'cpu'),
    'openvino': ('onnxruntime-openvino>=1.24,<2', 'auto'),
    'webgpu': ('onnxruntime-webgpu>=1.27,<2', 'webgpu'),
    'directml': ('onnxruntime-directml>=1.24.4,<2', 'auto'),
}


def interpreter(directory):
    return directory / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def benchmark(audio, runs, device=None, provider=None):
    import numpy as np
    import onnxruntime as ort
    from neyra.voz import PROVIDER_LABELS, VozEngine, select_provider

    numpy_version = np.__version__
    if provider:
        os.environ['NEYRA_VOZ_ONNX_PROVIDER'] = provider
    if device:
        os.environ['NEYRA_VOZ_DEVICE'] = device
    selected = select_provider(ort.get_available_providers())
    start = time.perf_counter()
    engine = VozEngine(lambda *args: None)
    load = time.perf_counter() - start
    timings = []
    result = {}
    for _ in range(runs):
        start = time.perf_counter()
        result = engine.transcribe(audio)
        timings.append(time.perf_counter() - start)
    engine.close()
    with wave.open(str(audio), 'rb') as source:
        duration = source.getnframes() / source.getframerate()
    return {
        'provider': PROVIDER_LABELS.get(engine.provider, 'CPU'),
        'runtime': ort.__version__,
        'numpy': numpy_version,
        'load_seconds': round(load, 3),
        'transcribe_seconds': [round(value, 3) for value in timings],
        'best_seconds': round(min(timings), 3),
        'real_time_factor': round(min(timings) / duration, 3),
        'audio_seconds': round(duration, 2),
        'text': result.get('text', ''),
    }


def ensure_models(directory):
    from neyra.voz import model_directory
    if directory:
        os.environ['NEYRA_VOZ_MODEL_DIR'] = str(Path(directory).expanduser())
    return model_directory(lambda *args: None)


def run_variant(name, audio, runs, models, workdir, keep):
    requirement, device = VARIANTS[name]
    environment = workdir / name
    if not keep or not interpreter(environment).is_file():
        subprocess.run(['uv', 'venv', '--python', '3.12', '--allow-existing', str(environment)], check=True)
        subprocess.run(['uv', 'pip', 'install', '--python', str(interpreter(environment)),
                        requirement, 'numpy'], check=True)
    command = [str(interpreter(environment)), str(Path(__file__).resolve()), '--worker',
               '--audio', str(audio), '--runs', str(runs)]
    environment_variables = {**os.environ, 'PYTHONPATH': str(ROOT), 'NEYRA_VOZ_MODEL_DIR': str(models)}
    environment_variables['NEYRA_VOZ_DEVICE'] = device
    environment_variables['NEYRA_VOZ_CACHE_DIR'] = str(workdir / 'openvino-cache')
    # The worker prints UTF-8; the Windows locale code page would fail to decode it.
    environment_variables['PYTHONIOENCODING'] = 'utf-8'
    output = subprocess.run(command, env=environment_variables, capture_output=True, text=True,
                            encoding='utf-8', errors='replace')
    if output.returncode != 0:
        return {'provider': name, 'failed': (output.stderr.strip().splitlines() or ['exit ' + str(output.returncode)])[-1]}
    result = next(json.loads(line[len('BENCH '):]) for line in output.stdout.splitlines() if line.startswith('BENCH '))
    result['variant'] = name
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audio', required=False, help='mono 16-bit 16 kHz WAV to transcribe')
    parser.add_argument('--runs', type=int, default=2)
    parser.add_argument('--model-dir', help='unpacked Voz onnx-fp16 directory (default: cached download)')
    parser.add_argument('--variants', help='comma-separated isolated variants: ' + ', '.join(VARIANTS))
    parser.add_argument('--device', choices=['auto', 'cpu', 'gpu', 'webgpu'], help='provider override for --worker and the current environment')
    parser.add_argument('--provider', help='explicit ONNX provider name for the current environment')
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--keep', action='store_true', help='keep variant virtual environments')
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    options = parser.parse_args()
    if not options.audio:
        parser.error('--audio is required')
    audio = Path(options.audio).expanduser().resolve()
    models = ensure_models(options.model_dir)
    if not options.variants:
        result = benchmark(audio, options.runs, options.device, options.provider)
        print(json.dumps(result, indent=2) if options.json else
              f"{result['provider']} (onnxruntime {result['runtime']}): "
              f"load {result['load_seconds']}s, best {result['best_seconds']}s "
              f"(RTF {result['real_time_factor']}) for {result['audio_seconds']}s audio\n{result['text']}")
        return
    workdir = Path(tempfile.mkdtemp(prefix='neyra-voz-bench-'))
    results = [run_variant(name, audio, options.runs, models, workdir, options.keep)
               for name in (item.strip() for item in options.variants.split(',')) if name]
    if options.json:
        print(json.dumps(results, indent=2))
        return
    print(f'{"variant":<10} {"provider":<10} {"runtime":<10} {"load":>7} {"best":>7} {"RTF":>6}')
    for result in results:
        if 'failed' in result:
            print(f'{result["provider"]:<10} failed: {result["failed"]}')
            continue
        print(f'{result["variant"]:<10} {result["provider"]:<10} {result["runtime"]:<10} '
              f'{result["load_seconds"]:>7} {result["best_seconds"]:>7} {result["real_time_factor"]:>6}')
    if not options.keep:
        import shutil
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == '__main__':
    if '--worker' in sys.argv:
        sys.argv.remove('--worker')
        parser = argparse.ArgumentParser()
        parser.add_argument('--audio', required=True)
        parser.add_argument('--runs', type=int, default=2)
        arguments = parser.parse_args()
        print('BENCH ' + json.dumps(benchmark(Path(arguments.audio), arguments.runs)))
    else:
        main()
