"""Domain-boundary regressions for remote capture without starting native engines."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from neyra.companion_ui import CompanionController


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.owner = SimpleNamespace(closing=False, history=SimpleNamespace(
            save_history_toggle=Mock(), add_transcript=Mock(), reminders=Mock()),
            reminder_store=Mock(records=[{'id': 'r', 'due_at': 1234.123456, 'text': 'synthetic', 'status': 'pending'}]),
            assistant_features=SimpleNamespace(job=SimpleNamespace(running=False), command=Mock()),
            _reminders_in_flight=set())
        self.owner.history.save_history_toggle.isChecked.return_value = True
        self.controller = SimpleNamespace(owner=self.owner, server=SimpleNamespace(machine_id='pc', name='test'))
        self.controller.notes = lambda: CompanionController.notes(self.controller)
        self.controller.snapshot = lambda: CompanionController.snapshot(self.controller)

    def handle(self, path, body):
        return CompanionController.handle(self.controller, path, body)

    def test_note_uses_history_only_and_respects_disabled_history(self):
        self.handle('/v1/capture', {'mode': 'NOTE', 'text': 'synthetic note'})
        self.owner.history.add_transcript.assert_called_once_with('synthetic note')
        self.owner.history.save_history_toggle.isChecked.return_value = False
        with self.assertRaises(ValueError):
            self.handle('/v1/capture', {'mode': 'NOTE', 'text': 'do not save'})

    def test_remote_context_requests_are_rejected(self):
        for text in ('explain selection', 'summarize clipboard', 'ask my notes private', 'what is on my screen'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.handle('/v1/capture', {'mode': 'ASSISTANT', 'text': text})
        self.owner.assistant_features.command.assert_not_called()

    def test_actions_check_deadline_in_milliseconds_without_float_roundtrip(self):
        self.handle('/v1/reminder', {'id': 'r', 'due_ms': 1234123, 'action': 'done'})
        self.owner.reminder_store.complete.assert_called_once_with('r')
        with self.assertRaises(ValueError):
            self.handle('/v1/reminder', {'id': 'r', 'due_ms': 1234000, 'action': 'snooze'})
        self.owner.reminder_store.snooze.assert_not_called()
