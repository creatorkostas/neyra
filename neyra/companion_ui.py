"""Qt adapter for the opt-in companion; only this module touches desktop state."""
import queue
import hashlib
import json
import io
import threading
from pathlib import Path
from PySide6.QtCore import QObject, QStandardPaths, QTimer, Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QPlainTextEdit
from .companion import CompanionServer


class CompanionController(QObject):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.server = None
        self.requests = queue.Queue(maxsize=8)
        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self.drain)
        self.dialog = None
        self.jobs = None

    def dispatch(self, path, body):
        event = threading.Event()
        item = {'path': path, 'body': body, 'event': event, 'cancelled': False}
        try:
            self.requests.put_nowait(item)
        except queue.Full:
            raise ValueError('Desktop is busy. Try again.') from None
        if not event.wait(8):
            item['cancelled'] = True
            raise TimeoutError()
        if 'error' in item:
            raise ValueError(item['error'])
        return item['result']

    def drain(self):
        for _ in range(8):
            try:
                item = self.requests.get_nowait()
            except queue.Empty:
                return
            if item['cancelled']:
                continue
            try:
                item['result'] = self.handle(item['path'], item['body'])
            except (ValueError, OSError) as exc:
                item['error'] = str(exc)
            finally:
                item['event'].set()

    def snapshot(self):
        return {'machineId': self.server.machine_id, 'name': self.server.name,
                'reminders': [dict(record) for record in self.owner.reminder_store.records],
                'notes': self.notes()}

    def notes(self):
        notes, size = [], 0
        records = list(getattr(self.owner.history, 'records', [])) + list(getattr(self.owner.history, 'meeting_records', []))
        for record in sorted(records, key=lambda r: r.get('time', ''), reverse=True)[:200]:
            text = record.get('text', '')[:8000]
            note = {'id': hashlib.sha256((record.get('time', '') + text).encode()).hexdigest(),
                    'text': text, 'time': record.get('time', ''), 'title': record.get('title', '')}
            size += len(json.dumps(note, ensure_ascii=False).encode())
            if size > 800_000:
                break
            notes.append(note)
        return notes

    def handle(self, path, body):
        if self.owner.closing or self.server is None:
            raise ValueError('Neyra is closing.')
        if path in ('/v1/transcribe', '/v1/chat', '/v1/job', '/v1/forget'):
            if self.jobs is None:
                from .companion_jobs import CompanionJobs
                self.jobs = CompanionJobs(self.owner)
            if path == '/v1/job':
                return self.jobs.status(body)
            if path == '/v1/forget':
                return self.jobs.forget(body.get('_peer', ''))
            return self.jobs.create('transcribe' if path == '/v1/transcribe' else 'chat', body)
        if path == '/v1/snapshot':
            return self.snapshot()
        if path == '/v1/capture':
            text = body.get('text')
            if not isinstance(text, str) or not 1 <= len(text.strip()) <= 8000:
                raise ValueError('Enter between 1 and 8,000 characters.')
            mode = body.get('mode')
            remote_key = hashlib.sha256((body.get('_peer', '') + ':' + body['requestId']).encode()).hexdigest() if body.get('requestId') else None
            if mode == 'NOTE':
                if not self.owner.history.save_history_toggle.isChecked():
                    raise ValueError('Enable desktop note history before saving a remote note.')
                if remote_key:
                    self.owner.history.add_transcript(text.strip(), remote_key=remote_key)
                else:
                    self.owner.history.add_transcript(text.strip())
                return {'message': 'Note saved on this computer.'}
            if mode == 'REMINDER':
                repeat = body.get('repeatSeconds', 0)
                if repeat not in (0, 86400, 604800) or isinstance(repeat, bool):
                    raise ValueError('Choose once, daily, or weekly.')
                record = self.owner.reminder_store.add(text.strip(), source_key='companion:' + remote_key if remote_key else None)
                self.owner.reminder_store.set_repeat(record['id'], repeat)
                self.owner.history.reminders.refresh(self.owner.reminder_store.records)
                self.owner.check_reminders()
                return {'message': 'Reminder saved. Refresh Inbox to sync it.'}
            if mode == 'ASSISTANT':
                # Remote requests may run bounded local commands, but never
                # implicitly read the focused app, screen, clipboard, or files.
                from .assistant_tools import parse_command
                action, _ = parse_command(text.strip())
                if action not in {'reminder', 'media', 'open', 'briefing'}:
                    raise ValueError('This command needs desktop context. Use it on the computer.')
                if self.owner.assistant_features.job.running:
                    raise ValueError('Desktop assistant is busy.')
                self.owner.assistant_features.command(text.strip(), use_ai=False, spoken=False)
                return {'message': 'Command sent to the desktop. Check the computer for its result.'}
            raise ValueError('Unknown capture mode.')
        if path == '/v1/reminder':
            record = next((r for r in self.owner.reminder_store.records if r['id'] == body.get('id')), None)
            if not record or int(record['due_at'] * 1000) != body.get('due_ms'):
                raise ValueError('Reminder changed. Refresh before trying again.')
            if body.get('action') == 'done':
                self.owner.reminder_store.complete(record['id'])
            elif body.get('action') == 'stop_repeat':
                self.owner.reminder_store.stop_repeating(record['id'])
            elif body.get('action') == 'snooze':
                from .reminders import snooze_deadline
                self.owner.reminder_store.snooze(record['id'], snooze_deadline('10min'))
            else:
                raise ValueError('Unknown reminder action.')
            self.owner._reminders_in_flight.discard(record['id'])
            self.owner.history.reminders.refresh(self.owner.reminder_store.records)
            return self.snapshot()
        raise ValueError('Unknown operation.')

    def show(self):
        if self.dialog:
            self.dialog.show()
            self.dialog.raise_()
            return
        self.dialog = QDialog(self.owner.history)
        self.dialog.setWindowTitle('Android companion')
        self.dialog.resize(760, 800)
        layout = QVBoxLayout(self.dialog)
        status = QLabel('Connect your Android phone on the same trusted local network.\nEnable starts an encrypted LAN service until Neyra quits. Ports are chosen automatically.')
        status.setWordWrap(True)
        layout.addWidget(status)
        qr = QLabel("Enable companion to generate a five-minute pairing QR code.")
        qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(qr)
        details = QPlainTextEdit()
        details.setReadOnly(True)
        layout.addWidget(details)
        enable = QPushButton('Enable companion and add a phone')
        layout.addWidget(enable)
        revoke = QPushButton('Disconnect all phones and stop companion')
        layout.addWidget(revoke)

        def start():
            enable.setEnabled(False)
            status.setText('Starting companion…')
            existing = self.server
            def worker():
                server = existing
                try:
                    directory = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)) / 'companion'
                    if server is None:
                        server = CompanionServer(directory, self.dispatch)
                        server.start()
                    token = server.new_phone_token()
                    result = (server, token, None)
                except Exception as exc:
                    if server and server is not existing:
                        server.close()
                    result = (None, None, str(exc))
                self.start_result = result
            # Poll completion on Qt; no UI or QSettings access in worker.
            self.start_result = None
            threading.Thread(target=worker, daemon=True, name='companion-start').start()
            poll.start()

        def display(server, token):
            import qrcode
            invite = server.new_invite()
            payload = json.dumps({'type': 'neyra-pair-v1', 'id': server.machine_id, 'name': server.name,
                                  'host': server.addresses[0], 'port': server.port,
                                  'fingerprint': server.fingerprint, 'invite': invite}, separators=(',', ':'))
            output = io.BytesIO()
            qrcode.make(payload).save(output, format='PNG')
            qr.setPixmap(QPixmap.fromImage(QImage.fromData(output.getvalue())).scaled(340, 340, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation))
            status.setText('Companion enabled. On the phone, choose Scan QR in Computers. This QR works once and expires in five minutes. Manual pairing details are below; keep tokens private.')
            details.setPlainText(f'Computer: {server.name}\nMachine ID: {server.machine_id}\nPort: {server.port}\n\nCertificate fingerprint:\n{server.fingerprint}\n\nPhone token:\n{token}')

        def finish():
            if self.start_result is None:
                return
            poll.stop()
            server, token, error = self.start_result
            enable.setEnabled(True)
            if error:
                status.setText(f'Could not start companion: {error}. Install dependencies with uv sync --extra companion.')
                return
            if self.owner.closing:
                threading.Thread(target=server.close, daemon=True).start()
                return
            self.server = server
            self.timer.start()
            display(server, token)

        def stop():
            if self.server:
                server, self.server = self.server, None
                self.timer.stop()
                def worker():
                    server.revoke_all()
                    server.close()
                threading.Thread(target=worker, daemon=True).start()
            details.clear()
            qr.clear()
            if self.jobs:
                self.jobs.close()
                self.jobs = None
            status.setText('Companion stopped. All phone credentials have been revoked.')

        poll = QTimer(self.dialog)
        poll.setInterval(100)
        poll.timeout.connect(finish)
        enable.clicked.connect(start)
        revoke.clicked.connect(stop)
        self.dialog.show()

    def close(self):
        if self.jobs:
            self.jobs.close()
        self.timer.stop()
        while not self.requests.empty():
            try:
                item = self.requests.get_nowait()
            except queue.Empty:
                break
            item['error'] = 'Neyra is closing.'
            item['event'].set()
        if self.server:
            server, self.server = self.server, None
            threading.Thread(target=server.close, daemon=True).start()
