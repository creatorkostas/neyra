"""Regression checks for audio cleanup, worker recovery and dashboard data."""
import json
import os
import queue
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import numpy as np
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QLabel, QFrame, QTabWidget
from neyra.audio import Microphone
from neyra.hotkeys import Hotkeys
from neyra.main import Assistant, HistoryDashboard, load_records
from neyra.stt import Transcriber
from neyra.text_tools import apply_style, expand_snippets
from pynput import keyboard

APP = QApplication.instance() or QApplication([])
SETTINGS_DIR = tempfile.TemporaryDirectory(prefix="neyra-tests-")
QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, SETTINGS_DIR.name)


class RegressionTests(unittest.TestCase):
    def setUp(self):
        QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope, "Neyra", "Neyra").clear()
        for target in ("neyra.stt.Transcriber.prepare_whistle", "neyra.stt.Transcriber.prepare_voz"):
            patcher = patch(target)
            patcher.start()
            self.addCleanup(patcher.stop)

    def make_assistant(self):
        with patch("neyra.hotkeys.Hotkeys.start"), patch("neyra.main.QSystemTrayIcon.show"):
            assistant = Assistant(APP)
        self.addCleanup(assistant.cleanup)
        return assistant

    def test_microphone_always_closes_and_unblocks_worker(self):
        chunks = queue.Queue()
        mic = Microphone(chunks, lambda value: None)
        stream = mic.stream = Mock()
        stream.stop.side_effect = RuntimeError("device disconnected")
        with self.assertRaisesRegex(RuntimeError, "disconnected"):
            mic.stop()
        stream.close.assert_called_once()
        self.assertIsNone(mic.stream)
        self.assertIsNone(chunks.get_nowait())
        mic.stop()
        self.assertTrue(chunks.empty())

    def test_failed_microphone_start_closes_stream(self):
        stream = Mock()
        stream.start.side_effect = RuntimeError("unavailable")
        mic = Microphone(queue.Queue(), lambda value: None)
        with patch("neyra.audio.sd.InputStream", return_value=stream):
            with self.assertRaises(RuntimeError):
                mic.start()
        stream.close.assert_called_once()

    def test_repeated_hold_and_both_control_keys(self):
        with patch("neyra.hotkeys.keyboard.Listener") as listener:
            hotkeys = Hotkeys()
            started, stopped = [], []
            hotkeys.hold_start.connect(lambda: started.append(True))
            hotkeys.hold_stop.connect(lambda: stopped.append(True))
            hotkeys.start()
            down = listener.call_args.kwargs["on_press"]
            up = listener.call_args.kwargs["on_release"]
            for _ in range(2):
                down(keyboard.Key.ctrl_l)
                down(keyboard.Key.ctrl_r)
                down(keyboard.Key.cmd_l)
                up(keyboard.Key.ctrl_l)
                self.assertTrue(hotkeys.holding)
                up(keyboard.Key.ctrl_r)
                up(keyboard.Key.cmd_l)
            self.assertEqual((len(started), len(stopped)), (2, 2))
            self.assertFalse(hotkeys.modifiers_active())

    def test_corrupt_settings_do_not_crash_dashboard(self):
        settings = QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope, "Neyra", "Neyra")
        settings.setValue("history", json.dumps([{"text": "bad date", "time": "no"}, None, {"text": "valid", "time": "2026-10-19T10:00:00"}]))
        settings.setValue("meetings", "{broken")
        settings.setValue("dictionary", '[1, "Neyra"]')
        settings.setValue("snippets", '["wrong shape"]')
        dashboard = HistoryDashboard()
        self.addCleanup(dashboard.close)
        self.assertEqual(len(dashboard.records), 1)
        self.assertEqual(dashboard.dictionary_words(), ["Neyra"])
        self.assertEqual(dashboard.snippets(), {})
        self.assertEqual(dashboard.meeting_records, [])

    def test_formal_contractions_and_nonrecursive_snippets(self):
        self.assertEqual(apply_style("Don't go. I CAN'T attend", "Formal"), "Do not go. I cannot attend.")
        self.assertEqual(expand_snippets("My address", {"my address": "signature", "signature": "Name"}), "signature")
        self.assertEqual(expand_snippets("Home address", {"address": "short", "home address": "long"}), "long")
        self.assertEqual(expand_snippets("İ", {"i": "match"}), "match")

    def test_history_retention_search_delete_and_speed(self):
        dashboard = HistoryDashboard()
        self.addCleanup(dashboard.close)
        dashboard.records = [{"text": "old", "time": "2026-10-18T10:00:00"}] * 500
        dashboard.add_transcript("four words for speed", duration=2)
        self.assertEqual(len(dashboard.records), 500)
        self.assertIn(">120</span> wpm", dashboard.count_stat.text())
        dashboard.items.refresh(query="speed")
        self.assertEqual(dashboard.items.query, "speed")
        record = dashboard.records[-1]
        dashboard.delete_transcript(record)
        self.assertEqual(len(load_records(dashboard.settings, "history")), 499)

    def test_notetaker_controls_follow_recording_state(self):
        dashboard = HistoryDashboard()
        self.addCleanup(dashboard.close)
        started, stopped = [], []
        dashboard.notetaker_start.connect(lambda: started.append(True))
        dashboard.notetaker_stop.connect(lambda: stopped.append(True))
        dashboard.notetaker.start_button.click()
        self.assertEqual(len(started), 1)
        dashboard.set_meeting_state("recording", "Recording")
        self.assertTrue(dashboard.notetaker.timer.isActive())
        self.assertEqual(dashboard.notetaker.start_button.text(), "Stop and transcribe")
        dashboard.notetaker.start_button.click()
        self.assertEqual(len(stopped), 1)
        dashboard.set_meeting_state("transcribing", "Working")
        self.assertFalse(dashboard.notetaker.start_button.isEnabled())
        self.assertFalse(dashboard.notetaker.timer.isActive())
        dashboard.set_meeting_state("idle", "Saved")
        self.assertTrue(dashboard.notetaker.start_button.isEnabled())

    def test_meeting_cards_search_delete_and_intro_persist(self):
        dashboard = HistoryDashboard()
        self.addCleanup(dashboard.close)
        dashboard.add_meeting("We need to finish the design review.")
        dashboard.add_meeting("Tomorrow we will discuss the budget.")
        dashboard.notetaker.search.setText("design")
        labels = [label.text() for label in dashboard.notetaker.feed.widget().findChildren(QLabel)]
        self.assertTrue(any("design" in text for text in labels))
        self.assertFalse(any("budget" in text for text in labels))
        dashboard.delete_meeting(dashboard.meeting_records[0])
        self.assertEqual(len(load_records(dashboard.settings, "meetings")), 1)
        dashboard.notetaker.dismiss_intro()
        reopened = HistoryDashboard()
        self.addCleanup(reopened.close)
        self.assertTrue(reopened.notetaker.intro.isHidden())
        self.assertEqual(len(reopened.meeting_records), 1)

    def test_window_content_has_outer_inset(self):
        dashboard = HistoryDashboard()
        self.addCleanup(dashboard.close)
        dashboard.show()
        APP.processEvents()
        surface = dashboard.findChild(QFrame, "surface")
        self.assertLess(surface.geometry().right(), dashboard.rect().right())
        self.assertLess(surface.geometry().bottom(), dashboard.rect().bottom())

    def test_meeting_recording_updates_controls_and_saves_notes(self):
        assistant = self.make_assistant()
        assistant.engine.run = Mock()
        mic = Mock()
        system = Mock()
        system.stop.return_value = np.zeros(160, dtype=np.float32)
        def make_mic(chunks, level):
            mic.start.side_effect = lambda: chunks.put(np.ones(160, dtype=np.float32))
            mic.stop.side_effect = lambda: chunks.put(None)
            return mic
        with patch("neyra.main.bridge_path"), patch("neyra.main.Microphone", side_effect=make_mic), patch("neyra.main.SystemAudioRecorder", return_value=system):
            assistant.history.notetaker.start_button.click()
            self.assertTrue(assistant.notetaker_active)
            self.assertEqual(assistant.history.notetaker.state, "recording")
            assistant.history.notetaker.start_button.click()
            self.assertFalse(assistant.notetaker_active)
            self.assertEqual(assistant.history.notetaker.state, "transcribing")
            assistant.engine.run.assert_called_once()
            self.assertEqual(assistant.engine.run.call_args.kwargs["model"], "voz")
            self.assertIn("meeting_options", assistant.engine.run.call_args.kwargs)
            chunks = assistant.engine.run.call_args.args[0]
            np.testing.assert_allclose(chunks.get_nowait(), 0.5)
            self.assertIsNone(chunks.get_nowait())
            assistant.complete("We need to review the design.")
            self.assertEqual(assistant.history.notetaker.state, "idle")
            self.assertEqual(len(assistant.history.meeting_records), 1)
            self.assertEqual(assistant.active_mode, "dictation")

    def test_meeting_viewer_contains_summary_actions_and_plain_transcript(self):
        dashboard = HistoryDashboard()
        self.addCleanup(dashboard.close)
        transcript = "We need to review <draft> tomorrow. The plan is ready."
        dashboard.add_meeting(transcript)
        def inspect(dialog):
            tabs = dialog.findChild(QTabWidget)
            self.assertEqual(tabs.count(), 3)
            self.assertEqual(tabs.widget(2).toPlainText(), transcript)
            self.assertIn("need to", tabs.widget(1).toPlainText())
            return 0
        with patch("neyra.ui.QDialog.exec", new=inspect):
            dashboard.notetaker.open_meeting(dashboard.meeting_records[0])

    def test_meeting_cleanup_attempts_both_recorders_after_error(self):
        assistant = self.make_assistant()
        assistant.notetaker_mic = Mock()
        assistant.notetaker_mic.stop.side_effect = RuntimeError("mic error")
        assistant.system_audio = Mock()
        assistant.system_audio.stop.return_value = np.zeros(10, dtype=np.float32)
        audio, errors = assistant.stop_meeting_capture()
        assistant.system_audio.stop.assert_called_once()
        self.assertEqual(len(audio), 10)
        self.assertEqual(errors, ["mic error"])

    def test_async_error_stops_recording_and_resets_meeting_mode(self):
        assistant = self.make_assistant()
        assistant.recorder = Mock()
        assistant.recording = True
        assistant.active_mode = "notetaker"
        assistant.error("engine failed")
        assistant.recorder.stop.assert_called_once()
        self.assertFalse(assistant.recording)
        self.assertEqual(assistant.active_mode, "dictation")
        self.assertIn("engine failed", assistant.history.notetaker_status.text())

    def test_shutdown_stops_meeting_and_dictation(self):
        assistant = self.make_assistant()
        assistant.recorder = Mock()
        assistant.notetaker_mic = Mock()
        assistant.system_audio = Mock()
        assistant.cleanup()
        for recorder in (assistant.recorder, assistant.notetaker_mic, assistant.system_audio):
            recorder.stop.assert_called_once()
        assistant.cleanup()
        assistant.notetaker_mic.stop.assert_called_once()

    def test_worker_signals_arrive_on_gui_thread_and_can_repeat(self):
        assistant = self.make_assistant()
        results = []
        assistant.engine.finished.connect(results.append)
        for _ in range(2):
            chunks = queue.Queue(); chunks.put(None)
            assistant.engine.run(chunks, model="voz")
            assistant.engine.thread.join(timeout=2)
            self.assertFalse(assistant.engine.thread.is_alive())
            APP.processEvents()
        self.assertEqual(results, ["", ""])
        self.assertIs(assistant.thread(), APP.thread())

    def test_voz_drains_stderr_handles_unicode_and_reuses_process(self):
        worker = Transcriber()
        self.addCleanup(worker.close)
        popen = subprocess.Popen
        code = """
import json, sys
print('runtime diagnostic', flush=True)
sys.stderr.write('warning\\n' * 20000); sys.stderr.flush()
print(json.dumps({'event': 'ready'}), flush=True)
for line in sys.stdin:
    print(json.dumps({'event':'result','text':'Hello café.'}, ensure_ascii=False), flush=True)
"""
        def launch(*args, **kwargs):
            kwargs.pop("cwd", None)
            return popen([sys.executable, "-X", "utf8", "-u", "-c", code], **kwargs)
        with patch("neyra.stt.subprocess.Popen", side_effect=launch):
            for _ in range(2):
                chunks = queue.Queue()
                chunks.put(np.ones(1600, dtype=np.float32)); chunks.put(None)
                self.assertEqual(worker._run_voz(chunks), "Hello café.")
        self.assertTrue(worker._voz_ready)

    def test_voz_failure_discards_process_and_allows_retry(self):
        worker = Transcriber()
        self.addCleanup(worker.close)
        with patch.object(worker, "_start_voz", side_effect=RuntimeError("load failed")):
            chunks = queue.Queue(); chunks.put(np.ones(160)); chunks.put(None)
            with self.assertRaisesRegex(RuntimeError, "load failed"):
                worker._run_voz(chunks)
        self.assertIsNone(worker._voz_process)
        self.assertFalse(worker._voz_ready)
        chunks = queue.Queue(); chunks.put(None)
        self.assertEqual(worker._run_voz(chunks), "")

    def test_paste_waits_for_shortcut_modifiers_to_release(self):
        assistant = self.make_assistant()
        assistant.hotkeys = Mock()
        assistant._pending_paste = "Hello"
        assistant.hotkeys.modifiers_active.return_value = True
        with patch("neyra.main.insert_text") as paste:
            assistant.paste_when_released()
            paste.assert_not_called()
            assistant.hotkeys.modifiers_active.return_value = False
            assistant.paste_when_released()
            paste.assert_called_once_with("Hello")


if __name__ == "__main__":
    unittest.main()
