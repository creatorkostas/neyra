import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from neyra.main import Assistant
from neyra.data_transfer import create_backup
from neyra.shortcuts import DEFAULT_SHORTCUTS

APP = QApplication.instance() or QApplication([])


class PreferenceIntegrationTests(unittest.TestCase):
    def setUp(self):
        speech = patch("neyra.assistant_features.PiperSpeech")
        speech.start()
        self.addCleanup(speech.stop)
        mute = patch("neyra.main.SpeakerMute")
        mute.start()
        self.addCleanup(mute.stop)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, folder.name)
        with patch("neyra.hotkeys.Hotkeys.start"), patch("neyra.main.input_devices", return_value=[]), \
                patch("neyra.startup.is_enabled", return_value=False), patch("neyra.main.QSystemTrayIcon.show"), \
                patch("neyra.stt.Transcriber.prepare_whistle"), patch("neyra.stt.Transcriber.prepare_voz"):
            self.owner = Assistant(APP)
        self.addCleanup(self.owner.cleanup)
        self.window = self.owner.history

    def test_speaking_mutes_and_restores_audio_and_preference(self):
        self.assertTrue(self.window.mute_while_speaking_toggle.isChecked())
        self.owner.engine.run = Mock()
        for mode in ("dictation", "assistant", "reminder"):
            self.owner.speaker_mute.reset_mock()
            with patch("neyra.main.Microphone", return_value=Mock()):
                self.owner.start(mode)
                self.owner.speaker_mute.begin.assert_called_once()
                self.owner.stop()
                self.owner.speaker_mute.end.assert_called_once()
            self.owner.processing = False
        self.window.mute_while_speaking_toggle.setChecked(False)
        self.assertFalse(self.window.settings.value("mute_while_speaking", type=bool))
        self.owner.speaker_mute.reset_mock()
        with patch("neyra.main.Microphone", return_value=Mock()):
            self.owner.start()
            self.owner.speaker_mute.begin.assert_not_called()
            self.owner.stop()
        self.owner.processing = False

    def test_mute_restore_on_start_failure_disable_and_shutdown(self):
        self.owner.engine.run = Mock()
        microphone = Mock()
        microphone.start.side_effect = RuntimeError("Microphone failed")
        with patch("neyra.main.Microphone", return_value=microphone):
            self.owner.start()
        self.owner.speaker_mute.end.assert_called()
        self.assertFalse(self.owner.recording)
        self.owner.speaker_mute.reset_mock()
        with patch("neyra.main.Microphone", return_value=Mock()):
            self.owner.start()
        self.window.mute_while_speaking_toggle.setChecked(False)
        self.owner.speaker_mute.end.assert_called_once()
        self.owner.cleanup()
        self.owner.speaker_mute.close.assert_called_once()

    def test_shortcuts_apply_persist_and_update_hints(self):
        self.window.shortcut_panel.fields["dictation"].setText("Ctrl+Alt+D")
        self.window.shortcut_panel.request_apply()
        self.assertEqual(json.loads(self.window.settings.value("shortcuts"))["dictation"], "Ctrl+Alt+D")
        self.assertEqual(self.owner.hotkeys.bindings["dictation"], {"ctrl", "alt", "d"})
        self.assertIn("Ctrl + Alt + D", self.window.dictation_key_hint.text())
        self.owner.recording = True
        self.owner.apply_shortcut_settings(DEFAULT_SHORTCUTS)
        self.assertEqual(self.window.shortcuts["dictation"], "Ctrl+Alt+D")
        self.owner.recording = False
        self.window.shortcut_panel.restore_defaults()
        self.assertEqual(self.window.shortcuts, DEFAULT_SHORTCUTS)

    def test_invalid_or_declined_shortcuts_do_not_save(self):
        panel = self.window.shortcut_panel
        panel.fields["dictation"].setText("Ctrl+Alt+A")
        panel.request_apply()
        self.assertIn("conflicts", panel.status.text())
        panel.fields["dictation"].setText("Ctrl+C")
        with patch("neyra.preferences_ui.QMessageBox.question", return_value=0):
            panel.request_apply()
        self.assertFalse(self.window.settings.contains("shortcuts"))

    def test_shortcut_write_failure_restores_session_and_preferences(self):
        for error in (False, True):
            with patch.object(self.window.settings, "sync", side_effect=OSError("Disk full") if error else None), \
                    patch.object(self.window.settings, "status", return_value=QSettings.Status.AccessError):
                self.owner.apply_shortcut_settings({**DEFAULT_SHORTCUTS, "dictation": "Ctrl+Alt+D"})
            self.assertEqual(self.window.shortcuts, DEFAULT_SHORTCUTS)
            self.assertEqual(self.owner.hotkeys.bindings["dictation"], {"ctrl", "win"})
            self.assertFalse(self.window.settings.contains("shortcuts"))
            self.assertIn("not changed", self.window.shortcut_panel.status.text())

    def test_exports_and_backup_use_selected_files(self):
        self.window.add_transcript("A thought in Ελληνικά")
        target = self.folder / "notes.txt"
        with patch("neyra.main.QFileDialog.getSaveFileName", return_value=(str(target), "Plain text (*.txt)")):
            self.window.export_notes_file()
        self.assertIn("Ελληνικά", target.read_text(encoding="utf-8"))
        self.assertFalse(target.read_text(encoding="utf-8").startswith("#"))
        target = self.folder / "backup.json"
        with patch("neyra.main.QFileDialog.getSaveFileName", return_value=(str(target), "")):
            self.window.backup_file()
        self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["data"]["history"][0]["text"], "A thought in Ελληνικά")

    def test_restore_waits_for_idle_then_quits_after_success(self):
        payload = create_backup(self.window.settings)
        payload["data"]["style"] = "Formal"
        self.owner.processing = True
        self.owner.restore_data(payload)
        self.assertNotEqual(self.window.settings.value("style"), "Formal")
        self.owner.processing = False
        with patch.object(self.owner, "quit") as quit_app:
            self.owner.restore_data(payload)
            quit_app.assert_called_once()
        self.assertTrue(self.owner.closing)
        self.assertEqual(self.window.settings.value("style"), "Formal")

    def test_restore_file_requires_confirmation_and_rejects_bad_data(self):
        payload = create_backup(self.window.settings)
        payload["data"]["style"] = "Formal"
        path = self.folder / "restore.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        with patch("neyra.main.QFileDialog.getOpenFileName", return_value=(str(path), "")), \
                patch("neyra.main.QMessageBox.question", return_value=0):
            self.window.restore_file()
        self.assertFalse(self.owner.closing)
        self.assertNotEqual(self.window.settings.value("style"), "Formal")
        path.write_text('{"version":999}', encoding="utf-8")
        with patch("neyra.main.QFileDialog.getOpenFileName", return_value=(str(path), "")), \
                patch("neyra.main.QMessageBox.question") as confirmation:
            self.window.restore_file()
        confirmation.assert_not_called()
        self.assertIn("Restore failed", self.window.data_panel.status.text())

    def test_late_delivery_ack_does_not_undo_snooze_or_completion(self):
        for done in (False, True):
            record = self.owner.reminder_store.add("Remind me in one second to stretch", now=time.time()-10)
            callbacks = []
            with patch.object(self.owner, "show_notification", side_effect=lambda *args, on_shown=None: callbacks.append(on_shown)):
                self.owner.check_reminders()
            self.assertTrue(callbacks)
            if done:
                self.owner.complete_reminder(record["id"])
            else:
                self.owner.snooze_reminder(record["id"], "10min")
            callbacks[0]()
            self.assertEqual(record["status"], "done" if done else "pending")
            if not done:
                self.assertGreater(record["due_at"], time.time())
