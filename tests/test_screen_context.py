"""Explicit screen requests and synthetic-image-only capture tests."""
import base64
import os
import threading
import unittest
from unittest.mock import Mock, patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import QApplication
from neyra import screen_context

APP = QApplication.instance() or QApplication([])


class ScreenRequestTests(unittest.TestCase):
    def test_explicit_screen_references_are_recognized(self):
        for text in (
            "Based on what I see on the screen, what should I do?",
            "Explain what is on my screen.", "Read this screen.",
            "Take a screenshot and explain it.", "Look at my screen.",
            "What am I looking at?", "Describe what I can see.",
            "BASED ON THE SCREEN tell me what to click.",
            "What is visible on screen?", "Use the screen shot.",
        ):
            with self.subTest(text=text):
                self.assertTrue(screen_context.screen_requested(text))

    def test_generic_screen_words_do_not_authorize_capture(self):
        for text in (None, 1, "", "Open screen settings", "Lock my screen", "Increase screen brightness",
                     "Explain screening tests", "How do monitors work?", "What should I do?",
                     "Don't take a screenshot", "Do not share the screen", "Never capture this screen", "Explain this without using a screenshot", "No screenshot, just explain monitors"):
            with self.subTest(text=text):
                self.assertFalse(screen_context.screen_requested(text))


class ScreenCaptureTests(unittest.TestCase):
    def screen(self, width=200, height=100):
        image = QImage(width, height, QImage.Format.Format_RGB32)
        image.fill(QColor("#427ac4"))
        screen = Mock()
        screen.grabWindow.return_value = QPixmap.fromImage(image)
        return screen

    def capture(self, selected, primary=None):
        gui = Mock()
        gui.instance.return_value = APP
        gui.screenAt.return_value = selected
        gui.primaryScreen.return_value = primary
        with patch.object(screen_context, "QGuiApplication", gui), patch.object(screen_context.QCursor, "pos", return_value=QPoint(25, 40)):
            data_url = screen_context.capture_screen()
        return data_url, gui

    def test_only_cursor_monitor_is_captured_and_jpeg_stays_in_memory(self):
        selected, primary = self.screen(), self.screen()
        data_url, gui = self.capture(selected, primary)
        selected.grabWindow.assert_called_once_with(0)
        primary.grabWindow.assert_not_called()
        gui.primaryScreen.assert_not_called()
        gui.screenAt.assert_called_once_with(QPoint(25, 40))
        self.assertTrue(data_url.startswith("data:image/jpeg;base64,"))
        raw = base64.b64decode(data_url.split(",", 1)[1], validate=True)
        self.assertLessEqual(len(raw), screen_context.MAX_IMAGE_BYTES)
        decoded = QImage.fromData(raw, "JPEG")
        self.assertEqual((decoded.width(), decoded.height()), (200, 100))

    def test_primary_monitor_is_fallback_and_large_image_preserves_aspect(self):
        screen = self.screen(2560, 1440)
        data_url, gui = self.capture(None, screen)
        gui.primaryScreen.assert_called_once()
        screen.grabWindow.assert_called_once_with(0)
        decoded = QImage.fromData(base64.b64decode(data_url.split(",", 1)[1]), "JPEG")
        self.assertEqual((decoded.width(), decoded.height()), (1920, 1080))

    def test_missing_or_null_capture_reports_permissions_without_fallback_capture(self):
        with self.assertRaisesRegex(RuntimeError, "permissions"):
            self.capture(None)
        selected, primary = Mock(), self.screen()
        selected.grabWindow.return_value = QPixmap()
        with self.assertRaisesRegex(RuntimeError, "Wayland and macOS"):
            self.capture(selected, primary)
        primary.grabWindow.assert_not_called()

    def test_encoded_image_byte_limit_is_enforced(self):
        with patch.object(screen_context, "MAX_IMAGE_BYTES", 1), self.assertRaisesRegex(RuntimeError, "4 MB"):
            self.capture(self.screen())

    def test_capture_requires_gui_thread_and_never_grabs_from_worker(self):
        selected = self.screen()
        gui = Mock()
        gui.instance.return_value = APP
        errors = []

        def worker():
            try:
                screen_context.capture_screen()
            except RuntimeError as exc:
                errors.append(str(exc))

        with patch.object(screen_context, "QGuiApplication", gui):
            thread = threading.Thread(target=worker)
            thread.start()
            thread.join(2)
        self.assertEqual(errors, ["Screen capture must run on the Qt GUI thread."])
        gui.screenAt.assert_not_called()
        selected.grabWindow.assert_not_called()


if __name__ == "__main__":
    unittest.main()
