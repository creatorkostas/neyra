# Assistant providers and Python Voz

## Settings

Voice settings → Appearance switches between light and dark immediately and saves
the selection. Voice settings → Assistant provider selects one of:

| Provider | Configuration |
| --- | --- |
| ChatGPT | Sign in on the Assistant page, as before. |
| Local model server | Start Ollama, LM Studio, or llama.cpp's OpenAI-compatible server. Enter the base URL including `/v1` and the exact model identifier. Ollama defaults to `http://127.0.0.1:11434/v1`. |
| OpenCode API | Start `opencode serve`, normally at `http://127.0.0.1:4096`. Optional model uses `provider/model`. Authentication reads `OPENCODE_SERVER_PASSWORD` and optionally `OPENCODE_SERVER_USERNAME`. |
| OpenCode CLI | Install OpenCode and authenticate it using `opencode auth login`. Enter its executable path/name and optionally `provider/model`. |
| No assistant | Local tool commands work; general questions, translation, summarization, and extraction need an assistant. |

The compatible-server option also accepts a remote HTTPS endpoint, including an
OpenCode Zen compatible endpoint. Set `NEYRA_ASSISTANT_API_KEY` in Neyra's launch
environment when authentication is required. Keys are not stored in settings or
portable backups. Plain HTTP is restricted to loopback addresses.

OpenCode runs as a text provider with tool permissions denied; Neyra owns desktop
actions. API requests use an isolated session which is deleted after the request.
CLI requests run from an empty temporary working directory and send input over
stdin. OpenCode itself may retain session history according to its configuration.
Provider changes interrupt pending responses and clear conversation/cache state.
Screen questions currently require ChatGPT; other providers report this limitation.
The added providers return complete replies (not token streams). HTTP timeout is
90 seconds; CLI timeout is 180 seconds. Cancellation suppresses stale output; API
cancellation also requests session abort, and CLI cancellation terminates the child.

## Local tool routing

The existing deterministic parser handles canonical commands immediately. Other
requests go to Needle 3 locally, without an assistant account. A small vocabulary
shortlist reduces the number of tool schemas presented to the model; Needle still
chooses the operation and extracts arguments. Ordinary conversation routes to the
selected assistant. The local router never invokes functions itself: one call,
confidence/grounding checks, an application allowlist, and the existing parser
must all pass before dispatch. Uncertain requests produce a clarification.

Needle's first use downloads its native engine and weights. Release builds bundle
both `whistle.cact` and `needle3.cact`. Source runs can set
`NEYRA_NEEDLE_WEIGHTS` to a local Needle 3 `.cact` file. The Python package already
includes Needle; no external assistant is required for tools.

## Voz runtime

`neyra/voz.py` replaces the JavaScript/WASM host with Python, NumPy, and native
ONNX Runtime. It uses the native `onnx-fp16` export of Voz v0.5.0, pinned to Hub
commit `12802bf4e2b5e97e1289b723bc6283b6f1a1ace5`. It does not retrain the model or
claim to reproduce its weights. Existing model caches from the Node web export
are a different format and cannot be reused directly.

The pipeline stages centered PCM rows and masks, runs mel and encoder graphs,
then performs batched TDT decoding with recurrent state and duration predictions.
Overlapping windows meet at quiet audio boundaries and are merged by matching
word runs. SentencePiece tokens become words with monotonic timestamps; audio
energy trims word ends. Empty speech windows retry at a shorter length.

Optimizations implemented: vectorized NumPy framing/argmax/energy calculations,
reused ONNX sessions, bounded window batches, reusable decoder staging buffers
within each batch, and a four-thread CPU cap to avoid oversubscription. Neural
network arithmetic remains in native ONNX Runtime. No claim of a measured speedup
over Node is made.

The first use downloads seven files. Download messages show file progress rather
than byte progress. Set `NEYRA_VOZ_MODEL_DIR` to an unpacked native `onnx-fp16`
directory for offline use. It must contain `meta.json`, `vocab.json`,
`embedding.f16`, `mel.onnx`, `encoder.onnx`, `encoder.weights`, and `decoder.onnx`.
Downloaded external weights are materialized beside the graphs because recent
ONNX Runtime versions reject external-data symlinks escaping the model directory.

### Execution providers

The mel front end and encoder run on the GPU when the installed ONNX Runtime build
offers one; the autoregressive decoder stays on the CPU because it makes one small
call per token. The wheel installed by `uv sync` is chosen per platform, so a
normal install needs no configuration:

| Platform | Wheel | Accelerated provider |
| --- | --- | --- |
| Linux x86_64 | `onnxruntime-webgpu` | WebGPU (Vulkan driver) |
| Windows x86_64 | `onnxruntime-webgpu` | WebGPU (Dawn over DirectX 12) |
| macOS | `onnxruntime` | CoreML |
| Other | `onnxruntime` | CPU only |

`NEYRA_VOZ_DEVICE` accepts `auto` (default), `cpu`, `gpu`, or `webgpu`.
`NEYRA_VOZ_ONNX_PROVIDER` names an installed provider explicitly and overrides the
device setting. `NEYRA_VOZ_CACHE_DIR` relocates the OpenVINO kernel cache, which
avoids recompiling the graphs on every start. If a GPU session cannot be created,
Voz reports the failure in the model status line and retries on the CPU.

Measured on a 9.76 s clip on an i5-1135G7 with Iris Xe, three runs, warm caches:

| Provider | Load | Transcribe | Real-time factor |
| --- | --- | --- | --- |
| CPU | 2.8 s | 1.38 s | 0.14 |
| OpenVINO, `auto` | 2.8 s | 1.40 s | 0.14 |
| OpenVINO, `device=gpu` | 1.0 s | 1.19 s | 0.12 |
| WebGPU (default) | 0.9 s | 0.91 s | 0.09 |

WebGPU needs only a Vulkan driver on Linux, or DirectX 12 on Windows, and was the
fastest and most reliable option measured, so it is the only GPU wheel shipped.
On an AMD Windows PC, DirectML and WebGPU transcribed within noise of each other,
which is why DirectML is no longer installed and WebGPU covers both platforms.
OpenVINO remains available on Linux by swapping the marker in `pyproject.toml` to
`onnxruntime-openvino`; the wheels provide the same module and cannot be installed
together. OpenVINO also needs `intel-compute-runtime` and `level-zero-loader`, its
`auto` device can stay on the CPU plugin, and forcing `device=gpu` crashes when
Mesa Rusticl is also registered as an OpenCL ICD (restrict `OCL_ICD_VENDORS` to the
Intel ICD). The DirectML wheel stays reachable for comparisons through the
benchmark script.

Compare providers on one machine with:

```sh
uv run python scripts/make_sample_audio.py --output sample.wav
uv run python scripts/benchmark_voz.py --variants cpu,webgpu \
  --audio sample.wav --runs 3
```

`make_sample_audio.py` reuses a Neyra Piper voice or downloads one, and writes the
mono 16 kHz WAV Voz accepts. The benchmark script creates isolated environments
with `uv`, so the variants cannot overwrite each other. On Windows,
`scripts/benchmark_voz_windows.ps1` installs the locked dependencies, reports the
display adapter, and compares CPU with WebGPU (add `-Variants cpu,webgpu,directml`
to include DirectML). Packaged builds still need target-device verification.

### Pipeline performance

The GPU encoder is cheap; most of the remaining time is the autoregressive decoder
on the CPU, which the pipeline used to run for all 16 lanes even when a clip held
one window. Three changes removed most of that idle work. Measured on the same
laptop with the WebGPU encoder and CPU decoder, best of three warm runs:

| Audio | Before | After | Real-time factor |
| --- | --- | --- | --- |
| 9.6 s dictation | 0.94 s | 0.45 s | 0.10 → 0.05 |
| 38.4 s recording | 2.03 s | 1.31 s | 0.05 → 0.03 |
| 9.6 s, CPU-only install | 1.54 s | 0.94 s | 0.16 → 0.10 |

- The decoder batch is dynamic. Upstream exports a fixed 16-lane decoder, so a
  short dictation paid for 15 silent lanes. On first use `onnx` rewrites the
  decoder's declared batch, the result is cached under `NEYRA_VOZ_CACHE_DIR`, and
  decoding then uses only the windows that exist. Transcripts and word timings
  matched the fixed-batch decoder exactly in testing.
- Windows are encoded four at a time (`ENCODER_BATCH` in `neyra/voz.py`): 343 ms
  per window became 267 ms, and larger batches stopped helping.
- On a GPU build the next batch is encoded while the current one decodes, because
  the encoder runs on the GPU and the decoder on the CPU. CPU-only installs stay
  sequential to avoid oversubscribing their cores.
- The relaxed decoder adds `onnx` as a dependency. If the rewrite or its cache is
  unusable, Voz deletes it and loads the shipped decoder, so transcription still
  works with the fixed batch.

The native port is not yet proven equivalent on long or multilingual recordings.
Upstream's advanced recovery for partially truncated windows and keyword boosting
are not implemented. Test long recordings before relying on it for meeting notes.
Align and the other optional native meeting models remain separate dependencies.

### Validation evidence

A live CPU test on the upstream public-domain six-second LibriVox fixture loaded
sessions in 7.04 seconds and transcribed in 1.60 seconds. The output contained the
expected sentence and word timestamps, with a trailing partial word (`Rec`) from
the cut audio. These are one-machine smoke measurements, not performance promises
or word-error-rate benchmarks. Unit tests cover framing, masks, overlap joining,
provider protocols, and the local routing guards.

### Attribution

Voz is powered by [Desert Ant Labs](https://desertant.com). The adapted pipeline
remains under the Desert Ant Labs Source-Available License; see
`packaging/licenses/DesertAnt-LICENSE.md`. It is an exception to the repository's
MIT license. Model downloads retain upstream terms.

Neyra performs no install reporting, license activation, or other calls to Desert
Ant Labs servers. Transcription and model downloads are the only network use, and
model downloads already require an explicit first-use fetch.

Upstream code inspected: `Desert-Ant-Labs/desert-ant-core` commit
`541a9ce4a148e9308a99f1edbfd927906394b686`, especially `Sources/Voz/Pipeline.swift`,
`Words.swift`, `Engine+Onnx.swift`, and `Buffers.swift`.
Provider references: <https://opencode.ai/docs/server/> and
<https://opencode.ai/docs/cli/>. Needle API: <https://github.com/cactus-compute/needle/blob/main/llms.txt>.
