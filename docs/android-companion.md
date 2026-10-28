# Android companion

Build/install the app from https://github.com/creatorkostas/neyra-android.
Install desktop dependencies with `uv sync --locked --extra companion`.
Open **Android companion** on Home, **Open Android companion** in Voice settings,
or the tray action. Enable the service and scan its QR from Computers on Android.
QR invitations expire after five minutes and work once. Generate another if needed.
Manual fingerprint/token pairing remains available below the code.

Keep both devices on the same trusted LAN. Allow Neyra through the private-network
firewall; no public forwarding is needed. Discovery uses UDP 5353 and HTTPS uses
an available TCP port. The service is opt-in for each Neyra session; certificate
and paired tokens persist. Disconnect all phones revokes tokens and invitations.

The phone records PCM audio locally (up to 60 seconds) and your selected desktop
Whistle/Voz engine transcribes it. Review the transcript before sending, or choose
Queue as note to authorize later transcription and note saving. Desktop recording
is blocked during phone inference. Cancelled native inference may finish, with its
result discarded. Remote notes never paste into the focused application.

Conversation mode uses the desktop's configured provider and sends only the
phone request and bounded recent phone conversation, not desktop screen, clipboard,
notes or files. Replies appear on the phone and use its installed offline TTS voice.
Conversation replies never execute tools. Commands mode retains local app/media/
reminder/briefing actions. Follow-up context is per phone/account, expires after
ten minutes, retains four pairs, and is memory-only. Clear/Stop are available.

The Android outbox persists notes/recordings for their original computer and
retries after reconnection. Stable request IDs and desktop receipt/history metadata
prevent ordinary reconnect/restart duplicates. The journal retains 2,000 receipts;
there is no guarantee beyond receipt/history retention. Recordings disappear after
successful save or explicit discard/delete. Phone search caches bounded recent
note excerpts; deleting a pair clears its cache/outbox.

Reminders support daily (24h) or weekly (7-day) fixed cadence. Delivery or early
completion creates one next future occurrence. Missed intervals are skipped.
Stop repeating cancels later pending occurrences; a selected pending occurrence
remains once. Recurrence is owned by the desktop. Inexact phone alarms and periodic
background sync may be delayed by Android, and disconnected phones can retain
stale reminders until sync. Notification actions wait for a network and validate
the original deadline. There is no away-from-home relay or arbitrary system
notification mirroring.

Credentials and TLS identity live in the user's application-data companion folder,
excluded from backups. Keep pairing tokens/QRs private. Phone deletion only forgets
local state; desktop revocation invalidates credentials. Speech/camera, installed
phone voices, widget behavior and battery/Doze delivery need physical-device checks.
