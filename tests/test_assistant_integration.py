"""Assistant routes, privacy boundaries, and reviewed reminder creation."""
import os
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtCore import QSettings, QDateTime
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pynput import keyboard
from neyra.main import Assistant
from neyra.hotkeys import Hotkeys

APP = QApplication.instance() or QApplication([])


class AssistantIntegrationTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="neyra-assistant-ui-")
        self.addCleanup(folder.cleanup)
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, folder.name)
        self.client = Mock()
        self.client.accounts.return_value = []
        self.client.active_id = None
        for target, value in (("neyra.main.input_devices", []),
                              ("neyra.startup.is_enabled", False),
                              ("neyra.stt.Transcriber.prepare_whistle", None),
                              ("neyra.stt.Transcriber.prepare_voz", None),
                              ("neyra.chatgpt.ChatGPTClient", self.client)):
            patcher = patch(target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        with patch("neyra.hotkeys.Hotkeys.start"), patch("neyra.main.QSystemTrayIcon.show"):
            self.owner = Assistant(APP)
        self.addCleanup(self.owner.cleanup)
        self.owner.engine.run = Mock()
        self.features = self.owner.assistant_features
        self.panel = self.owner.history.assistant_panel

    def finish_job(self):
        for _ in range(100):
            QTest.qWait(10)
            if not self.features.job.running:
                break
        self.assertFalse(self.features.job.running)

    def test_assistant_shortcut_is_distinct_and_repeats_do_not_toggle(self):
        with patch("neyra.hotkeys.keyboard.Listener") as listener:
            shortcuts = Hotkeys()
            self.addCleanup(shortcuts.stop)
            start, stop, other = Mock(), Mock(), Mock()
            shortcuts.assistant_start.connect(start)
            shortcuts.assistant_stop.connect(stop)
            shortcuts.reminder_start.connect(other)
            shortcuts.hold_start.connect(other)
            shortcuts.start()
            down, up = listener.call_args.kwargs["on_press"], listener.call_args.kwargs["on_release"]
            key_a = keyboard.KeyCode.from_char("a")
            for key in (keyboard.Key.ctrl_l, keyboard.Key.alt_l, key_a, key_a, keyboard.Key.cmd_l):
                down(key)
            start.assert_called_once()
            other.assert_not_called()
            up(key_a)
            stop.assert_called_once()

    def test_voice_command_never_pastes_or_saves_dictation(self):
        APP.clipboard().setText("Keep this")
        self.owner.last_text = "Last dictation"
        with patch("neyra.main.Microphone", return_value=Mock()):
            self.owner.start_assistant()
        self.owner.hotkeys.reminder_stop.emit()
        self.assertTrue(self.owner.recording)
        with patch("neyra.main.time.time", return_value=1000):
            self.owner.stop_assistant()
        with patch.object(self.owner, "check_reminders"):
            self.owner.complete("set a timer for five minutes")
        self.assertEqual(APP.clipboard().text(), "Keep this")
        self.assertEqual(self.owner.last_text, "Last dictation")
        self.assertEqual(self.owner.history.records, [])
        self.assertEqual(self.owner.reminder_store.records[0]["due_at"], 1300)
        self.assertFalse(self.owner.paste_timer.isActive())
        self.client.respond.assert_not_called()

    def test_selection_preview_does_not_send_until_requested(self):
        APP.clipboard().setText("Some selected text")
        self.panel.paste.click()
        self.client.respond.assert_not_called()
        self.client.respond.return_value = "An explanation"
        self.panel.explain.click()
        self.finish_job()
        self.assertEqual(self.client.respond.call_args.args[1], "Some selected text")
        self.assertEqual(self.panel.selection_answer.toPlainText(), "An explanation")

    def test_clipboard_capture_restores_original_and_sends_nothing(self):
        APP.clipboard().setText("Original clipboard")
        self.features.selection_stage = "release"
        self.features.selection_started = time.monotonic()
        with patch("neyra.assistant_features.is_wayland", return_value=False), patch("pynput.keyboard.Controller"):
            self.features.selection_tick()
        APP.clipboard().setText("Captured selection")
        self.features.selection_started -= 1
        self.features.selection_tick()
        self.assertEqual(APP.clipboard().text(), "Original clipboard")
        self.assertEqual(self.panel.selection.toPlainText(), "Captured selection")
        self.client.respond.assert_not_called()

    def test_missing_copy_never_reuses_stale_clipboard(self):
        APP.clipboard().setText("Private stale clipboard")
        self.features.selection_stage = "release"
        self.features.selection_started = time.monotonic()
        with patch("pynput.keyboard.Controller"):
            self.features.selection_tick()
        self.features.selection_started -= 1
        self.features.selection_tick()
        self.assertEqual(self.panel.selection.toPlainText(), "")
        self.assertEqual(APP.clipboard().text(), "Private stale clipboard")
        self.client.respond.assert_not_called()

    def test_changed_or_deleted_sources_require_new_preview(self):
        record = {"text": "Launch is Friday.", "time": "2026-10-24T12:00:00"}
        self.owner.history.records.append(record)
        self.panel.question.setText("When is launch?")
        self.features.find_notes()
        self.owner.history.records.clear()
        self.features.ask_notes()
        self.client.respond.assert_not_called()
        self.assertEqual(self.features.sources, [])
        self.assertIn("changed", self.panel.status.text())

    def test_knowledge_sends_numbered_sources_only_after_review(self):
        self.owner.history.records.append({"text": "Launch is Friday.", "time": "2026-10-24T12:00:00"})
        self.panel.question.setText("When is launch?")
        self.features.ask_notes()
        self.client.respond.assert_not_called()
        self.client.respond.return_value = "Friday [1]."
        self.features.ask_notes()
        self.finish_job()
        self.assertIn("[1] Dictation", self.client.respond.call_args.args[1])
        self.assertEqual(self.panel.knowledge_answer.toPlainText(), "Friday [1].")

    def test_meeting_actions_require_review_and_do_not_schedule_twice(self):
        self.owner.history.add_meeting("Alex will send slides.", {"title": "Planning"})
        self.features.refresh_meetings()
        self.client.respond.return_value = '[{"text":"Send slides","evidence":"Alex will send slides."}]'
        self.features.extract_actions()
        self.finish_job()
        self.assertEqual(self.owner.reminder_store.records, [])
        self.panel.action_due.setDateTime(QDateTime.currentDateTime().addSecs(3600))
        self.features.schedule_action()
        self.features.schedule_action()
        self.assertEqual(len(self.owner.reminder_store.records), 1)
        self.assertEqual(self.owner.reminder_store.records[0]["text"], "Send slides")
        self.features.clear_actions()
        self.client.respond.return_value = '[{"text":"Send the slides","evidence":"Alex will send slides."}]'
        self.features.extract_actions()
        self.finish_job()
        self.features.schedule_action()
        self.assertEqual(len(self.owner.reminder_store.records), 1)

    def test_signout_cannot_be_cancelled_after_revocation_starts(self):
        self.client.sign_out.return_value = "Signed out of ChatGPT."
        self.features.logout()
        self.assertFalse(self.panel.cancel.isVisible())
        self.features.cancel()
        self.assertFalse(self.features.job.cancelled.is_set())
        self.finish_job()
        self.assertEqual(self.panel.account_status.text(), "Signed out of ChatGPT.")

    def test_agenda_and_briefing_work_without_chatgpt(self):
        self.panel.agenda_text.setText("Team meeting")
        self.panel.agenda_at.setDateTime(QDateTime.currentDateTime())
        self.features.add_agenda()
        self.assertIn("Team meeting", self.panel.briefing.toPlainText())
        self.client.respond.assert_not_called()

    def test_cancelled_result_does_not_become_a_completed_answer(self):
        self.features.reply_widget = self.panel.selection_answer
        self.panel.selection_answer.setPlainText("Partial answer")
        self.features.job.cancelled.set()
        self.features.finished("Finished answer")
        self.assertIn("did not complete", self.panel.selection_answer.toPlainText())
        self.assertNotIn("Finished answer", self.panel.selection_answer.toPlainText())

    def test_capture_button_stops_assistant_and_cleanup_stops_speech(self):
        with patch("neyra.main.Microphone", return_value=Mock()):
            self.owner.start_assistant()
        self.owner.toggle_capture()
        self.assertFalse(self.owner.recording)
        self.assertTrue(self.owner.processing)
        speech = self.features.speech = Mock()
        self.owner.cleanup()
        speech.stop.assert_called_once()
        self.assertTrue(self.features.job.cancelled.is_set())


if __name__ == "__main__":
    unittest.main()
