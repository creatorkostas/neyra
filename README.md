# Neyra — Local Desktop Voice Assistant (MVP)

A frameless, always-on-top PySide6 dictation widget backed by Cactus Whistle by default, with optional Desert Ant Voz transcription. Windows 10/11 and Linux (X11 best supported; Wayland limitations below). Whistle is pinned to English, preloads in the background, and streams live previews about once per second. Voz supports 25 languages and produces its transcript after recording stops.

## Current state

Neyra is a useful local speech-to-text tool in an early state. Its default Needle Whistle model is small and uses very little RAM. Transcription results are usable, but not exceptional.

Download the Windows and Linux builds from the [latest release](https://github.com/creatorkostas/neyra/releases/latest).

## Install with uv

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and use a 64-bit Windows or Linux system.

```bash
uv sync
uv run python -m neyra.main
```

This uses the Python 3.12 version specified in `.python-version`.

To enable the optional Voz engine, install Node.js 20 or newer, then install its runtime packages from the project folder:

```bash
npm install
```

In Neyra's **Style** page, choose **Whistle** for live text about once per second, or **Voz** for a final transcript after recording stops. Whistle loads its model into CPU memory in the background when selected. Voz downloads its model on first use (about 400 MB) and keeps it locally. Neyra reuses the loaded Voz model until the app exits; it uses about 1.2 GB of memory, and its Node runtime runs inference on the CPU with at most four inference threads. The dashboard shows model download progress in MB, and stalled downloads or engine failures can be retried. Recorded audio is not sent to a server. Voz's JavaScript API does not currently use Neyra's custom dictionary hints. The current Nuitka build does not bundle Node.js, so Voz in a packaged build requires Node.js and the npm packages to be available alongside the app.

For a microphone and native-engine smoke test:

```bash
uv run needle whistle playground
```

## Build with Nuitka (offline model included)

```bash
uv sync --extra build
uv run python scripts/build.py --onefile
```

The build script runs `needle download whistle --out assets/model` and `needle fetch --out assets/engine`, verifies that it can find the model and a native engine library, and includes both in Nuitka's onefile distribution. It sets `NEEDLE_WHISTLE_WEIGHTS`, `NEEDLE3_LIB_PATH`, and `HF_HUB_OFFLINE=1` at application startup. A packaged executable should not download weights at runtime.

For easier debugging first build a folder distribution:

```bash
uv run python scripts/build.py --standalone
```

Build on Windows to produce `dist/Neyra.exe`; build on Linux to produce `dist/Neyra`. Nuitka does not cross-compile. The executable is self-extracting, not a fully static binary; Linux still needs compatible system libraries and a display server.

**Packaging caveat:** Cactus's fetched engine layout may change, and some distributions may contain multiple libraries. The build deliberately fails instead of silently falling back to online downloads. If `NEEDLE3_LIB_PATH` is ignored by a future Cactus release or native dependencies are missing, verify against that release and adjust the packaging.

## Publish a release

Push a version tag such as `v0.1.0` to build both platform packages and publish them as GitHub release assets. The workflow also builds both packages on pushes to `main`.

## Controls

- **Hold** `Ctrl+Win` to record; release either key to finish. The overlay hides on release, and the transcript is copied to the clipboard when transcription completes.
- **Toggle** `Ctrl+Shift+Space` to start/stop recording.
- The dashboard includes local Insights, a recognition dictionary, spoken snippets, output styles, and a Notetaker that captures the microphone and default speaker audio.
- Notetaker uses Voz and Align for word timestamps. Optional Who speaker labels, Clear audio cleanup, and Gist topic tags have separate controls on the Notetaker page.
- Meeting titles are suggested from the transcript and can be edited. Search matches titles, topics, and transcript text. Summaries and follow-up suggestions still use local sentence extraction rules.
- Double-click the system tray icon to open the dashboard. Search, copy, or delete transcripts in the dated history feed.
- System tray right-click → Toggle recording / Copy last transcript / Show overlay / Quit.
- Drag the widget by holding the left mouse button.

Global shortcuts work through `pynput` on Windows and X11. They are **not** generally supported by pynput on native Wayland. For Wayland, use the tray menu or set up compositor-specific bindings / a desktop portal integration in a later iteration. Tray visibility also depends on the desktop environment.

## Set up meeting models

Install the Node packages for Voz with `npm install`. Build the native meeting helper with the setup script:

```powershell
uv run python scripts/setup_meeting_models.py
```

The helper uses the Desert Ant Swift SDK for Windows support. See [meeting runtime setup](runtime/meeting-models/README.md) for the Swift toolchain, C++ tools, and build options. The executable and its runtime libraries belong in `assets/meeting-models`. Set `NEYRA_MEETING_MODELS` to an absolute executable path to use another location.

On the **Notetaker** page:

- Enable **Speaker labels** to label turns with Who. Labels are numbers, not identified names. Overlapping turns can show multiple speakers.
- Enable **Clean audio** to run Clear before transcription. Clear reduces noise and echo, but also suppresses music and other non-speech sound.
- Enable **Organize notes** to suggest a title and add Gist topic tags. **Save title** updates a meeting title. Desert Ant Title is not used because its SDK requires Apple silicon.
- Choose **Meeting language** for Align. The supported languages are English, Spanish, French, Italian, Portuguese, German, Japanese, Korean, and Chinese. Voz detects the spoken language independently.

These settings apply to new recordings. Speaker labels and audio cleanup default to off; organization defaults to on. Meetings always use Voz followed by Align, independently of the dictation engine. Meeting transcripts preserve the recognized words instead of applying dictation styles or expanding snippets, which would break their timestamp correspondence.

Open a meeting to see its timestamped transcript and **Word timestamps** tab. The start and end cells indicate whether Align refined that boundary or kept Voz's timing. **Copy transcript** includes timestamps and enabled speaker labels. The meeting card menu also offers **Copy plain text**.

Model weights download on first use and are cached by the SDK. The native SDK also contacts Desert Ant for license activation. Audio processing runs locally. See the runtime guide for network and licensing details.

A failed processing attempt keeps the mixed recording in memory for **Retry processing**. You can disable an optional model before retrying, or choose **Discard recording**. Closing Neyra discards that unsaved recording. Successful processing removes temporary audio files; existing saved notes cannot be reprocessed without their audio.

The build script includes `assets/meeting-models` when present and excludes development toolchain installers. Node.js and the Voz npm packages remain separate runtime requirements. Verify the native helper and packaged application on the target machine before distributing.

## Text insertion

- The transcript is copied to the clipboard and automatically pasted into the focused application when recording finishes.
- On Wayland, `wl-copy` + `wtype` are attempted if installed and allowed by the compositor. Otherwise use **Copy last transcript** in the tray.
- The overlay is non-focusable to preserve the target text field, but paste delivery is best-effort. Some elevated apps, secure inputs, games and Wayland sessions block it. The clipboard is intentionally **not restored** because restoring it too early can race with the target application.
- Avoid dictating sensitive information into the wrong focused field. The MVP does not inspect or filter password fields.

## Architecture

```
neyra/
  main.py     # PySide6 overlay, tray, session lifecycle
  audio.py    # sounddevice microphone, 16 kHz mono float32
  stt.py      # Whistle streaming and optional Voz transcription on background threads
  hotkeys.py  # hold and toggle chords (Windows/X11)
  desktop.py  # best-effort cross-platform paste
  system_audio.py # default-speaker loopback capture for Notetaker
  text_tools.py # local speech cleanup and snippet expansion
pyproject.toml
```

The UI previews Whistle's `pending` text but only inserts committed transcription after recording ends. Voz returns its transcript after release and does not provide live previews in the JavaScript API. Its model download and transcription progress are reported by the worker. One-second audio blocks are streamed via a queue. All inference is off the GUI thread. Worker results and microphone levels reach the GUI through Qt signals. Audio streams are closed on failure and shutdown. Auto-paste waits for the shortcut modifiers to be released. There is no wake word, silence detection, or automatic timeout.

## Regression checks

```bash
uv run python -m unittest discover -s tests -v
```

These checks use isolated settings and simulated audio devices. They cover recording cleanup, shortcut reuse, output formatting, history retention, and the Voz subprocess protocol. They do not capture the microphone or system audio.

## Troubleshooting

- **Model errors:** test `needle whistle playground` for Whistle. For Voz, check Node.js 20+, run `npm install` in the project folder, and allow internet access for its first model download.
- **No mic:** check OS microphone permissions, default input device, and PortAudio availability.
- **No shortcuts on Wayland:** expected. Use tray and configure compositor bindings if needed.
- **Text didn't paste:** use tray → Copy last transcript; verify focus and clipboard tools.
- **No tray:** some Linux desktops need AppIndicator/tray support; window stays visible.

## References

- https://www.cactuscompute.com/blog/whistle
- https://www.cactuscompute.com/blog/whistle-best-practices
- https://github.com/cactus-compute/needle/blob/main/llms.txt

## Product naming

- Product: **Neyra**
- Python distribution/package and command: `neyra`
- Executable: `Neyra.exe` on Windows and `Neyra` on Linux
- Speech engines: Cactus Whistle (English, default); Desert Ant Voz (optional, 25 languages)

The project is a renamed prototype, not a validated distributable release. Test native engine availability, keyboard integration and Nuitka packaging on your target machine before distributing.
