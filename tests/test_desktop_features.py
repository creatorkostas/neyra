"""Device selection, recording controls, local data and per-user login entries."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
import numpy as np
from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox
from neyra.audio import Microphone, input_devices
from neyra.main import Assistant, HistoryDashboard, load_records
from neyra.stt import Transcriber
from neyra import startup

APP = QApplication.instance() or QApplication([])


class DesktopFeatures(unittest.TestCase):
    def test_long_combo_labels_do_not_expand_the_layout(self):
        from neyra.ui import DashboardComboBox
        combo = DashboardComboBox()
        self.addCleanup(combo.close)
        combo.addItem("Default microphone")
        width = combo.sizeHint().width()
        label = "A very long microphone or account name " * 30
        combo.addItem(label)
        combo.setCurrentIndex(1)
        self.assertEqual(combo.sizeHint().width(), width)
        self.assertEqual(combo.toolTip(), label)

    def setUp(self):
        speech = patch("neyra.assistant_features.PiperSpeech")
        speech.start()
        self.addCleanup(speech.stop)
        mute = patch("neyra.main.SpeakerMute")
        mute.start()
        self.addCleanup(mute.stop)
        folder = tempfile.TemporaryDirectory(prefix="neyra-desktop-")
        self.addCleanup(folder.cleanup)
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, folder.name)
        for target, value in (
            ("neyra.main.input_devices", [(7, "USB mic (WASAPI)")]),
            ("neyra.startup.is_enabled", False),
            ("neyra.stt.Transcriber.prepare_whistle", None),
            ("neyra.stt.Transcriber.prepare_voz", None),
        ):
            patcher = patch(target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def dashboard(self):
        window = HistoryDashboard()
        self.addCleanup(window.close)
        return window

    def assistant(self):
        with patch("neyra.hotkeys.Hotkeys.start"), patch("neyra.main.QSystemTrayIcon.show"):
            assistant = Assistant(APP)
        self.addCleanup(assistant.cleanup)
        assistant.engine.run = Mock()
        return assistant

    def test_saved_microphone_survives_device_reordering_and_reports_disconnection(self):
        window = self.dashboard()
        window.mic_choice.setCurrentIndex(1)
        with patch("neyra.main.input_devices", return_value=[(12, "USB mic (WASAPI)")]):
            window.refresh_microphones()
        self.assertEqual(window.selected_microphone(), 12)
        with patch("neyra.main.input_devices", return_value=[]):
            window.refresh_microphones()
        with self.assertRaisesRegex(RuntimeError, "unavailable"):
            window.selected_microphone()
        self.assertIn("unavailable", window.mic_status.text())

    def test_device_listing_filters_output_only_devices(self):
        with patch("neyra.audio.sd.query_hostapis", return_value=[{"name": "ALSA"}]), patch(
            "neyra.audio.sd.query_devices", return_value=[
                {"name": "Speaker", "hostapi": 0, "max_input_channels": 0},
                {"name": "Mic", "hostapi": 0, "max_input_channels": 1},
            ]):
            self.assertEqual(input_devices(), [(1, "Mic (ALSA)")])

    def test_meter_test_discards_audio_and_uses_selected_input(self):
        levels = []
        mic = Microphone(None, levels.append, device=7)
        with patch("neyra.audio.sd.InputStream") as stream:
            mic.start()
            callback = stream.call_args.kwargs["callback"]
            callback(np.full((20, 1), 0.25, dtype=np.float32), 20, None, None)
            self.assertEqual(stream.call_args.kwargs["device"], 7)
            self.assertAlmostEqual(levels[0], 0.25)
            mic.stop()
            stream.return_value.close.assert_called_once()

    def test_real_recording_stops_meter_test_and_updates_controls(self):
        assistant = self.assistant()
        assistant.history.mic_choice.setCurrentIndex(1)
        meter, recording = Mock(), Mock()
        with patch("neyra.main.Microphone", side_effect=[meter, recording]) as create:
            assistant.toggle_microphone_test()
            self.assertIs(assistant.mic_test, meter)
            assistant.start()
            meter.stop.assert_called_once()
            self.assertEqual(create.call_args.kwargs["device"], 7)
            self.assertTrue(assistant.recording)
            self.assertEqual(assistant.history.capture.record_button.text(), "Stop and transcribe")
            self.assertFalse(assistant.history.mic_choice.isEnabled())
            assistant.stop()
            self.assertFalse(assistant.history.capture.record_button.isEnabled())
            assistant.complete("New transcript")
            self.assertTrue(assistant.history.capture.record_button.isEnabled())
            self.assertTrue(assistant.history.mic_choice.isEnabled())

    def test_history_clear_requires_confirmation_and_preserves_meetings(self):
        window = self.dashboard()
        window.add_transcript("Keep until confirmed")
        window.add_meeting("Meeting stays")
        with patch("neyra.main.QMessageBox.question", return_value=QMessageBox.StandardButton.No):
            window.clear_history()
        self.assertEqual(len(window.records), 1)
        with patch("neyra.main.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
            window.clear_history()
        self.assertEqual(load_records(window.settings, "history"), [])
        self.assertEqual(len(load_records(window.settings, "meetings")), 1)
        self.assertFalse(window.clear_history_button.isEnabled())
        window.save_history_toggle.setChecked(False)
        window.add_transcript("Do not persist")
        self.assertEqual(window.records, [])
        self.assertFalse(self.dashboard().save_history_toggle.isChecked())

    def test_vocabulary_corrections_apply_to_dictation_before_snippets(self):
        assistant = self.assistant()
        window = assistant.history
        window.correction_heard.setText("near a")
        window.correction_written.setText("Neyra")
        window.save_correction()
        window.style_choice.setCurrentText("Natural")
        assistant.complete("near a works; near able stays.")
        self.assertEqual(assistant.last_text, "Neyra works; near able stays.")
        self.assertEqual(window.dictionary_words(), [])
        window.correction_heard.setText("NEAR A")
        window.correction_written.setText("NEYRA")
        window.save_correction()
        self.assertEqual(len(window.vocabulary_corrections()), 1)
        window.corrections_table.selectRow(0)
        window.remove_correction()
        self.assertEqual(window.vocabulary_corrections(), {})

    def test_model_progress_belongs_to_its_engine(self):
        window = self.dashboard()
        window.set_model_status("voz", "downloading", "Downloading encoder · 25 / 100 MB", 25)
        self.assertNotIn("encoder", window.capture.model_detail.text())
        window.engine_choice.setCurrentIndex(1)
        self.assertEqual(window.capture.progress.value(), 25)
        self.assertIn("Downloading", window.capture.model_badge.text())
        window.set_model_status("voz", "error", "Connection refused", -1)
        self.assertTrue(window.retry_model_button.isEnabled())
        self.assertTrue(window.capture.progress.isHidden())

    def test_closing_window_stops_test_and_respects_tray_preference(self):
        assistant = self.assistant()
        assistant.mic_test = Mock()
        meter = assistant.mic_test
        with patch("neyra.main.QSystemTrayIcon.isSystemTrayAvailable", return_value=True), patch.object(APP, "quit") as quit_app:
            assistant.dashboard_closed()
            meter.stop.assert_called_once()
            quit_app.assert_not_called()
            assistant.history.close_to_tray_toggle.setChecked(False)
            assistant.dashboard_closed()
            quit_app.assert_called_once()

    def test_escape_stops_microphone_test_through_normal_close_handling(self):
        assistant = self.assistant()
        assistant.mic_test = meter = Mock()
        with patch("neyra.main.QSystemTrayIcon.isSystemTrayAvailable", return_value=True), patch.object(APP, "quit") as quit_app:
            assistant.history.show()
            APP.processEvents()
            QTest.keyClick(assistant.history, Qt.Key.Key_Escape)
            self.assertFalse(assistant.history.isVisible())
            meter.stop.assert_called_once()
            quit_app.assert_not_called()

    def test_history_disabled_still_copies_result_without_pasting_into_dashboard(self):
        assistant = self.assistant()
        assistant.history.save_history_toggle.setChecked(False)
        assistant.history.style_choice.setCurrentText("Natural")
        assistant._paste_on_complete = False
        assistant.complete("Available on clipboard")
        self.assertEqual(APP.clipboard().text(), "Available on clipboard")
        self.assertEqual(assistant.history.records, [])
        self.assertFalse(assistant.paste_timer.isActive())
        self.assertTrue(assistant.copy_action.isEnabled())

    def test_deleting_current_transcript_forgets_tray_copy_and_pending_paste(self):
        assistant = self.assistant()
        assistant.complete("Forget this transcript")
        record = assistant.history.records[-1]
        self.assertTrue(assistant.copy_action.isEnabled())
        assistant.history.delete_transcript(record)
        self.assertEqual(assistant.last_text, "")
        self.assertEqual(assistant._pending_paste, "")
        self.assertFalse(assistant.paste_timer.isActive())
        self.assertFalse(assistant.copy_action.isEnabled())

    def test_deleting_old_record_keeps_current_unsaved_result(self):
        assistant = self.assistant()
        old = assistant.history.add_transcript("Saved earlier")
        assistant.history.save_history_toggle.setChecked(False)
        assistant.complete("Current unsaved result")
        assistant.history.delete_transcript(old)
        self.assertEqual(assistant.last_text, "Current unsaved result.")
        self.assertTrue(assistant.copy_action.isEnabled())


class RuntimeAndStartup(unittest.TestCase):
    def test_voz_preload_and_first_recording_share_one_runtime(self):
        worker = Transcriber()
        self.addCleanup(worker.close)
        statuses = []
        worker.model_status.connect(lambda *args: statuses.append(args))
        engine = Mock()
        def load(progress, closed):
            progress("downloading", "encoder", 25)
            return engine
        with patch("neyra.voz.VozEngine", side_effect=load) as loaded:
            worker.prepare_voz()
            runtime = worker._start_voz()
            worker._voz_prepare_thread.join(timeout=2)
            self.assertIs(runtime, worker._start_voz())
            self.assertEqual(loaded.call_count, 1)
        APP.processEvents()
        self.assertTrue(worker._voz_ready)
        self.assertTrue(any(state == "downloading" and percent == 25 for _, state, _, percent in statuses))
        self.assertEqual(statuses[-1][1], "ready")

    def test_linux_autostart_quotes_paths_and_removes_only_its_entry(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(startup.sys, "platform", "linux"), patch.dict(os.environ, {"XDG_CONFIG_HOME": folder}), patch(
            "neyra.startup.application_command", return_value=['/opt/My $App/100%/Neyra', '--background']):
            startup.set_enabled(True)
            path = Path(folder) / "autostart" / "neyra.desktop"
            self.assertIn('Exec="/opt/My \\\\$App/100%%/Neyra" "--background"', path.read_text())
            self.assertTrue(startup.is_enabled())
            unrelated = path.parent / "other.desktop"
            unrelated.write_text("keep")
            startup.set_enabled(False)
            self.assertFalse(startup.is_enabled())
            self.assertEqual(unrelated.read_text(), "keep")

    def test_windows_autostart_changes_only_neyra_run_value(self):
        registry = MagicMock()
        command = [r"C:\My Apps\Neyra.exe", "--background"]
        with patch.object(startup.sys, "platform", "win32"), patch.dict(sys.modules, {"winreg": registry}), patch("neyra.startup.application_command", return_value=command):
            startup.set_enabled(True)
            self.assertEqual(registry.SetValueEx.call_args.args[1:],
                             ("Neyra", 0, registry.REG_SZ, subprocess.list2cmdline(command)))
            startup.set_enabled(False)
            self.assertEqual(registry.DeleteValue.call_args.args[1], "Neyra")

    def test_packaged_autostart_points_at_original_executable(self):
        with patch.object(startup.sys, "frozen", True, create=True), patch.object(sys, "argv", [r"C:\Apps\Neyra.exe"]):
            self.assertEqual(startup.application_command(), [str(Path(sys.argv[0]).resolve()), "--background"])


if __name__ == "__main__":
    unittest.main()
