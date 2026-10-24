# Neyra workspace identity

Neyra is a personal voice workspace. The message is "Capture a thought.
Remember what matters." The app and static website share a rounded waveform mark, cool
white surfaces, cool blue actions, and compact navigation.

## Tokens

- Background: `#f5f6f9`; foreground: `#171e31`; secondary text: `#53596b`.
- Primary action: `#365bd6`; quiet surface: `#e6e9f1`; border: `#d7dae3`.
- Voice indicator: deep blue `#171f37` with pale blue `#9dacda`.
- Media radius: 10px; buttons: 8px. Avoid a large rounded container around the app.
- Website type: self-hosted Manrope. Body text is 16px with 1.65 line height.
  The display title caps at 74px and wraps naturally.

## Structure and behavior

The website leads with the purpose, downloads, and an illustrative note preview.
The ring appears before the resulting note to explain the voice-to-text flow.
The real Home screenshot uses synthetic content and carries a development label.
Later sections cover assistant workflows, limitations, downloads, and setup.

The app uses top navigation for Home, Notes, Reminders, and Assistant. Home
shows capture, recent notes, and upcoming reminders. Voice settings groups
dictionary, snippets, formatting, microphone, models, and usage.

The ring responds to real microphone levels in the app. It has no idle loop.
The website ring animates only during a requested text preview, and stops when
the tab is hidden. Keyboard and reduced-motion activation complete immediately.
Pointer press feedback is subtle. Focus states keep their geometry stable.

## Maintenance

Keep keyboard focus visible and touch controls at least 44px tall on the site.
Check the site at 320px, 390px, and desktop widths. Check desktop pages at
1000×640 and 1340×840 with long device names and account labels.

Preserve development labels until releases include the shown features. The
site requests no microphone access. Keep it static and keep downloads usable
when the release API cannot be reached.
