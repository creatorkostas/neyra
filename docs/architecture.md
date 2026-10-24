# Neyra architecture

Neyra is a PySide6 desktop application. Local speech engines process recordings;
optional ChatGPT features receive text only after the user requests it.

## Runtime flow

`run_neyra.py` starts `neyra.main`. The `Assistant` controller owns recording
state, the tray, hotkeys, and shutdown. The dashboard and floating overlay run
on the Qt GUI thread. Audio capture and inference run in workers and report
results through queues and Qt signals.

Dictation flows from `audio.py` into `stt.py`, through local text formatting in
`text_tools.py`, and then into history and clipboard output. `desktop.py`
handles pasting into the focused application. Reminder and assistant recording
modes route the transcript to their own handlers instead of pasting it.

## Module ownership

| Area | Files | Responsibility |
| --- | --- | --- |
| App lifecycle | `main.py`, `ui.py` | Recording modes, dashboard, overlay, tray, and shutdown |
| Speech | `audio.py`, `stt.py`, `bundled.py`, `voz_transcribe.mjs` | Microphone capture, speech workers, bundled models, and the Voz subprocess |
| Desktop integration | `hotkeys.py`, `desktop.py`, `startup.py` | Global shortcuts, clipboard/paste, and supported login startup entries |
| Reminders | `reminders.py`, `reminders_ui.py` | Time parsing, persistence, scheduling, and notifications |
| Assistant | `assistant_tools.py`, `assistant_features.py`, `assistant_ui.py` | Bounded local commands, reviewed context, background jobs, and assistant panels |
| ChatGPT | `chatgpt.py` | Neyra-owned OAuth accounts, credential storage, and streamed responses |
| Meeting notes | `system_audio.py`, `meeting.py`, `runtime/meeting-models/` | Loopback capture, native helper protocol, timestamps, and optional meeting models |
| Distribution | `scripts/`, `.github/workflows/`, `packaging/aur/` | Native builds, package validation, release publication, and AUR recipe generation |
| Website | `website/` | Static GitHub Pages site; no desktop runtime dependencies |

All Python files in this table live under `neyra/` unless another path is shown.

## Boundaries to preserve

- Keep blocking audio, model, network, and subprocess work off the GUI thread.
  Send UI updates through Qt signals.
- Keep parsing and local actions in domain modules. UI panels collect inputs;
  controllers coordinate jobs and state transitions.
- Keep AI context sharing explicit. Show selected text or note excerpts before
  sending them, and require review before turning extracted tasks into reminders.
- Store user data and credentials outside the repository. Use isolated settings
  and synthetic transcripts in tests.
- Close streams and subprocesses during failure and shutdown. Preserve the
  distinction between dictation, reminder commands, and assistant commands.

Read [CONTRIBUTING.md](../CONTRIBUTING.md) for setup and verification commands.
Update this guide when module ownership or runtime flow changes.
