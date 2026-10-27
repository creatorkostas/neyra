# Android companion

Build/install the app from https://github.com/creatorkostas/neyra-android.
Install desktop dependencies with `uv sync --locked --extra companion`.
Open Android companion from Neyra's tray or Voice settings → Data & backup.
Enable the service, then select this computer under Computers on the phone.
Copy the full certificate fingerprint and generated phone token from the desktop
window. Verify the fingerprint there. Each click on Add a phone creates a new
independent credential. Disconnect all phones revokes all credentials and stops
the service. It must be enabled again after Neyra restarts.

Keep both devices on the same trusted network. Allow Neyra through the private
network firewall if needed; no public port forwarding is needed. Discovery uses
UDP 5353 and the encrypted service chooses an available TCP port.

The phone can save notes when desktop history is enabled, create relative-time
reminders, send supported local app/media/reminder/briefing commands, and sync,
complete or snooze reminders. Remote requests never paste into another app or
implicitly share desktop screen/clipboard context. Phone speech uses Android's
speech service, which may contact its provider despite the offline preference.
Assistant replies remain on the computer.

Foreground phone sync runs about every five seconds; background sync is periodic
and may be delayed. Already synced reminders schedule inexact phone alerts, even
when disconnected; later desktop edits/cancellations require reconnection. No
away-from-home delivery or arbitrary desktop notification mirroring is included.

Credentials and the TLS key/certificate live in the user's application data
companion directory, outside backups and the repository. Treat generated phone
tokens as private credentials. Revocation on desktop is required to invalidate
a phone; deleting it on Android only forgets local state. Copy-based enrollment
and revoke-all are initial controls; QR enrollment and individual revocation
are future work. This is an early implementation requiring real-device testing.
