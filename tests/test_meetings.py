"""Meeting timing, speaker attribution, recovery, and model protocol checks."""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
import numpy as np
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QPushButton, QTableWidget
from neyra.main import Assistant, HistoryDashboard, load_records
from neyra.meeting import MeetingModels, label_words, meeting_transcript, timestamp, validated_words
from neyra.stt import Transcriber

APP = QApplication.instance() or QApplication([])


class MeetingTests(unittest.TestCase):
    def setUp(self):
        self.settings_dir = tempfile.TemporaryDirectory(prefix="neyra-meetings-")
        self.addCleanup(self.settings_dir.cleanup)
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, self.settings_dir.name)
        QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope, "Neyra", "Neyra").clear()

    def test_speaker_turns_keep_overlap_and_unknown_words(self):
        words = validated_words([
            {"text": "First", "start": 0, "end": 1},
            {"text": "both", "start": 1, "end": 2},
            {"text": "unknown", "start": 3, "end": 4},
        ], 4)
        label_words(words, [{"speaker": 0, "start": 0, "end": 2}, {"speaker": 1, "start": 1, "end": 2}])
        self.assertEqual([word["speakers"] for word in words], [[0], [0, 1], []])
        text = meeting_transcript({"text": "First both unknown", "words": words, "speaker_labels": True})
        self.assertIn("Speaker 1 + Speaker 2: both", text)
        self.assertIn("Speaker unknown: unknown", text)
        self.assertEqual(timestamp(3661.234), "01:01:01.234")

    def test_invalid_timings_rejected(self):
        for start, end in ((float("nan"), 1), (0, float("inf")), (-1, 1), (2, 1), (0, 10), (True, 1)):
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                validated_words([{"text": "word", "start": start, "end": end}], 2)

    def test_toggles_and_language_persist_and_lock_while_recording(self):
        dashboard = HistoryDashboard()
        self.addCleanup(dashboard.close)
        panel = dashboard.notetaker
        panel.speaker_toggle.setChecked(True)
        panel.cleanup_toggle.setChecked(True)
        panel.organize_toggle.setChecked(False)
        panel.language_choice.setCurrentIndex(panel.language_choice.findData("de"))
        panel.set_state("recording")
        self.assertFalse(panel.cleanup_toggle.isEnabled())
        self.assertFalse(panel.language_choice.isEnabled())
        reopened = HistoryDashboard()
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.notetaker.processing_options(), {"speakers": True, "cleanup": True, "organize": False, "language": "de"})

    def test_notes_search_titles_topics_and_save_timestamps(self):
        dashboard = HistoryDashboard()
        self.addCleanup(dashboard.close)
        metadata = {"title": "Release review", "topics": [{"slug": "technology", "name": "Technology"}],
                    "words": [{"text": "Hello", "start": 0.1, "end": 0.4, "refined": True, "speakers": [0]}],
                    "speaker_labels": True, "timestamp_model": "align"}
        dashboard.add_meeting("Hello", metadata)
        for query in ("release", "technology"):
            dashboard.notetaker.search.setText(query)
            labels = dashboard.notetaker.feed.widget().findChildren(QLabel)
            self.assertTrue(any("Release review" == label.text() for label in labels))
        persisted = load_records(dashboard.settings, "meetings")[0]
        self.assertEqual(persisted["words"], metadata["words"])
        def inspect(dialog):
            table = dialog.findChild(QTableWidget)
            self.assertEqual(table.item(0, 1).text(), "00:00:00.100")
            self.assertEqual(table.item(0, 3).text(), "Speaker 1")
            dialog.findChild(QLineEdit).setText("Renamed meeting")
            next(button for button in dialog.findChildren(QPushButton) if button.text() == "Save title").click()
            return 0
        with patch("neyra.ui.QDialog.exec", new=inspect):
            dashboard.notetaker.open_meeting(dashboard.meeting_records[0])
        self.assertEqual(load_records(dashboard.settings, "meetings")[0]["title"], "Renamed meeting")

    def test_invalid_saved_metadata_keeps_plain_transcript_usable(self):
        settings = QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope, "Neyra", "Neyra")
        settings.setValue("meetings", json.dumps([{"text": "Keep this transcript", "time": "2026-10-19T12:00:00", "title": 42,
            "words": [{"text": "Bad", "start": "oops", "end": 2}], "topics": [None], "warnings": 123}]))
        dashboard = HistoryDashboard()
        self.addCleanup(dashboard.close)
        record = dashboard.meeting_records[0]
        self.assertEqual(meeting_transcript(record), "Keep this transcript")
        self.assertEqual(record["topics"], [])

    def test_missing_runtime_does_not_start_capture(self):
        with patch("neyra.hotkeys.Hotkeys.start"), patch("neyra.main.QSystemTrayIcon.show"):
            assistant = Assistant(APP)
        self.addCleanup(assistant.cleanup)
        with patch("neyra.main.bridge_path", side_effect=RuntimeError("Run setup_meeting_models.py")), patch("neyra.main.Microphone") as microphone:
            assistant.start_notetaker()
        microphone.assert_not_called()
        self.assertIn("setup_meeting_models", assistant.history.notetaker_status.text())
        self.assertFalse(assistant.notetaker_active)

    def test_dashboard_settings_are_isolated_in_test_directory(self):
        dashboard = HistoryDashboard()
        self.addCleanup(dashboard.close)
        self.assertEqual(dashboard.settings.format(), QSettings.Format.IniFormat)
        self.assertTrue(Path(dashboard.settings.fileName()).is_relative_to(Path(self.settings_dir.name)))

    def test_processing_failure_keeps_recording_for_retry(self):
        with patch("neyra.hotkeys.Hotkeys.start"), patch("neyra.main.QSystemTrayIcon.show"):
            assistant = Assistant(APP)
        self.addCleanup(assistant.cleanup)
        assistant._meeting_audio = np.ones(1600, dtype=np.float32)
        assistant.engine.run = Mock(side_effect=RuntimeError("model unavailable"))
        assistant.process_meeting()
        self.assertIsNotNone(assistant._meeting_audio)
        self.assertFalse(assistant.history.notetaker.retry_button.isHidden())
        self.assertFalse(assistant.history.notetaker.start_button.isEnabled())
        assistant.engine.run.side_effect = None
        assistant.history.notetaker.speaker_toggle.setChecked(True)
        assistant.history.notetaker.retry_button.click()
        self.assertTrue(assistant.processing)
        self.assertTrue(assistant.engine.run.call_args.kwargs["meeting_options"]["speakers"])
        assistant.engine.meeting_result = {"words": [], "title": "Keep um literally"}
        assistant.history.style_choice.setCurrentText("Clean up speech")
        assistant.complete("Keep um literally")
        self.assertIsNone(assistant._meeting_audio)
        self.assertEqual(assistant.history.meeting_records[-1]["text"], "Keep um literally")

    def test_recorder_stop_failure_preserves_available_microphone_audio(self):
        with patch("neyra.hotkeys.Hotkeys.start"), patch("neyra.main.QSystemTrayIcon.show"):
            assistant = Assistant(APP)
        self.addCleanup(assistant.cleanup)
        assistant.notetaker_active = True
        assistant.notetaker_chunks = queue.Queue()
        assistant.notetaker_chunks.put(np.ones(1600, dtype=np.float32))
        assistant.notetaker_chunks.put(None)
        assistant.notetaker_mic = Mock()
        assistant.system_audio = Mock()
        assistant.system_audio.stop.side_effect = RuntimeError("loopback disconnected")
        assistant.engine.run = Mock()
        assistant.stop_notetaker()
        self.assertEqual(len(assistant._meeting_audio), 1600)
        self.assertFalse(assistant.history.notetaker.retry_button.isHidden())
        assistant.engine.run.assert_not_called()
        assistant.history.notetaker.retry_button.click()
        assistant.engine.run.assert_called_once()
        assistant.engine.meeting_result = {"words": []}
        assistant.complete("Microphone transcript")
        self.assertIn("loopback disconnected", assistant.history.meeting_records[-1]["warnings"][0])

    def test_voz_pipeline_uses_cleaned_audio_align_and_optional_models(self):
        worker = Transcriber()
        self.addCleanup(worker.close)
        words = [{"text": "Hello", "start": 0, "end": 0.5}]
        process = Mock()
        process.poll.return_value = None
        worker._start_voz = Mock(return_value=process)
        worker._read_voz_event = Mock(return_value={"event": "result", "text": "Hello", "words": words})
        paths = []
        def models(request, *args, **kwargs):
            if request["operation"] == "check":
                return {"capabilities": ["align", "clear", "who", "gist"]}
            paths.append(request["path"])
            if request["operation"] == "enhance":
                Path(request["output_path"]).write_bytes(Path(request["path"]).read_bytes())
                return {"path": request["output_path"]}
            self.assertEqual(request["language"], "fr")
            self.assertTrue(request["speakers"])
            self.assertTrue(request["organize"])
            return {"words": [{**words[0], "start": 0.02, "refined": True}], "turns": [{"speaker": 0, "start": 0, "end": 0.6}], "topics": [{"name": "Technology", "slug": "technology"}]}
        worker.meeting_models.request = Mock(side_effect=models)
        chunks = queue.Queue()
        chunks.put(np.ones(16000, dtype=np.float32)); chunks.put(None)
        self.assertEqual(worker._run_voz(chunks, {"speakers": True, "cleanup": True, "organize": True, "language": "fr"}), "Hello")
        self.assertTrue(paths[1].endswith("-clean.wav"))
        self.assertEqual(json.loads(process.stdin.write.call_args.args[0])["path"], paths[1])
        self.assertEqual(worker.meeting_result["words"][0]["speakers"], [0])
        self.assertEqual(worker.meeting_result["timestamp_model"], "align")
        self.assertTrue(all(not Path(path).exists() for path in paths))

    def test_disabled_optional_models_are_not_requested(self):
        worker = Transcriber()
        self.addCleanup(worker.close)
        words = [{"text": "Hello", "start": 0, "end": 0.5}]
        process = Mock(); process.poll.return_value = None
        worker._start_voz = Mock(return_value=process)
        worker._read_voz_event = Mock(return_value={"event": "result", "text": "Hello", "words": words})
        worker.meeting_models.request = Mock(side_effect=[{"capabilities": ["align"]}, {"words": words}])
        chunks = queue.Queue(); chunks.put(np.ones(16000)); chunks.put(None)
        worker._run_voz(chunks, {"speakers": False, "cleanup": False, "organize": False})
        request = worker.meeting_models.request.call_args.args[0]
        self.assertFalse(request["speakers"])
        self.assertFalse(request["organize"])
        self.assertEqual(worker.meeting_result["topics"], [])
        self.assertEqual(worker.meeting_result["title"], "")

    def test_failed_cleanup_removes_partial_native_audio(self):
        worker = Transcriber()
        self.addCleanup(worker.close)
        partial_paths = []
        def models(request, *args, **kwargs):
            if request["operation"] == "check":
                return {"capabilities": ["align", "clear"]}
            partial = Path(request["output_path"]).parent / ".neyra-partial.wav"
            partial.write_bytes(b"partial audio")
            partial_paths.append(partial)
            raise RuntimeError("Clear failed")
        worker.meeting_models.request = Mock(side_effect=models)
        chunks = queue.Queue(); chunks.put(np.ones(16000)); chunks.put(None)
        with self.assertRaisesRegex(RuntimeError, "Clear failed"):
            worker._run_voz(chunks, {"cleanup": True})
        self.assertTrue(partial_paths)
        self.assertFalse(partial_paths[0].parent.exists())

    def test_native_bridge_drains_diagnostics_and_preserves_unicode(self):
        bridge = MeetingModels()
        self.addCleanup(bridge.close)
        popen = subprocess.Popen
        code = "import json,sys; r=json.loads(sys.stdin.readline()); sys.stderr.write('warning\\n'*20000); sys.stderr.flush(); print(json.dumps({'event':'progress','message':'Analyzing'}),flush=True); print(json.dumps({'event':'result','text':'café'}),flush=True)"
        def launch(*args, **kwargs):
            kwargs.pop("cwd", None)
            return popen([sys.executable, "-u", "-c", code], **kwargs)
        progress = []
        with patch("neyra.meeting.bridge_path", return_value=Path(sys.executable)), patch("neyra.meeting.subprocess.Popen", side_effect=launch):
            result = bridge.request({"operation": "check"}, progress.append, timeout=5)
        self.assertEqual(result["text"], "café")
        self.assertEqual(progress, ["Analyzing"])
        self.assertIsNone(bridge._process)

    def test_native_bridge_shutdown_interrupts_processing(self):
        bridge = MeetingModels()
        popen = subprocess.Popen
        code = "import sys,time; sys.stdin.readline(); time.sleep(30)"
        def launch(*args, **kwargs):
            kwargs.pop("cwd", None)
            return popen([sys.executable, "-u", "-c", code], **kwargs)
        errors = []
        def run():
            try:
                bridge.request({"operation": "check"})
            except RuntimeError as exc:
                errors.append(str(exc))
        with patch("neyra.meeting.bridge_path", return_value=Path(sys.executable)), patch("neyra.meeting.subprocess.Popen", side_effect=launch):
            thread = threading.Thread(target=run)
            thread.start()
            deadline = time.monotonic() + 3
            while bridge._process is None and time.monotonic() < deadline:
                time.sleep(0.01)
            bridge.close()
            thread.join(timeout=3)
        self.assertFalse(thread.is_alive())
        self.assertTrue(errors)

    def test_meeting_tools_do_not_override_whistle_runtime(self):
        from neyra.bundled import configure_bundled_runtime
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "assets" / "meeting-models").mkdir(parents=True)
            with patch("neyra.bundled.__file__", str(root / "neyra" / "bundled.py")), patch.dict(os.environ, {}, clear=True):
                configure_bundled_runtime()
                self.assertNotIn("NEEDLE_WHISTLE_WEIGHTS", os.environ)

    def test_build_excludes_toolchain_installers(self):
        from scripts import build
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            assets = root / "assets"
            assets.mkdir()
            (root / "node_modules").mkdir()
            for name in ("model", "engine", "meeting-models", "tools"):
                (assets / name).mkdir()
            with patch.object(build, "ROOT", root), patch.object(build, "ASSETS", assets), patch.object(build, "run") as run, patch("neyra.bundled.configure_bundled_runtime"), patch.object(sys, "argv", ["build.py", "--skip-download"]):
                build.main()
            command = run.call_args.args
            included = [arg for arg in command if str(arg).startswith(("--include-data-dir=", "--include-raw-dir="))]
            self.assertEqual({str(arg).rsplit("=", 1)[-1] for arg in included},
                             {"assets/model", "assets/engine", "assets/meeting-models", "node_modules"})
            self.assertFalse(any("tools" in str(arg) for arg in included))


if __name__ == "__main__":
    unittest.main()
