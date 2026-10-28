# Neyra — Your personal voice workspace

A local dictation dashboard and floating recording overlay for Windows 10/11, Linux, and Apple silicon Macs. Cactus Whistle recognizes English and shows live text every few seconds. Desert Ant Voz supports 25 languages and produces its transcript after recording stops. Both engines run on your CPU. X11 has the best Linux shortcut support; see the Wayland limitations below.

PC audio is muted while you record dictation, reminder commands, or assistant commands, and its previous mute state is restored when you stop. Disable **Mute PC audio while I speak** under **Voice settings → Microphone / models → Desktop**. Meeting recording and microphone testing keep PC audio available.

**Analytics**, beside Voice settings, shows statistics for saved dictations and meetings, plus ChatGPT tokens reported for the selected account's Neyra requests. Token tracking starts with this version and includes input/output tokens from intent recognition and assistant features; it does not include usage from other apps. Deleting saved notes changes the saved-note statistics. No transcripts or prompts are stored in token analytics.

Account controls show 5-hour and weekly quota availability. The supported ChatGPT sign-in flow does not expose those percentages to Neyra; use the account-limits link to see current plan usage in ChatGPT.

## Current state

Neyra opens to **Home**, with a compact capture bar, recent notes, upcoming
reminders, and quick actions. **Notes** contains dictations and meeting notes.
**Reminders** and **Assistant** have their own tabs. Open **Voice settings** for
microphone and model choices, Dictionary, Snippets, and Formatting.

Neyra is a useful local speech-to-text tool in an early state. Its default Needle Whistle model is small and uses very little RAM. Transcription results are usable, but not exceptional.

The optional Assistant connects your ChatGPT account for text explanations, questions over saved notes, and meeting action extraction. Speech recognition, desktop commands, reminders, and the daily agenda remain local.

Download the Windows, Linux, and Apple silicon macOS builds from the [latest release](https://github.com/creatorkostas/neyra/releases/latest). The macOS download is an unsigned `.app` bundle in a ZIP archive; see the macOS permissions below before opening it.

## Install with uv

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and use a supported Windows, Linux, or Apple silicon macOS system.

```bash
uv sync
uv run python -m neyra.main
```

This uses the Python 3.12 version specified in `.python-version`.

In **Voice settings**, choose **Whistle** for live text or **Voz** for a final transcript after recording stops. Selecting an engine loads its model in the background. Voz downloads about 1.2 GB on first use and caches the files locally. Its loaded model uses about 1.2 GB of RAM and at most four inference threads. Neyra keeps loaded models in memory until you quit.

The Home capture bar shows model loading and transcription status. Voz uses Python and ONNX Runtime, runs the encoder on the GPU through WebGPU (or CoreML on macOS), and needs no Node.js installation. Model weights download on first use. See [providers and Python Voz](docs/providers-and-python-voz.md) for setup, measured results, and current validation limits.

## Set up dictation

1. Open **Voice settings → Microphone** and select an input, or use **System default**. The same choice applies to Notetaker.
2. Click **Test microphone** and speak. The meter shows the input level; the test does not save audio. Stop the test when finished. Changing pages, closing the window, or starting a recording also stops the test.
3. Choose a speech model. Whistle starts loading when Neyra opens; selecting Voz starts its first download or loads its cached model.
4. Hold **Ctrl + Win** while another app has focus, then release to transcribe and paste. You can also use **Start dictation** on the dashboard. Dashboard recordings copy their result and appear in history without pasting back into Neyra.

If a selected microphone is disconnected, Neyra asks you to choose another input. **Refresh microphones** updates the list. Each device name includes its audio API to distinguish duplicate Windows entries.

## Customize shortcuts

Open **Voice settings → Shortcuts** to change all five keyboard combinations.
Type a combination such as `Ctrl+Alt+D`, then select **Apply shortcuts**. Changes
apply immediately and are remembered after restart. **Restore defaults** resets
the combinations. Finish recording and release the keys before applying changes.

Neyra rejects duplicate combinations and combinations contained inside another
Neyra shortcut. It warns about common system shortcuts, but cannot detect every
other app's bindings. Supported keys are Ctrl, Alt, Shift, Win, letters, digits,
Space, and F1–F12. Cmd, Meta, and Super are accepted aliases for Win. Native
Wayland still requires the desktop's own shortcut integration.

## Manage words and history

**Dictionary** stores recognition hints for Whistle. Voz does not support these hints. Under **Vocabulary corrections**, enter a misheard phrase and its intended spelling, then click **Save correction**. Corrections match whole words or phrases without case sensitivity and apply to new dictations from either engine. Select an existing row to update it or remove it. Corrections run before output formatting and snippet expansion. They do not change meeting words or timestamps.

Dictation history stays on this computer and retains the latest 500 entries. Search the feed, copy an entry, or delete it from its menu. **Clear history** asks for confirmation and removes saved dictations. Meeting notes are separate. Under **Voice settings → Local history**, turn off **Save new dictations to history** to stop saving new entries. Results still copy to your clipboard; this setting does not delete existing history or clear the system clipboard.

## Export notes and back up data

Choose **Notes → Export notes** to save all dictations and meetings as Markdown
or plain text. The export includes note dates, titles, and transcript text.

Under **Voice settings → Data**, choose **Create backup** for a JSON backup of
notes, reminders, vocabulary, snippets, agenda, shortcuts, and portable settings.
Backups contain personal text and are not encrypted. Keep them somewhere private.
ChatGPT credentials, custom executable paths, microphone selection, and login
startup settings are excluded and remain specific to the current computer.

**Restore backup** validates the whole file before asking to replace the included
data and preferences. Make a backup first if you want to keep the current data.
Restoring requires recordings and assistant requests to finish; Neyra quits after
a successful restore. Reopen it to load the restored data. Restore accepts version
1 Neyra backup files up to 64 MiB.

## Keep Neyra available

Enable **Voice settings → Start Neyra at login** to create a per-user startup entry. Windows uses Neyra's value in the current user's Run registry key; Linux uses `$XDG_CONFIG_HOME/autostart/neyra.desktop`, or `~/.config/autostart/neyra.desktop`. Turn the option off to remove Neyra's entry. Keep the app at the same location, or toggle the option off and on after moving it.

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

Open **Reminders** to type a command, use **Speak a reminder**, inspect scheduled times, or cancel a reminder. Delivered reminders move to **Recent reminders**, where **Dismiss** removes them. Reminder storage is independent of dictation history settings.

Each pending or delivered reminder has an **Actions** menu with **Snooze 10
minutes**, **Tomorrow 9AM**, and **Mark done**. Tomorrow means 9:00 in your local
time zone on the next calendar day. Snoozing schedules a new notification for
the same task. Done tasks appear separately and do not notify again. Receiving
a notification does not mark a task done. Neyra retains the latest 100 delivered
or done reminders together, plus all pending reminders.

Click a supported system tray notification to open Reminders. Fallback alerts
also offer **Open reminders**; notification systems without click support still
require opening the app to choose an action.

Keep Neyra running, including in the tray, for notifications at the scheduled time. Closed apps cannot notify; overdue reminders appear when you reopen Neyra. Windows and supported Linux trays use desktop notifications. Linux desktops without a tray can use `notify-send` from `libnotify`; if desktop notifications are unavailable or that command fails, Neyra opens a nonblocking reminder alert. Several reminders overdue at startup share one notification, and the full list remains in the dashboard.

## Use the assistant

Open **Assistant** in the sidebar. Its five tabs cover the following workflows:

1. **Commands:** hold **Ctrl + Alt + A**, speak, then release. Examples include "open calculator", "open browser", "volume up", "pause music", "next track", "set a timer for five minutes", and "daily briefing". These commands run locally. Add a spoken app name and choose its executable under **Assistant apps** to launch your own programs. Neyra never executes arbitrary shell commands from speech or AI output. Windows mute uses the system toggle key; Linux supports "unmute" as well.
2. **Selected text:** highlight text in another app and press **Ctrl + Alt + E**. Neyra copies it into a preview and restores the previous clipboard when it can identify one stable copy. Choose Explain, Summarize, or Translate, then **Send text to ChatGPT**. You can also paste text manually. Capture alone sends nothing online. This tool reads selected text. Screen questions use a separate, explicitly requested screenshot. The limit is 24,000 characters.
3. **Ask notes:** enter a question, choose **Find notes**, and review the matching passages. **Ask ChatGPT** sends the question and those passages. Answers request numbered source references. Search uses local word matching across dictation history and meeting transcripts, with up to six excerpts of 4,500 characters; it does not search arbitrary files. Voice questions search and answer automatically, without opening this page.
4. **Follow-ups:** choose a saved meeting and **Find tasks**. You can also open a meeting and choose **Plan follow-ups with Luna**. Neyra sends that transcript, up to 100,000 characters, and requires each returned task to include a verbatim supporting quote. Select a task, edit it if needed, choose a future date and time, and click **Create reminder**. Extraction alone schedules nothing. Manage saved tasks on **Reminders**.
5. **Briefing:** add plans to the local agenda, refresh today's briefing, or choose **Read aloud**. The briefing includes today's agenda and pending reminders due by tonight, including overdue ones. Agenda items do not create notifications. Use reminders for alerts. Speech playback uses local Piper and can be stopped. This agenda has no Google or Outlook calendar connection.

Assistant speech uses the selected local transcription engine and does not paste into another app or enter dictation history. Timers start when you release the command shortcut. Starting dictation or a meeting stops briefing playback.

### Connect ChatGPT

Click **Continue with ChatGPT** and complete the browser sign-in. Neyra uses OpenAI's documented [open-source ChatGPT sign-in flow](https://developers.openai.com/siwc/token-sharing-open-source/sign-in), with its own registration and a local callback. No API key or separately installed Codex CLI is needed. Your account must grant ChatGPT plan usage to Neyra.

**Spoken assistant answers:** replies requested through the assistant shortcut are read by local Piper sentence by sentence while ChatGPT is still responding. Disable **Read assistant answers aloud** under **Voice settings → Microphone / models → Assistant voice** to keep replies silent and use normal text formatting. Voice replies ask ChatGPT for brief spoken prose, without Markdown, code blocks, symbolic citations, or braces. Structured command routing and task extraction retain their JSON format; only answer text inside the routing response is streamed to speech. Incomplete responses are not cached or remembered, and queued speech is stopped on cancellation or a stream error. Starting a recording or choosing **Stop voice** interrupts playback.

Choose US English Lessac, British English Alan, or Greek Rapunzelina under **Voice settings → Assistant voice**. Preview the selected voice and set speed from **0.75× to 1.5×**. Voices download separately on first use with pinned checksums; the default Lessac voice is about 63 MB. Subsequent synthesis works offline. Supported English/Greek translations can automatically use a matching voice; other languages use your selected voice and may be pronounced poorly. The **Read aloud** button remains an explicit way to read the daily briefing. See [third-party notices](THIRD_PARTY_NOTICES.md) for Piper and voice licensing.

**Recent conversation:** Neyra remembers up to four completed request/answer pairs for 10 minutes, within a 12,000-character budget. This lets you say “make that shorter,” “translate that,” or “remind me in an hour to do that.” Memory is account-specific, stays in RAM, and is cleared on account changes, sign-out, or shutdown. Say **“forget our conversation”**, choose **Clear conversation**, or disable **Remember recent conversation** under **Voice settings → Assistant voice**. Editing a note-search question does not erase the conversation.

**Screen questions:** say “based on what I see on the screen…” or “what am I looking at?” while using the assistant shortcut. Neyra captures the display under your pointer, hides its floating overlay, and sends one image with that question to ChatGPT. It does not capture all monitors or continuously watch the screen. The JPEG is limited to a 1920-pixel long edge and 4 MB, stays in memory, and is not saved in history or the response cache. The answer may be kept as text in recent conversation. To ask about a changed screen, make a new screen request. Capture needs desktop permission; Wayland or macOS sessions may deny it. Images can use additional account tokens.

**Floating status:** the recording overlay stays visible through **Listening → Thinking → Speaking**. **Cancel** discards recorded assistant speech or cancels a pending request; **Stop** interrupts playback. Pressing the assistant shortcut stops current speech and starts listening without waiting for an old ChatGPT connection to close. Late text and results from the cancelled turn are discarded. Cancelled native transcription may finish in the background, but its result is discarded and is never sent to ChatGPT.

To reduce repeated requests, completed text explanations, translations, note answers, and meeting-task suggestions are reused for up to 10 minutes when the account, instructions, input, and output budget match exactly. This bounded cache lives only in memory and is cleared on account changes, sign-out, note-source invalidation, and shutdown. Cancelled or failed results and voice intent commands are not cached. A reused result makes no new ChatGPT request.

Requests keep stable instructions first, put source passages before changing questions, and use task-specific output limits. Provider prompt caching is automatic where eligible; Neyra uses an opaque per-account cache key and leaves default cache retention unchanged. Analytics shows provider-reported cached input tokens as part of input tokens, never as extra tokens or a quota discount. Cache hits are not guaranteed, and cached input still counts toward token rate limits.

With a connected ChatGPT account, you can speak naturally: “Could you shorten the text I highlighted?” or “What does my day look like?” Familiar commands run locally; other requests use ChatGPT to identify a supported action. Neyra sends the spoken request, basic workflow state, and recent request/answer text when conversation memory is enabled. Raw note bodies, selected text, and executable paths are excluded from routing; requested tool context is sent to the tool itself. Missing essential details prompt a spoken question. Voice requests automatically run the requested tool and speak its result; typed requests retain their previews. Suggested tasks create reminders only when you ask for a task and a time. Without a connected account, use the commands below.

The **assistant command shortcut** (Ctrl + Alt + A by default) is the main interaction: hold it, speak naturally, then release. Neyra runs the required tool and speaks back without opening the dashboard or asking you to press Send. Ordinary questions receive a conversational answer; voice requests for selected text, saved notes, and meetings authorize sending that requested context. Examples:

- **Selected text:** say “summarize selected text,” “explain selection,” or “translate selection into Greek.” Neyra captures the selection, sends it to ChatGPT, and speaks the result automatically. Keep the source app focused. Where automatic capture is blocked, copy the text and say “summarize clipboard.”
- **Ask notes:** ask about your saved notes, for example “What did my notes say about the launch?” Neyra searches matching excerpts, asks ChatGPT, and speaks the answer automatically.
- **Follow-ups:** ask for tasks from the latest meeting or name a meeting. Neyra extracts and reads them automatically. Say “schedule task one in an hour” to save a reminder. Tasks are numbered; existing reminders are not duplicated.
- **Today:** say “daily briefing,” “show today,” or “stop reading.” Add a plan with “add a plan in an hour to call Alex” and remove it with “remove plan one.” Plan numbers appear under Edit plans. Plans do not send notifications; use “remind me in an hour to call Alex” for a notification.

AI requests use exactly **`gpt-6-luna` with low reasoning effort**. Neyra does not substitute another model. A successful request verifies whether your selected account can use Luna; signing in alone does not prove model access. Internet access and ChatGPT plan availability are required, and account usage limits apply. Use **Account limits** to open ChatGPT's usage controls. See [ChatGPT plan inference](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference) and [Luna model settings](https://developers.openai.com/api/docs/models/gpt-6-luna).

The account picker supports saved accounts and adding another account. **Sign out** attempts to revoke the selected session and clears its local tokens. If remote revocation cannot be confirmed, Neyra says so; disconnect it in ChatGPT Settings. Account mappings remain so later sign-ins can reuse their registration.

Credentials are stored outside the project under Qt's user configuration location in `Neyra/chatgpt`. Windows protects the credential file with the current user's DPAPI; Unix uses an owner-only directory and file. Requests set `store: false`. Audio is never sent to ChatGPT. AI receives the spoken request, enabled recent conversation context, and any selected text, matching note excerpts, meeting transcript, or explicitly requested screen snapshot needed for your question. Voice requests send that context automatically; typed requests retain a preview. AI answers can still be wrong, so inspect the cited passages and proposed tasks.

### Linux assistant dependencies

Commands and the dashboard work on Linux. Install `playerctl` for media playback commands and `wpctl` from WirePlumber, or `pactl`, for volume commands. Piper speech is bundled. Its English voice downloads once on first use; playback uses the default output device. If playback is unavailable, answers and briefings remain readable.

On native Wayland, use **Speak command** in Assistant and copy text manually into the preview. Global keyboard hooks and simulated copy are subject to the same desktop restrictions as dictation.

## Build with Nuitka (offline model included)

```bash
uv sync --extra build
uv run python scripts/build.py --onefile
```

The build script bundles the Whistle and Needle 3 weights plus their native engine. Python ONNX Runtime replaces the former Voz Node packages. Voz model weights remain a first-use download.

At startup, Neyra sets `NEEDLE_WHISTLE_WEIGHTS`, `NEEDLE3_LIB_PATH`, and `HF_HUB_OFFLINE=1` for the bundled Whistle assets. Whistle should not download weights in a packaged build. Voz and the optional meeting models still download their own assets on first use.

For easier debugging first build a folder distribution:

```bash
uv run python scripts/build.py --standalone
```

Build on Windows to produce `dist/Neyra.exe`, on Linux to produce `dist/Neyra`, and on Apple silicon macOS to produce `dist/Neyra.app`. Nuitka does not cross-compile. macOS builds are not signed or notarized, so Gatekeeper may require you to approve opening the downloaded app in **System Settings → Privacy & Security**. macOS may also ask you to grant microphone access and Accessibility access for global shortcuts. The executable is self-extracting, not a fully static binary; Linux still needs compatible system libraries and a display server.

For macOS release packages, use `uv run python scripts/build.py --standalone`.
The workflow packages the resulting self-contained `Neyra.app` directory as a zip.
Windows and Linux release packages use `--onefile`.

**Packaging caveat:** Cactus's fetched engine layout may change, and some distributions may contain multiple libraries. The build deliberately fails instead of silently falling back to online downloads. If `NEEDLE3_LIB_PATH` is ignored by a future Cactus release or native dependencies are missing, verify against that release and adjust the packaging.

## Publish a release

Push a version tag such as `v0.1.0` to build the Windows, Linux, and Apple silicon macOS packages and publish them as GitHub release assets. The workflow also builds all three on pushes to `main`.

Pull requests also build all three packages so native packaging errors can be
caught before merging. The checks workflow imports the installed Voz and ONNX
runtime to check their bridge APIs without downloading model weights.

Tagged releases also attach `neyra-bin-VERSION-aur.tar.gz`, a submission archive for the Arch User Repository. It contains the package recipe, matching `.SRCINFO`, desktop launcher, icon, and license. Its checksums come from the exact Linux release archive. See [AUR packaging and submission](packaging/aur/README.md) for Arch validation and SSH submission. Generating these files does not publish the package to the AUR.

## Default controls

- **Hold** `Ctrl+Win` to record; release either key to finish. The overlay hides on release, and the transcript is copied to the clipboard when transcription completes.
- **Toggle** `Ctrl+Shift+Space` to start/stop recording.
- **Remind**: hold `Ctrl+Alt+Space`, say a relative reminder command, then release to save it.
- **Assistant**: hold `Ctrl+Alt+A`, speak a command, then release.
- **Selected text**: press `Ctrl+Alt+E` to capture a selection for review before sending it to ChatGPT.
- The dashboard includes local Insights, a recognition dictionary, spoken snippets, output styles, and a Notetaker that captures the microphone and default speaker audio.
- Notetaker uses Voz and Align for word timestamps. Optional Who speaker labels, Clear audio cleanup, and Gist topic tags have separate controls on the Notetaker page.
- Meeting titles are suggested from the transcript and can be edited. Search matches titles, topics, and transcript text. Summaries and follow-up suggestions still use local sentence extraction rules.
- Double-click the system tray icon to open the dashboard. Search, copy, or delete transcripts in the dated history feed.
- System tray right-click → Start or stop dictation, Stop Notetaker, Open Neyra, Copy last transcript, Settings, or Quit.
- Drag the widget by holding the left mouse button.

Global shortcuts work through `pynput` on Windows and X11. They are **not** generally supported by pynput on native Wayland. For Wayland, use the tray menu or set up compositor-specific bindings / a desktop portal integration in a later iteration. Tray visibility also depends on the desktop environment.

## Set up meeting models

Build the native meeting helper with the setup script:

```powershell
uv run python scripts/setup_meeting_models.py
```

The helper uses the Desert Ant Swift SDK for Windows support. See [meeting runtime setup](runtime/meeting-models/README.md) for the Swift toolchain, C++ tools, and build options. The executable and its runtime libraries belong in `assets/meeting-models`. Set `NEYRA_MEETING_MODELS` to an absolute executable path to use another location.

Under **Notes → Meetings**:

- Enable **Speaker labels** to label turns with Who. Labels are numbers, not identified names. Overlapping turns can show multiple speakers.
- Enable **Clean audio** to run Clear before transcription. Clear reduces noise and echo, but also suppresses music and other non-speech sound.
- Enable **Organize notes** to suggest a title and add Gist topic tags. **Save title** updates a meeting title. Desert Ant Title is not used because its SDK requires Apple silicon.
- Choose **Meeting language** for Align. The supported languages are English, Spanish, French, Italian, Portuguese, German, Japanese, Korean, and Chinese. Voz detects the spoken language independently.

These settings apply to new recordings. Speaker labels and audio cleanup default to off; organization defaults to on. Meetings always use Voz followed by Align, independently of the dictation engine. Meeting transcripts preserve the recognized words instead of applying dictation styles or expanding snippets, which would break their timestamp correspondence.

Open a meeting to see its timestamped transcript and **Word timestamps** tab. The start and end cells indicate whether Align refined that boundary or kept Voz's timing. **Copy transcript** includes timestamps and enabled speaker labels. The meeting card menu also offers **Copy plain text**.

Model weights download on first use and are cached by the SDK. The native SDK also contacts Desert Ant for license activation. Audio processing runs locally. See the runtime guide for network and licensing details.

A failed processing attempt keeps the mixed recording in memory for **Retry processing**. You can disable an optional model before retrying, or choose **Discard recording**. Closing Neyra discards that unsaved recording. Successful processing removes temporary audio files; existing saved notes cannot be reprocessed without their audio.

The build script includes `assets/meeting-models` when present and excludes development toolchain installers. Voz now uses Python ONNX Runtime and needs no Node.js installation. Verify the native helper and packaged application on the target machine before distributing.

## Text insertion

- The transcript is copied to the clipboard and automatically pasted into the focused application when recording finishes.
- On Wayland, `wl-copy` + `wtype` are attempted if installed and allowed by the compositor. Otherwise use **Copy last transcript** in the tray.
- The overlay is non-focusable to preserve the target text field, but paste delivery is best-effort. Some elevated apps, secure inputs, games and Wayland sessions block it. The clipboard is intentionally **not restored** because restoring it too early can race with the target application.
- Avoid dictating sensitive information into the wrong focused field. The MVP does not inspect or filter password fields.

## Architecture

Read the [short architecture guide](docs/architecture.md) for runtime flow,
module ownership, and boundaries to preserve. See [CONTRIBUTING.md](CONTRIBUTING.md)
for development setup, PR checks, dependency updates, and the release process.

```
neyra/
  main.py     # PySide6 overlay, tray, session lifecycle
  audio.py    # sounddevice microphone, 16 kHz mono float32
  stt.py      # Whistle live windows and optional Voz transcription on background threads
  hotkeys.py  # hold and toggle chords (Windows/X11)
  desktop.py  # best-effort cross-platform paste
  startup.py  # per-user Windows and Linux login startup entries
  reminders.py # relative-time parser, reviewed deadlines, and persistent reminders
  reminders_ui.py # reminder list, command entry, and notification fallback
  assistant_ui.py # commands, text preview, note search, follow-ups, and briefing tabs
  assistant_features.py # assistant UI wiring, background requests, and speech playback
  assistant_tools.py # bounded desktop actions, source selection, and local agenda
  chatgpt.py # Neyra-owned OAuth accounts and Luna Responses streaming
  system_audio.py # default-speaker loopback capture for Notetaker
  text_tools.py # local speech cleanup and snippet expansion
pyproject.toml
```

Whistle transcribes audio in windows of at most 5.12 seconds and shows their text as it commits, but only inserts committed transcription after recording ends. The native encoder is about seven times slower per second of audio past that window, and the streaming call re-encodes the audio it keeps on every pass, so windowing keeps a long dictation faster than real time; a window also ends inside a sustained pause so a cut rarely splits a word. Voz returns its transcript after release and does not provide live previews in the JavaScript API. Its model download and transcription progress are reported by the worker. Quarter-second audio blocks are streamed via a queue. All inference is off the GUI thread. Worker results and microphone levels reach the GUI through Qt signals. Audio streams are closed on failure and shutdown. Auto-paste waits for the shortcut modifiers to be released. There is no wake word, no automatic stop on silence, and no timeout.

## Regression checks

```bash
uv run python -m unittest discover -s tests -v
```

These checks use isolated settings and simulated audio devices. They cover device selection, meter-test cleanup, recording controls, history retention and clearing, vocabulary corrections, login entries, and the Voz preload/subprocess protocol. Reminder checks cover spoken time parsing, shortcut isolation, persistent deadlines, timer delivery, cancellation, and shutdown before notification acknowledgment. They do not capture the microphone or system audio or send actual desktop notifications. Run `python packaging/aur/check_generator.py` separately for the portable AUR generator checks; Arch installation needs native validation.

Assistant checks cover command restrictions, clipboard preservation, reviewed source sharing, grounded action extraction, explicit reminder creation, and local agenda persistence. ChatGPT tests use a real loopback callback with mocked provider endpoints, signed synthetic ID tokens, credential protection, refresh locking, and simulated response streams. They do not sign into a real account or consume ChatGPT usage. Test actual login, model access, desktop shortcuts, and speaker playback on your target machine.

## Troubleshooting

- **Model errors:** test `needle whistle playground` for Whistle. For Voz, run `uv sync --locked` and allow internet access for its first model download, or configure `NEYRA_VOZ_MODEL_DIR`.
- **Voz runs on the CPU:** check the loading message for the provider. `NEYRA_VOZ_DEVICE=gpu` forces acceleration; see [execution providers](docs/providers-and-python-voz.md) for driver requirements and `scripts/benchmark_voz.py`.
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

## Providers, themes, and local tools

Voice settings now includes an Appearance button and assistant provider controls.
Choose ChatGPT, a local compatible model server, OpenCode API, OpenCode CLI, or
no assistant. Natural-language tool routing uses local Needle 3 independently.
See [setup and runtime details](docs/providers-and-python-voz.md).
