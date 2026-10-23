# Neyra — Local Desktop Voice Assistant (MVP)

A local dictation dashboard and floating recording overlay for Windows 10/11 and Linux. Cactus Whistle recognizes English and streams live previews about once per second. Desert Ant Voz supports 25 languages and produces its transcript after recording stops. Both engines run on your CPU. X11 has the best Linux shortcut support; see the Wayland limitations below.

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

In **Settings**, choose **Whistle** for live text or **Voz** for a final transcript after recording stops. Selecting an engine loads its model in the background. Voz downloads about 400 MB on first use and caches the files locally. Its loaded model uses about 1.2 GB of RAM and at most four inference threads. Neyra keeps loaded models in memory until you quit.

The Dictation panel shows loading, downloading, ready, transcribing, and error states. Voz download progress shows the current file's bytes and percentage when its size is available. To retry a failed load, use **Settings → Load / retry model**. Recorded audio is not sent to a server. Packaged builds include the Voz npm dependencies, including the platform's ONNX runtime. Install Node.js 20 or newer separately to use Voz.

## Set up dictation

1. Open **Settings → Microphone** and select an input, or use **System default**. The same choice applies to Notetaker.
2. Click **Test microphone** and speak. The meter shows the input level; the test does not save audio. Stop the test when finished. Changing pages, closing the window, or starting a recording also stops the test.
3. Choose a speech model. Whistle starts loading when Neyra opens; selecting Voz starts its first download or loads its cached model.
4. Hold **Ctrl + Win** while another app has focus, then release to transcribe and paste. You can also use **Start dictation** on the dashboard. Dashboard recordings copy their result and appear in history without pasting back into Neyra.

If a selected microphone is disconnected, Neyra asks you to choose another input. **Refresh microphones** updates the list. Each device name includes its audio API to distinguish duplicate Windows entries.

## Manage words and history

**Dictionary** stores recognition hints for Whistle. Voz does not support these hints. Under **Vocabulary corrections**, enter a misheard phrase and its intended spelling, then click **Save correction**. Corrections match whole words or phrases without case sensitivity and apply to new dictations from either engine. Select an existing row to update it or remove it. Corrections run before output formatting and snippet expansion. They do not change meeting words or timestamps.

Dictation history stays on this computer and retains the latest 500 entries. Search the feed, copy an entry, or delete it from its menu. **Clear history** asks for confirmation and removes saved dictations. Meeting notes are separate. Under **Settings → Local history**, turn off **Save new dictations to history** to stop saving new entries. Results still copy to your clipboard; this setting does not delete existing history or clear the system clipboard.

## Keep Neyra available

Enable **Settings → Start Neyra at login** to create a per-user startup entry. Windows uses Neyra's value in the current user's Run registry key; Linux uses `$XDG_CONFIG_HOME/autostart/neyra.desktop`, or `~/.config/autostart/neyra.desktop`. Turn the option off to remove Neyra's entry. Keep the app at the same location, or toggle the option off and on after moving it.

Normal launches open the dashboard. Login startup passes `--background` to open in the tray. If the desktop has no tray, Neyra opens the dashboard and closing it quits the app. With a tray available, **Keep running in the tray when I close the window** controls closing behavior. The tray menu shows recording state and offers dictation controls, Stop Notetaker, Copy last transcript, Settings, and Quit. Quit stops audio capture and closes the inference runtimes.

For a microphone and native-engine smoke test:

```bash
uv run needle whistle playground
```

## Set a spoken reminder

Hold **Ctrl + Alt + Space**, speak a reminder, then release the keys. This shortcut is separate from dictation. For example:

- "Remind me in an hour to take out the garbage."
- "Remind me in twenty-five minutes to check the oven."
- "Remind me in one hour and thirty minutes to call Sam."
- "Remind me to stretch in half an hour."

Neyra transcribes the command with your selected speech model and saves the reminder locally. It shows the task and scheduled time as confirmation. The delay starts when you release the shortcut, so transcription time does not add to the delay. Commands do not paste into another app or enter dictation history.

Supported delays use seconds, minutes, hours, days, or weeks, up to 365 days. Numbers can be digits or spoken English, including "a minute", "an hour", "half an hour", and "a quarter of an hour". Absolute dates and phrases such as "sometime later" are not supported. Neyra rejects unclear commands and keeps their text on the **Reminders** page for correction.

Open **Reminders** to type a command, use **Speak a reminder**, inspect scheduled times, or cancel a reminder. Due reminders move to **Recent reminders**, where **Dismiss** removes them. Neyra keeps all pending reminders and the latest 100 due reminders across restarts, independently of dictation history settings.

Keep Neyra running, including in the tray, for notifications at the scheduled time. Closed apps cannot notify; overdue reminders appear when you reopen Neyra. Windows and supported Linux trays use desktop notifications. Linux desktops without a tray can use `notify-send` from `libnotify`; if desktop notifications are unavailable or that command fails, Neyra opens a nonblocking reminder alert. Several reminders overdue at startup share one notification, and the full list remains in the dashboard.

## Build with Nuitka (offline model included)

```bash
uv sync --extra build
npm ci --omit=dev
uv run python scripts/build.py --onefile
```

The build script runs `needle download whistle --out assets/model` and `needle fetch --out assets/engine`, verifies the model and native engine library, and includes both in Nuitka's onefile distribution. It also includes the installed Voz `node_modules` directory. Run `npm ci` on the target build platform so the ONNX native binaries match Windows or Linux. The build fails if the npm dependency directory is missing.

At startup, Neyra sets `NEEDLE_WHISTLE_WEIGHTS`, `NEEDLE3_LIB_PATH`, and `HF_HUB_OFFLINE=1` for the bundled Whistle assets. Whistle should not download weights in a packaged build. Voz and the optional meeting models still download their own assets on first use.

For easier debugging first build a folder distribution:

```bash
uv run python scripts/build.py --standalone
```

Build on Windows to produce `dist/Neyra.exe`; build on Linux to produce `dist/Neyra`. Nuitka does not cross-compile. The executable is self-extracting, not a fully static binary; Linux still needs compatible system libraries and a display server.

**Packaging caveat:** Cactus's fetched engine layout may change, and some distributions may contain multiple libraries. The build deliberately fails instead of silently falling back to online downloads. If `NEEDLE3_LIB_PATH` is ignored by a future Cactus release or native dependencies are missing, verify against that release and adjust the packaging.

## Publish a release

Push a version tag such as `v0.1.0` to build both platform packages and publish them as GitHub release assets. The workflow also builds both packages on pushes to `main`.

Tagged releases also attach `neyra-bin-VERSION-aur.tar.gz`, a submission archive for the Arch User Repository. It contains the package recipe, matching `.SRCINFO`, desktop launcher, icon, and license. Its checksums come from the exact Linux release archive. See [AUR packaging and submission](packaging/aur/README.md) for Arch validation and SSH submission. Generating these files does not publish the package to the AUR.

## Controls

- **Hold** `Ctrl+Win` to record; release either key to finish. The overlay hides on release, and the transcript is copied to the clipboard when transcription completes.
- **Toggle** `Ctrl+Shift+Space` to start/stop recording.
- **Remind**: hold `Ctrl+Alt+Space`, say a relative reminder command, then release to save it.
- The dashboard includes local Insights, a recognition dictionary, spoken snippets, output styles, and a Notetaker that captures the microphone and default speaker audio.
- Notetaker uses Voz and Align for word timestamps. Optional Who speaker labels, Clear audio cleanup, and Gist topic tags have separate controls on the Notetaker page.
- Meeting titles are suggested from the transcript and can be edited. Search matches titles, topics, and transcript text. Summaries and follow-up suggestions still use local sentence extraction rules.
- Double-click the system tray icon to open the dashboard. Search, copy, or delete transcripts in the dated history feed.
- System tray right-click → Start or stop dictation, Stop Notetaker, Open Neyra, Copy last transcript, Settings, or Quit.
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

The build script includes `assets/meeting-models` when present and excludes development toolchain installers. It bundles the installed Voz npm packages; Node.js remains a separate runtime requirement. Verify the native helper and packaged application on the target machine before distributing.

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
  startup.py  # per-user Windows and Linux login startup entries
  reminders.py # relative-time command parser and persistent reminders
  reminders_ui.py # reminder list, command entry, and notification fallback
  system_audio.py # default-speaker loopback capture for Notetaker
  text_tools.py # local speech cleanup and snippet expansion
pyproject.toml
```

The UI previews Whistle's `pending` text but only inserts committed transcription after recording ends. Voz returns its transcript after release and does not provide live previews in the JavaScript API. Its model download and transcription progress are reported by the worker. One-second audio blocks are streamed via a queue. All inference is off the GUI thread. Worker results and microphone levels reach the GUI through Qt signals. Audio streams are closed on failure and shutdown. Auto-paste waits for the shortcut modifiers to be released. There is no wake word, silence detection, or automatic timeout.

## Regression checks

```bash
uv run python -m unittest discover -s tests -v
```

These checks use isolated settings and simulated audio devices. They cover device selection, meter-test cleanup, recording controls, history retention and clearing, vocabulary corrections, login entries, and the Voz preload/subprocess protocol. Reminder checks cover spoken time parsing, shortcut isolation, persistent deadlines, timer delivery, cancellation, and shutdown before notification acknowledgment. They do not capture the microphone or system audio or send actual desktop notifications. Run `python packaging/aur/check_generator.py` separately for the portable AUR generator checks; Arch installation needs native validation.

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
