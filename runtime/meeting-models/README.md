# Meeting models helper

`neyra-meeting-models.exe` is a Windows x64 Swift command-line helper. It uses
Desert Ant Core v4.0.0 at immutable commit
`9ac125cc4b10696a7ae1d18723fb585b8c025ee1`. The package uses a revision pin
because that release itself declares a revision dependency on Windows.

## Build

Install or supply Swift 6.2+ for Windows x64, its matching Windows Swift SDK,
MSVC C++ x64/x86 build tools and a Windows 11 SDK. Git and Python are required;
`uv` is used if available. The [official Swift instructions](https://www.swift.org/install/windows/manual/)
describe those prerequisites. This script does not install Swift, request
administrator access, or change persistent environment variables. If the
workspace already contains an extracted toolchain under `assets/tools/swift-local`,
the script discovers its compiler, SDK and runtime directories automatically.

From the repository root:

```powershell
.venv/Scripts/python.exe scripts/setup_meeting_models.py
# An existing local toolchain can be selected explicitly:
.venv/Scripts/python.exe scripts/setup_meeting_models.py --swift C:/local/Swift/usr/bin/swift.exe --sdk C:/local/Swift/Windows.platform/Developer/SDKs/Windows.sdk --runtime-bin C:/local/Swift/Runtimes/usr/bin
```

The script downloads the pinned `ai-edge-litert==2.2.0` and
`onnxruntime-directml==1.23.0` Windows wheels into
`assets/meeting-models-build`, generates import libraries using the Swift LLVM tools,
builds release code, runs protocol tests and checks capabilities. It stages
`assets/meeting-models/neyra-meeting-models.exe`, `libLiteRt.dll`, ONNX Runtime
and DirectML DLLs, Swift runtime DLLs and SwiftPM resource directories. The
shared SDK inference target links ONNX Runtime on Windows even for LiteRT
models. Preserve that directory as a unit when
bundling. Use `--runtime-bin` for any runtime directory missing from the current
environment. The final check verifies loading on the build machine; test the
bundle on a clean Windows machine before distributing it.

The app discovers that path or the `NEYRA_MEETING_MODELS` override. To test
the protocol tests separately, run `swift test --filter MeetingProtocolTests`,
with the same LiteRT linker search path used in the setup script.
After building, run the model-free executable checks with
`python -m unittest discover -s runtime/meeting-models/verification -v`.
Set `NEYRA_TEST_MODELS=1` to also test actual Align and Who inference on
synthetic 16 kHz and 48 kHz WAVs. This optional test can download models.

## Protocol

Start a process, send one UTF-8 JSON line to stdin, and close stdin. The helper
consumes one request and exits. Terminate the process to cancel work. Stdout
contains JSON lines only. Native diagnostics are redirected to stderr. Events
echo an optional string, number or null `id`.

```json
{"operation":"check"}
{"event":"result","capabilities":["align","who","clear","gist"],"sdk_version":"4.0.0","languages":["en","es","fr","it","pt","de","ja","ko","zh"]}
```

`check` does not construct models, download weights or run inference.

```json
{"id":"cleanup","operation":"enhance","path":"C:/recording.wav","output_path":"C:/cleaned.wav","language":"en"}
{"event":"progress","id":"cleanup","message":"Loading Clear and cleaning audio. First use downloads model weights."}
{"event":"result","id":"cleanup","path":"C:/cleaned.wav"}
```

Clear accepts a WAV and writes a separate WAV. Existing output files are
rejected. It writes a temporary sibling and moves it into place after success.
Force termination can leave a `.neyra-<uuid>.wav` sibling; the final output
is never a partial file.

```json
{"operation":"analyze","path":"C:/original-16k.wav","words":[{"text":"Hello","start":0.1,"end":0.5}],"speakers":true,"organize":true,"language":"en"}
{"event":"result","words":[{"text":"Hello","start":0.12,"end":0.48,"refined":true}],"turns":[{"speaker":0,"start":0.1,"end":1.5}],"topics":[{"slug":"technology","name":"Technology & Software","score":0.8}],"speaker_count":1}
```

The example result illustrates the shape, not a recorded inference. Analyze
requires the same mono WAV used for transcription and nonempty Voz words.
It accepts both the original 16 kHz audio and Clear's 48 kHz output. Align and
Who receive the file's actual sample rate and resample internally, so their
timestamps remain in seconds on that WAV's timeline. Align always runs.
Who runs when `speakers` is true and Gist when `organize` is true.
Gist classifies the joined words using its English variant for English meetings
and its multilingual variant for other supported languages. It supplies topic
tags, not a summary or chapters. Speaker numbers start at zero, represent
anonymous voices, can overlap and cover up to four dominant speakers.
`refined:false` means Align retained a timestamp. Title has no Windows build;
the caller creates the editable title.

Requests are limited to 16 MiB, 200000 words and a 1 GiB WAV. Words require
finite, ordered, nonnegative timestamps. Align accepts English, Spanish, French,
Italian, Portuguese, German, Japanese, Korean, and Chinese language codes.
Failures emit `{"event":"error","message":"..."}` and exit with code 1.
Progress precedes each model operation. The first use can take time to download
weights; later runs use the SDK cache. A successful capability check does not
prove that downloads, license activation or inference will succeed.

The SDK's model loading contacts Hugging Face and Desert Ant's licensing service;
audio and transcript inference run locally. Review the upstream
[license and activation behavior](https://github.com/Desert-Ant-Labs/desert-ant-core/tree/9ac125cc4b10696a7ae1d18723fb585b8c025ee1#licensing)
before distribution. No external inference provider is used.

## Verified locally

On 2026-10-19, Swift 6.2.4 x64 built the pinned package on Windows using
workspace-local extracted toolchain files and Windows SDK 10.0.26100.0.
The setup command, four Swift tests and five native protocol tests passed.
The staged helper passed `check` with the child PATH restricted to System32.
A synthetic two-voice recording passed both `enhance` and `analyze`: Clear
wrote a WAV, Align refined 20 of 28 words, Who found two speakers and five
turns, and Gist returned a topic. After fixing the Clear 48 kHz handoff, the
full Python pipeline passed on the same recording: 28 Voz words, 28 Align
refinements, two labeled speakers, and a Gist topic. Both 16 kHz and 48 kHz
native inference checks passed. These checks prove execution and protocol
behavior; they do not measure transcription, timestamp or speaker accuracy.
The synthetic request/result/diagnostic logs are in the local, ignored
`assets/meeting-models-build/native-*` files. Clean-machine distribution and
force-termination cleanup were not tested.

## API references

The implementation was checked against the pinned source, rather than older
SDK examples:

- [Align.refine and WordTiming](https://github.com/Desert-Ant-Labs/desert-ant-core/tree/9ac125cc4b10696a7ae1d18723fb585b8c025ee1/Sources/Align)
- [Who.diarize](https://github.com/Desert-Ant-Labs/desert-ant-core/blob/9ac125cc4b10696a7ae1d18723fb585b8c025ee1/Sources/Who/Who.swift)
- [Clear.enhance](https://github.com/Desert-Ant-Labs/desert-ant-core/blob/9ac125cc4b10696a7ae1d18723fb585b8c025ee1/Sources/Clear/Clear.swift)
- [Gist.classify](https://github.com/Desert-Ant-Labs/desert-ant-core/blob/9ac125cc4b10696a7ae1d18723fb585b8c025ee1/Sources/Gist/Gist.swift)
- [Upstream LiteRT DLL and import library setup](https://github.com/Desert-Ant-Labs/desert-ant-core/blob/9ac125cc4b10696a7ae1d18723fb585b8c025ee1/Tools/dal.sh)
