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
`NEYRA_VOZ_ONNX_PROVIDER` can select an execution provider installed in the Python
environment; CPU is the tested default. DirectML/CUDA and packaged builds still
need target-device verification.

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

### Attribution and usage reporting

Voz is powered by [Desert Ant Labs](https://desertant.com). The adapted pipeline
and usage-reporting modules remain under the Desert Ant Labs Source-Available
License; see `packaging/licenses/DesertAnt-LICENSE.md`. They are exceptions to the
repository's MIT license. Model downloads retain upstream terms. The Python port
preserves monthly install reporting (random install ID, app/model/SDK identifiers;
no audio or transcript). License grants are signature-checked, cached, activated,
and retried without blocking offline inference. A live reporting-server contract
check is still needed before a production release.

Upstream code inspected: `Desert-Ant-Labs/desert-ant-core` commit
`541a9ce4a148e9308a99f1edbfd927906394b686`, especially `Sources/Voz/Pipeline.swift`,
`Words.swift`, `Engine+Onnx.swift`, `Buffers.swift`, and `Sources/Usage`.
Provider references: <https://opencode.ai/docs/server/> and
<https://opencode.ai/docs/cli/>. Needle API: <https://github.com/cactus-compute/needle/blob/main/llms.txt>.
