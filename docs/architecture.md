# Neyra architecture

Neyra is a PySide6 desktop application. Local speech engines process recordings;
optional ChatGPT features receive text only after the user requests it.

## Runtime flow

`run_neyra.py` starts `neyra.main`. The `Assistant` controller owns recording
state, the tray, hotkeys, and shutdown. The dashboard and floating overlay run
on the Qt GUI thread. Audio capture and inference run in workers and report
results through queues and Qt signals.

`home_ui.py` presents the Home overview and emits navigation and action signals.
The existing controllers handle recording and reminders. The top navigation
groups dictation history and meetings under Notes, and speech preferences under
Voice settings. Home refreshes when notes or reminder delivery state changes.

Dictation flows from `audio.py` into `stt.py`, through local text formatting in
`text_tools.py`, and then into history and clipboard output. `desktop.py`
handles pasting into the focused application. Reminder and assistant recording
modes route the transcript to their own handlers instead of pasting it.

Assistant commands first use the bounded local parser. With a connected ChatGPT
account, unrecognized requests use a cancellable intent job. The model returns
one canonical command or a clarification; schema validation and the same local
parser gate dispatch. Intent context excludes note bodies, selected text, and
executable paths. Interpretation never grants arbitrary code or shell access.

## Module ownership

| Area | Files | Responsibility |
| --- | --- | --- |
| App lifecycle | `main.py`, `ui.py` | Recording modes, dashboard, overlay, tray, and shutdown |
| Speech | `speech.py`, `audio.py`, `stt.py`, `bundled.py`, `voz_transcribe.mjs` | Microphone capture, speech workers, bundled models, and the Voz subprocess |
| Desktop integration | `hotkeys.py`, `shortcuts.py`, `desktop.py`, `speaker_mute.py`, `startup.py` | Validated shortcut preferences and global key events, clipboard/paste, and supported login startup entries |
| Reminders | `reminders.py`, `reminders_ui.py` | Time parsing, persistence, scheduling, and notifications |
| Assistant | `assistant_tools.py`, `assistant_features.py`, `assistant_ui.py` | Bounded local commands, reviewed context, background jobs, and assistant panels |
| ChatGPT | `chatgpt.py` | Neyra-owned OAuth accounts, credential storage, streamed responses, and reported token-usage capture |
| Result reuse | `response_cache.py` | Bounded, account-scoped, short-lived in-memory reuse of completed read-only assistant results |
| Analytics | `analytics.py` | Local per-account token counters and saved-note statistics; no note text in token storage |
| Data preferences | `preferences_ui.py`, `data_transfer.py` | Shortcut editing, note export, portable backup validation, and atomic file writes |
| Meeting notes | `system_audio.py`, `meeting.py`, `runtime/meeting-models/` | Loopback capture, native helper protocol, timestamps, and optional meeting models |
| Distribution | `scripts/`, `.github/workflows/`, `packaging/aur/` | Native builds, package validation, release publication, and AUR recipe generation |
| Website | `website/` | Static GitHub Pages site; no desktop runtime dependencies |

All Python files in this table live under `neyra/` unless another path is shown.

## Boundaries to preserve

- Piper synthesis and playback use a cancellable worker with pinned first-use
  voice downloads. A new recording stops playback. Spoken response instructions
  apply to user-facing prose, never to the structured command or task protocols.
- Keep blocking audio, model, network, and subprocess work off the GUI thread.
  Send UI updates through Qt signals.
- Keep parsing and local actions in domain modules. UI panels collect inputs;
  controllers coordinate jobs and state transitions.
- A spoken tool request authorizes automatic processing of its selected text,
  matching saved-note excerpts, or chosen meeting. Voice flows stay headless and
  speak results; typed flows retain previews. The intent router may return a
  conversational answer, a bounded command, or a clarification. Creating a
  reminder from an extracted task still requires the user to specify a task/time.
- Record token usage against the account that supplied the request token. Keep
  local Neyra token counts separate from account-wide quotas; unavailable quota
  percentages must never be estimated from token totals.
- Store user data and credentials outside the repository. Use isolated settings
  and synthetic transcripts in tests.
- Backup files include an explicit allowlist of portable data, excluding tokens,
  executable paths, and device configuration. Validate every field before
  restoring; restore quits the app to prevent stale controllers overwriting data.
- Keep delivered and done reminder states separate. A delayed notification
  acknowledgment must match the original deadline before changing a reminder.
- Temporary speaker muting runs outside the GUI thread, restores the original
  output state on stop, failure, and shutdown, and excludes meeting loopback capture.
- Close streams and subprocesses during failure and shutdown. Preserve the
  distinction between dictation, reminder commands, and assistant commands.

Read [CONTRIBUTING.md](../CONTRIBUTING.md) for setup and verification commands.
Update this guide when module ownership or runtime flow changes.
