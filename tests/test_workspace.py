"""The workspace keeps existing data and routes actions without recording itself."""
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import tempfile
import unittest
from unittest.mock import Mock, patch
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from neyra.main import HistoryDashboard

APP = QApplication.instance() or QApplication([])


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, folder.name)
        with patch("neyra.main.input_devices", return_value=[]), patch("neyra.startup.is_enabled", return_value=False):
            self.window = HistoryDashboard()
        self.addCleanup(self.window.close)

    def test_theme_toggle_persists_and_restores(self):
        from neyra.themes import current_theme
        self.window.theme_button.click()
        self.assertEqual(current_theme(), "dark")
        self.assertEqual(self.window.settings.value("theme"), "dark")
        self.assertIn("#151922", self.window.styleSheet())
        with patch("neyra.main.input_devices", return_value=[]), patch("neyra.startup.is_enabled", return_value=False):
            reopened = HistoryDashboard()
        self.addCleanup(reopened.close)
        self.assertEqual(current_theme(), "dark")
        self.assertEqual(reopened.theme_button.text(), "Use light theme")
        reopened.theme_button.click()
        self.assertEqual(current_theme(), "light")

    def test_home_is_default_and_notes_share_one_navigation_group(self):
        self.assertEqual(self.window.pages.currentIndex(), 9)
        self.assertTrue(self.window.home.isAncestorOf(self.window.capture))
        for page in (0, 1):
            self.window.show_page(page)
            self.assertTrue(self.window.nav_buttons[0].isChecked())
        self.window.show_page(3)
        self.assertTrue(self.window.nav_buttons[6].isChecked())
        self.assertNotIn(2, self.window.context_buttons)

    def test_home_tracks_note_addition_deletion_and_reminder_states(self):
        record = self.window.add_transcript("A fresh thought to keep")
        self.assertIn("A fresh thought", self.window.home.note_labels[0].text())
        self.window.delete_transcript(record)
        self.assertIn("first note", self.window.home.note_labels[0].text())
        reminder = {"id": "sample", "text": "Send the slides", "status": "pending", "due_at": 1900000000}
        self.window.reminders.refresh([reminder])
        self.assertIn("Send the slides", self.window.home.reminder_labels[0].text())
        self.window.reminders.refresh([{**reminder, "status": "fired"}])
        self.assertNotIn("Send the slides", self.window.home.reminder_labels[0].text())

    def test_quick_actions_route_to_existing_handlers(self):
        remind = Mock()
        meeting = Mock()
        self.window.reminders.speak_requested.connect(remind)
        self.window.notetaker_start.connect(meeting)
        self.window.home.remind.emit()
        self.assertEqual(self.window.pages.currentIndex(), 7)
        self.window.home.meeting.emit()
        self.assertEqual(self.window.pages.currentIndex(), 1)
        remind.assert_called_once()
        meeting.assert_called_once()
        self.window.home.ask_notes.emit()
        self.assertEqual(self.window.pages.currentIndex(), 8)
        self.assertEqual(self.window.assistant_panel.tabs.currentIndex(), 2)
