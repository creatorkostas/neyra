import os
import threading
import unittest
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtCore import QObject
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from neyra.assistant_features import BackgroundTask

APP = QApplication.instance() or QApplication([])


class BackgroundTaskTests(unittest.TestCase):
    def test_interrupt_allows_new_job_without_waiting_and_drops_old_events(self):
        owner = QObject()
        job = BackgroundTask(owner)
        entered, release = threading.Event(), threading.Event()
        results, deltas = [], []
        job.done.connect(results.append)
        job.delta.connect(deltas.append)
        def slow(cancel):
            entered.set()
            release.wait(3)
            job.emit_delta(cancel, "stale delta")
            return "stale result"
        try:
            job.start(slow)
            self.assertTrue(entered.wait(1))
            job.interrupt()
            self.assertFalse(job.running)
            job.start(lambda cancel: "new result")
            for _ in range(100):
                QTest.qWait(10)
                if results:
                    break
            self.assertEqual(results, ["new result"])
            release.set()
            QTest.qWait(50)
            self.assertEqual(results, ["new result"])
            self.assertEqual(deltas, [])
        finally:
            release.set()
            job.close()
