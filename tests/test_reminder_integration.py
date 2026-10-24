"""Reminder shortcuts, command recording, persisted deadlines and notifications."""
import os
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtCore import QSettings
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication
from pynput import keyboard
from neyra.hotkeys import Hotkeys
from neyra.main import Assistant
from neyra.reminders import ReminderStore

APP = QApplication.instance() or QApplication([])


class ReminderIntegrationTests(unittest.TestCase):
    def setUp(self):
        speech = patch("neyra.assistant_features.PiperSpeech")
        speech.start()
        self.addCleanup(speech.stop)
        mute = patch("neyra.main.SpeakerMute")
        mute.start()
        self.addCleanup(mute.stop)
        folder = tempfile.TemporaryDirectory(prefix="neyra-reminder-ui-")
        self.addCleanup(folder.cleanup)
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, folder.name)
        for target, value in (
            ("neyra.main.input_devices", []),
            ("neyra.startup.is_enabled", False),
            ("neyra.stt.Transcriber.prepare_whistle", None),
            ("neyra.stt.Transcriber.prepare_voz", None),
        ):
            patcher = patch(target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def assistant(self):
        with patch("neyra.hotkeys.Hotkeys.start"), patch("neyra.main.QSystemTrayIcon.show"):
            assistant = Assistant(APP)
        self.addCleanup(assistant.cleanup)
        assistant.engine.run = Mock()
        return assistant

    def test_reminder_chord_is_separate_and_repeated_keydown_is_ignored(self):
        with patch("neyra.hotkeys.keyboard.Listener") as listener:
            shortcuts = Hotkeys()
            self.addCleanup(shortcuts.stop)
            started, stopped, dictation, toggles = [], [], [], []
            shortcuts.reminder_start.connect(lambda: started.append(True))
            shortcuts.reminder_stop.connect(lambda: stopped.append(True))
            shortcuts.hold_start.connect(lambda: dictation.append(True))
            shortcuts.toggle.connect(lambda: toggles.append(True))
            shortcuts.start()
            down, up = listener.call_args.kwargs["on_press"], listener.call_args.kwargs["on_release"]
            for _ in range(2):
                down(keyboard.Key.ctrl_l)
                down(keyboard.Key.alt_l)
                down(keyboard.Key.space)
                down(keyboard.Key.space)
                up(keyboard.Key.space)
                up(keyboard.Key.alt_l)
                up(keyboard.Key.ctrl_l)
            self.assertEqual((len(started), len(stopped)), (2, 2))
            self.assertEqual(dictation, [])
            self.assertEqual(toggles, [])

    def test_active_reminder_chord_cannot_also_start_dictation(self):
        with patch("neyra.hotkeys.keyboard.Listener") as listener:
            shortcuts = Hotkeys()
            self.addCleanup(shortcuts.stop)
            dictation = Mock()
            shortcuts.hold_start.connect(dictation)
            shortcuts.start()
            down = listener.call_args.kwargs["on_press"]
            for key in (keyboard.Key.ctrl_l, keyboard.Key.alt_l, keyboard.Key.space, keyboard.Key.cmd_l):
                down(key)
            dictation.assert_not_called()
            self.assertTrue(shortcuts.reminder_holding)

    def test_reminder_recording_does_not_paste_or_save_dictation(self):
        assistant = self.assistant()
        APP.clipboard().setText("Previous clipboard")
        assistant.last_text = "Previous dictation"
        with patch("neyra.main.Microphone", return_value=Mock()):
            assistant.start_reminder()
        self.assertTrue(assistant.recording)
        assistant.hotkeys.hold_stop.emit()
        self.assertTrue(assistant.recording)
        with patch("neyra.main.time.time", return_value=1000):
            assistant.hotkeys.reminder_stop.emit()
        self.assertFalse(assistant.recording)
        self.assertFalse(assistant.history.reminders.speak_button.isEnabled())
        with patch("neyra.main.time.time", return_value=1030):
            assistant.complete("Remind me in an hour to take out the garbage.")
        reminder = assistant.reminder_store.records[0]
        self.assertEqual(reminder["text"], "take out the garbage")
        self.assertEqual(reminder["due_at"], 4600)
        self.assertEqual(reminder["status"], "pending")
        self.assertEqual(APP.clipboard().text(), "Previous clipboard")
        self.assertEqual(assistant.last_text, "Previous dictation")
        self.assertEqual(assistant.history.records, [])
        self.assertFalse(assistant.paste_timer.isActive())
        self.assertEqual(assistant.active_mode, "dictation")
        self.assertTrue(assistant.history.reminders.speak_button.isEnabled())

    def test_unclear_spoken_command_is_kept_for_correction_and_not_scheduled(self):
        assistant = self.assistant()
        assistant.active_mode = "reminder"
        command = "Remind me sometime to call Sam"
        with patch.object(assistant, "show_notification") as notify:
            assistant.complete(command)
        self.assertEqual(assistant.reminder_store.records, [])
        self.assertEqual(assistant.history.reminders.command.text(), command)
        self.assertIn("not saved", assistant.history.reminders.status.text())
        notify.assert_called_once()
        self.assertEqual(assistant.active_mode, "dictation")

    def test_due_reminder_notifies_once_and_stays_fired_after_reopening(self):
        assistant = self.assistant()
        reminder = assistant.reminder_store.add("remind me in a second to check the oven", now=1000)
        with patch("neyra.main.time.time", return_value=1001), patch.object(assistant, "show_notification") as notify:
            assistant.check_reminders()
            assistant.check_reminders()
            self.assertEqual(notify.call_count, 1)
            self.assertEqual(notify.call_args.args, ("Neyra reminder", "check the oven\nOpen Reminders to snooze or mark done."))
            self.assertEqual(reminder["status"], "pending")
            notify.call_args.kwargs["on_shown"]()
        self.assertEqual(reminder["status"], "fired")
        reopened = ReminderStore(assistant.history.settings)
        self.assertEqual(reopened.take_due(2000), [])
        self.assertEqual(reopened.records[0]["status"], "fired")

    def test_quit_before_notification_acknowledgment_keeps_reminder_pending(self):
        assistant = self.assistant()
        reminder = assistant.reminder_store.add("remind me in a second to check the oven", now=1000)
        with patch("neyra.main.time.time", return_value=1001), patch.object(assistant, "show_notification") as notify:
            assistant.check_reminders()
            callback = notify.call_args.kwargs["on_shown"]
            assistant.cleanup()
            callback()
        self.assertEqual(reminder["status"], "pending")
        reopened = ReminderStore(assistant.history.settings)
        self.assertEqual(reopened.pending_due(2000)[0]["id"], reminder["id"])

    def test_cancelled_reminder_does_not_notify(self):
        assistant = self.assistant()
        reminder = assistant.reminder_store.add("remind me in a minute to call Sam", now=1000)
        assistant.remove_reminder(reminder["id"])
        with patch("neyra.main.time.time", return_value=2000), patch.object(assistant, "show_notification") as notify:
            assistant.check_reminders()
        notify.assert_not_called()
        self.assertEqual(ReminderStore(assistant.history.settings).records, [])

    def test_overdue_restart_reminders_are_grouped_into_one_notification(self):
        assistant = self.assistant()
        assistant.reminder_store.add("remind me in a minute to call Sam", now=1000)
        assistant.reminder_store.add("remind me in two minutes to check the oven", now=1000)
        assistant.reminder_store = ReminderStore(assistant.history.settings)
        with patch("neyra.main.time.time", return_value=2000), patch.object(assistant, "show_notification") as notify:
            assistant.check_reminders()
        self.assertEqual(notify.call_count, 1)
        self.assertIn("2 reminders due", notify.call_args.args[0])
        self.assertIn("call Sam", notify.call_args.args[1])
        self.assertIn("check the oven", notify.call_args.args[1])

    def test_notifications_use_the_desktop_when_supported(self):
        assistant = self.assistant()
        with patch("neyra.main.QSystemTrayIcon.isSystemTrayAvailable", return_value=True), patch("neyra.main.QSystemTrayIcon.supportsMessages", return_value=True), patch.object(assistant.tray, "showMessage") as notification:
            assistant.show_notification("Neyra reminder", "Take out the garbage")
        self.assertEqual(notification.call_args.args[:2], ("Neyra reminder", "Take out the garbage"))
        self.assertEqual(assistant.notification_alerts, [])

    def test_background_timer_dispatches_due_reminder(self):
        assistant = self.assistant()
        APP.processEvents()
        reminder = assistant.reminder_store.add("remind me in a second to stretch", now=1000)
        assistant.reminder_timer.setInterval(20)
        with patch("neyra.main.time.time", return_value=1001), patch("neyra.main.QSystemTrayIcon.isSystemTrayAvailable", return_value=True), patch("neyra.main.QSystemTrayIcon.supportsMessages", return_value=True), patch.object(assistant.tray, "showMessage") as notification:
            timer = QSignalSpy(assistant.reminder_timer.timeout)
            self.assertTrue(timer.wait(2000), "Reminder timer did not fire")
        self.assertEqual(notification.call_count, 1)
        self.assertEqual(notification.call_args.args[:2], ("Neyra reminder", "stretch\nOpen Reminders to snooze or mark done."))
        self.assertEqual(reminder["status"], "fired")

    def test_no_notification_backend_opens_nonblocking_alert(self):
        assistant = self.assistant()
        with patch("neyra.main.QSystemTrayIcon.isSystemTrayAvailable", return_value=False), patch("neyra.main.shutil.which", return_value=None):
            assistant.show_notification("Neyra reminder", "Take out the garbage")
        self.assertEqual(len(assistant.notification_alerts), 1)
        alert = assistant.notification_alerts[0]
        self.assertFalse(alert.isModal())
        alert.reject()
        self.assertEqual(assistant.notification_alerts, [])

    def test_failed_notify_send_falls_back_to_alert(self):
        assistant = self.assistant()
        with patch("neyra.main.QSystemTrayIcon.isSystemTrayAvailable", return_value=False), patch("neyra.main.sys.platform", "linux"), patch("neyra.main.shutil.which", return_value="nonexistent-neyra-notifier"):
            assistant.show_notification("Neyra reminder", "Take out the garbage")
            deadline = time.monotonic() + 2
            while not assistant.notification_alerts and time.monotonic() < deadline:
                APP.processEvents()
        self.assertEqual(len(assistant.notification_alerts), 1)

    def test_cleanup_stops_scheduling_and_prevents_notifications(self):
        assistant = self.assistant()
        assistant.reminder_store.add("remind me in a second to check the oven", now=1000)
        assistant.cleanup()
        self.assertFalse(assistant.reminder_timer.isActive())
        with patch.object(assistant, "show_notification") as notify:
            assistant.check_reminders()
        notify.assert_not_called()
        self.assertEqual(assistant.reminder_store.records[0]["status"], "pending")


if __name__ == "__main__":
    unittest.main()
