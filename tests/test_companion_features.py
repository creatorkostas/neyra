"""QR enrollment, cross-restart delivery and recurring reminder regressions."""
import base64
import json
import tempfile
import threading
import time
import unittest
from unittest.mock import patch, Mock
from types import SimpleNamespace
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication
from neyra.companion import CompanionServer
from neyra.companion_jobs import CompanionJobs
from neyra.reminders import ReminderStore

APP = QApplication.instance() or QApplication([])


class Settings:
    def __init__(self):
        self.data = {}
    def value(self, key, default=None):
        return self.data.get(key, default)
    def setValue(self, key, value):
        self.data[key] = value


class RecurrenceTests(unittest.TestCase):
    def test_delivery_creates_one_next_occurrence_and_reload_preserves_it(self):
        settings = Settings()
        store = ReminderStore(settings)
        now = time.time()
        first = store.add_at('synthetic daily task', now + 60)
        store.set_repeat(first['id'], 86400)
        store.mark_fired([first['id']])
        following = [r for r in store.records if r['status'] == 'pending']
        self.assertEqual(len(following), 1)
        self.assertEqual(following[0]['due_at'], first['due_at'] + 86400)
        store.complete(first['id'])
        self.assertEqual(len(store.records), 2)
        restored = ReminderStore(settings)
        self.assertEqual(restored.records, store.records)

    def test_stopping_series_cancels_spawned_future_without_changing_old_delivery(self):
        store = ReminderStore(Settings())
        first = store.add('remind me in an hour to test')
        store.set_repeat(first['id'], 86400)
        store.mark_fired([first['id']])
        store.stop_repeating(first['id'])
        self.assertEqual(len(store.records), 1)
        self.assertEqual(store.records[0]['status'], 'fired')
        self.assertNotIn('repeat_seconds', store.records[0])

    def test_completing_pending_weekly_task_preserves_cadence(self):
        store = ReminderStore(Settings())
        first = store.add('remind me in 10 minutes to test')
        store.set_repeat(first['id'], 604800)
        store.complete(first['id'])
        self.assertEqual(store.records[-1]['due_at'], first['due_at'] + 604800)
        self.assertEqual(store.records[-1]['repeat_seconds'], 604800)
        with self.assertRaises(ValueError):
            store.set_repeat(first['id'], -1)


class EnrollmentTests(unittest.TestCase):
    def test_invitation_is_single_use_expiring_and_revocable(self):
        with tempfile.TemporaryDirectory() as folder:
            server = CompanionServer(folder, lambda *_: {})
            self.addCleanup(server.close)
            invite = server.new_invite()
            token = server.enroll(invite)['token']
            self.assertIn(token, server.tokens)
            with self.assertRaises(ValueError):
                server.enroll(invite)
            expired = server.new_invite()
            server.invites[expired] = time.monotonic() - 1
            with self.assertRaises(ValueError):
                server.enroll(expired)
            pending = server.new_invite()
            server.revoke_all()
            with self.assertRaises(ValueError):
                server.enroll(pending)

    def test_receipt_survives_service_restart_without_storing_raw_audio(self):
        with tempfile.TemporaryDirectory() as folder:
            first = CompanionServer(folder, lambda *_: {})
            first.receipt('Bearer synthetic', 'note-1')
            first.save_receipt('Bearer synthetic', 'note-1', 'digest', {'message': 'saved'})
            first.close()
            second = CompanionServer(folder, lambda *_: {})
            self.addCleanup(second.close)
            self.assertEqual(second.receipt('Bearer synthetic', 'note-1'), ('digest', {'message': 'saved'}))
            self.assertIsNone(second.receipt('Bearer another-phone', 'note-1'))


class FakeTranscriber(QObject):
    finished = Signal(str)
    failed = Signal(str)
    def run(self, chunks, model):
        samples = chunks.get()
        assert len(samples) == 1600
        assert model == 'whistle'
        self.finished.emit('synthetic phone transcript')
    def close(self):
        pass


class JobTests(unittest.TestCase):
    def setUp(self):
        self.owner = QObject()
        self.owner.recording = self.owner.processing = self.owner.notetaker_active = self.owner.closing = False
        self.owner.update_controls = Mock()
        self.owner.history = SimpleNamespace(engine_choice=Mock())
        self.owner.history.engine_choice.currentData.return_value = 'whistle'
        self.client = SimpleNamespace(active_id='synthetic-account', respond=Mock(return_value='Synthetic answer'))
        self.owner.assistant_features = SimpleNamespace(get_assistant_provider=lambda: self.client)
        self.jobs = CompanionJobs(self.owner)
        self.addCleanup(self.jobs.close)

    def wait_done(self, identifier):
        until = time.monotonic() + 3
        while self.jobs.jobs[identifier]['status'] == 'running' and time.monotonic() < until:
            APP.processEvents()
            threading.Event().wait(.01)
        return self.jobs.status({'jobId': identifier, '_peer': 'phone'})

    def test_audio_is_transcribed_without_desktop_capture_or_paste(self):
        with patch('neyra.companion_jobs.Transcriber', FakeTranscriber):
            result = self.jobs.create('transcribe', {'_peer': 'phone', 'pcm': base64.b64encode(b'\0' * 3200).decode()})
        self.assertEqual(self.wait_done(result['jobId'])['text'], 'synthetic phone transcript')
        self.assertFalse(self.owner.processing)
        with self.assertRaises(ValueError):
            self.jobs.status({'jobId': result['jobId'], '_peer': 'other-phone'})

    def test_chat_followup_is_phone_and_account_scoped_and_forget_clears_it(self):
        first = self.jobs.create('chat', {'_peer': 'phone', 'text': 'first question'})
        self.assertEqual(self.wait_done(first['jobId'])['text'], 'Synthetic answer')
        second = self.jobs.create('chat', {'_peer': 'phone', 'text': 'follow up'})
        self.wait_done(second['jobId'])
        prompt = json.loads(self.client.respond.call_args.args[1])
        self.assertEqual(prompt['recentConversation'][0]['request'], 'first question')
        self.jobs.forget('phone')
        self.assertNotIn('phone', self.jobs.memories)

    def test_cancel_discards_late_answer(self):
        gate = threading.Event()
        def respond(*_args, **_kwargs):
            gate.wait(1)
            return 'Late answer'
        self.client.respond.side_effect = respond
        result = self.jobs.create('chat', {'_peer': 'phone', 'text': 'test'})
        self.jobs.status({'_peer': 'phone', 'jobId': result['jobId'], 'action': 'cancel'})
        gate.set()
        APP.processEvents()
        status = self.jobs.status({'_peer': 'phone', 'jobId': result['jobId']})
        self.assertEqual(status['status'], 'cancelled')
        self.assertEqual(status['text'], '')


class NoteDeduplicationTests(unittest.TestCase):
    def test_history_metadata_closes_the_gap_before_receipt_is_written(self):
        from PySide6.QtCore import QSettings
        from neyra.main import HistoryDashboard
        settings = Mock()
        settings.status.return_value = QSettings.Status.NoError
        owner = SimpleNamespace(save_history_toggle=Mock(), records=[], settings=settings,
                                items=Mock(), refresh_notes_state=Mock())
        owner.save_history_toggle.isChecked.return_value = True
        first = HistoryDashboard.add_transcript(owner, 'Synthetic durable note', remote_key='a' * 64)
        again = HistoryDashboard.add_transcript(owner, 'Synthetic durable note', remote_key='a' * 64)
        self.assertIs(first, again)
        self.assertEqual(len(owner.records), 1)
        self.assertEqual(settings.setValue.call_count, 1)
        self.assertEqual(settings.sync.call_count, 2)
