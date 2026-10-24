"""Assistant routes, privacy boundaries, and reviewed reminder creation."""
import os
import json
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
        speech = patch("neyra.assistant_features.PiperSpeech")
        speech.start()
        self.addCleanup(speech.stop)
        mute = patch("neyra.main.SpeakerMute")
        mute.start()
        self.addCleanup(mute.stop)
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

    def test_assistant_reveals_controls_only_for_the_current_step(self):
        self.assertTrue(self.panel.language.isHidden())
        self.panel.selection_mode.setCurrentText("Translate")
        self.assertFalse(self.panel.language.isHidden())
        self.panel.selection_mode.setCurrentText("Summarize")
        self.assertTrue(self.panel.language.isHidden())
        self.assertEqual(self.panel.explain.text(), "Summarize with ChatGPT")
        self.assertTrue(self.panel.selection_answer.isHidden())
        self.panel.selection_answer.setPlainText("A concise result.")
        self.assertFalse(self.panel.selection_answer.isHidden())
        self.assertTrue(self.panel.agenda_form.isHidden())
        self.panel.edit_plans.click()
        self.assertFalse(self.panel.agenda_form.isHidden())
        self.assertTrue(self.panel.action_form.isHidden())
        self.owner.history.records.append({"text": "Create a PR template.", "time": "2026-10-24T12:00:00"})
        self.panel.question.setText("PR")
        self.features.find_notes()
        self.assertFalse(self.panel.sources.isHidden())
        self.assertFalse(self.panel.ask.isHidden())
        self.client.respond.assert_not_called()
        self.panel.question.setText("unmatchedword")
        self.features.find_notes()
        self.assertTrue(self.panel.sources.isHidden())
        self.assertTrue(self.panel.ask.isHidden())
        self.assertIn("No matching notes", self.panel.status.text())

    def test_voice_selection_copies_before_showing_and_requires_explicit_send(self):
        with patch.object(self.features, "capture_selection") as capture, patch.object(self.features, "show") as show:
            self.features.command("summarize selected text")
            capture.assert_called_once()
            show.assert_not_called()
        self.assertEqual(self.panel.selection_mode.currentText(), "Summarize")
        self.client.respond.assert_not_called()
        self.panel.selection.setPlainText("Text intentionally selected for review.")
        self.client.respond.return_value = "Summary."
        self.features.command("send this text")
        self.finish_job()
        self.assertEqual(self.panel.selection_answer.toPlainText(), "Summary.")
        self.assertIn("Summarize", self.client.respond.call_args.args[0])

    def test_voice_note_search_then_explicit_answer(self):
        self.owner.history.records.append({"text": "Create a PR template.", "time": "2026-10-24T12:00:00"})
        self.features.command("ask my notes PR")
        self.assertIn("PR template", self.panel.sources.toPlainText())
        self.client.respond.assert_not_called()
        self.client.respond.return_value = "Create the template [1]."
        self.features.command("answer from these notes")
        self.finish_job()
        self.assertIn("[1]", self.panel.knowledge_answer.toPlainText())

    def test_voice_meeting_tasks_and_numbered_reminder(self):
        self.owner.history.add_meeting("Alex will send slides.", {"title": "Planning"})
        self.features.command("follow-ups for the latest meeting")
        self.client.respond.assert_not_called()
        self.client.respond.return_value = '[{"text":"Send slides","evidence":"Alex will send slides."}]'
        self.features.command("find tasks")
        self.finish_job()
        self.assertEqual(len(self.features.actions), 1)
        self.assertEqual(self.owner.reminder_store.records, [])
        self.features.command("schedule task one in an hour")
        self.assertEqual(len(self.owner.reminder_store.records), 1)
        self.assertEqual(self.owner.reminder_store.records[0]["text"], "Send slides")
        self.features.command("schedule task one in an hour")
        self.assertEqual(len(self.owner.reminder_store.records), 1)
        self.features.command("schedule task nine in an hour")
        self.assertEqual(len(self.owner.reminder_store.records), 1)

    def test_voice_agenda_and_reading_need_no_chatgpt(self):
        self.features.command("add a plan in an hour to Call Alex")
        self.assertEqual(self.features.agenda.records[0]["text"], "Call Alex")
        self.features.command("show today")
        self.assertEqual(self.panel.tabs.currentIndex(), 4)
        self.features.command("remove plan one")
        self.assertEqual(self.features.agenda.records, [])
        self.features.speech = Mock()
        self.features.command("stop reading")
        self.features.speech.stop.assert_called_once()
        self.client.respond.assert_not_called()

    def connect_intent_account(self):
        self.client.active_id = "connected"
        self.client.accounts.return_value = [{"id": "connected", "connected": True, "label": "Test"}]

    def test_natural_request_is_interpreted_then_dispatched_without_private_context(self):
        self.connect_intent_account()
        self.panel.selection.setPlainText("Private selected content")
        self.owner.history.records.append({"text": "Private saved content", "time": "2026-10-24T12:00:00"})
        self.client.respond.return_value = '{"command":"show today"}'
        self.features.command("Could you show me what my day looks like?")
        self.finish_job()
        QTest.qWait(20)
        self.assertEqual(self.panel.tabs.currentIndex(), 4)
        sent = self.client.respond.call_args.args[1]
        self.assertIn("what my day looks like", sent)
        self.assertNotIn("Private selected content", sent)
        self.assertNotIn("Private saved content", sent)
        self.assertEqual(self.client.respond.call_count, 1)

    def test_natural_selection_does_not_focus_dashboard_before_capture(self):
        self.connect_intent_account()
        self.client.respond.return_value = '{"command":"summarize selected text"}'
        with patch.object(self.features, "capture_selection") as capture, patch.object(self.features, "show") as show:
            self.features.command("Can you shorten the text I highlighted?")
            self.finish_job()
            QTest.qWait(20)
            capture.assert_called_once()
            show.assert_not_called()
        self.assertEqual(self.client.respond.call_count, 1)

    def test_bad_ai_intent_and_missing_preview_execute_nothing(self):
        self.connect_intent_account()
        for answer in ('{"command":"run powershell"}', '{"command":"send this text"}'):
            self.client.respond.return_value = answer
            self.features.command("Do something for me")
            self.finish_job()
            QTest.qWait(20)
            self.assertEqual(self.owner.reminder_store.records, [])
            self.assertFalse(self.features.intent_pending)
        self.assertIn("review first", self.panel.status.text())

    def test_intent_clarification_keeps_previous_request_for_next_utterance(self):
        self.connect_intent_account()
        self.client.respond.return_value = '{"clarification":"How long from now?"}'
        self.features.command("I need to remember to call Alex")
        self.finish_job()
        self.assertIn("How long", self.panel.status.text())
        self.client.respond.return_value = '{"command":"show today"}'
        self.features.command("In about an hour")
        self.finish_job()
        QTest.qWait(20)
        self.assertIn("remember to call Alex", self.client.respond.call_args.args[1])
        self.assertIsNone(self.features.intent_clarification)

    def test_cancelled_interpretation_does_not_dispatch(self):
        self.connect_intent_account()
        def respond(*args, **kwargs):
            self.features.job.cancelled.set()
            return '{"command":"show today"}'
        self.client.respond.side_effect = respond
        with patch.object(self.features, "refresh_briefing") as refresh:
            self.features.command("How is my day looking?")
            self.finish_job()
            self.assertFalse(self.features.intent_pending)
            self.assertIn("Cancelled", self.panel.status.text())
            self.assertEqual(self.panel.tabs.currentIndex(), 0)
        self.client.respond.side_effect = None

    def test_account_usage_labels_do_not_fabricate_quota_and_analytics_uses_active_account(self):
        self.connect_intent_account()
        self.features.get_client()
        self.client.usage_error = ""
        self.client.analytics.snapshot.return_value = {"input_tokens": 20, "output_tokens": 5, "total_tokens": 25, "requests": 1}
        self.features.refresh_accounts()
        self.assertIn("Unavailable", self.panel.five_hour_usage.text())
        self.assertIn("Unavailable", self.owner.history.account_weekly_usage.text())
        self.client.analytics.snapshot.assert_called_with("connected")
        self.assertEqual(self.owner.history.analytics_usage["total_tokens"], 25)
        self.client.active_id = None
        self.features.refresh_accounts()
        self.assertIn("Not connected", self.panel.weekly_usage.text())
        self.assertNotIn("total_tokens", self.owner.history.analytics_usage)

    def test_identical_read_only_results_reuse_cache_but_changes_do_not(self):
        self.connect_intent_account()
        self.features.get_client()
        self.panel.selection.setPlainText("Text to explain.")
        self.client.respond.return_value = "An explanation."
        self.features.explain()
        self.finish_job()
        self.features.explain()
        self.assertEqual(self.client.respond.call_count, 1)
        self.assertIn("No new ChatGPT request", self.panel.status.text())
        self.panel.selection.setPlainText("Different text.")
        self.features.explain()
        self.finish_job()
        self.assertEqual(self.client.respond.call_count, 2)
        self.client.active_id = "another-account"
        self.features.explain()
        self.finish_job()
        self.assertEqual(self.client.respond.call_count, 3)
        self.features.invalidate_sources()
        self.features.explain()
        self.finish_job()
        self.assertEqual(self.client.respond.call_count, 4)

    def test_failed_results_are_not_cached(self):
        self.connect_intent_account()
        self.features.get_client()
        self.panel.selection.setPlainText("Text to explain.")
        self.client.respond.side_effect = RuntimeError("Request failed")
        self.features.explain()
        self.finish_job()
        self.features.explain()
        self.finish_job()
        self.assertEqual(self.client.respond.call_count, 2)
        self.assertEqual(len(self.features.response_cache.entries), 0)
        self.client.respond.side_effect = None

    def test_voice_answers_use_piper_and_spoken_prompt_but_typed_answers_do_not(self):
        self.panel.selection.setPlainText("A short selected passage.")
        self.client.respond.return_value = "A brief spoken explanation."
        self.features.command("send this text", spoken=True)
        self.finish_job()
        self.assertIn("will be heard aloud", self.client.respond.call_args.args[0])
        self.features.speech.speak.assert_called_with("A brief spoken explanation.")
        self.features.speech.reset_mock()
        self.features.explain()
        self.finish_job()
        self.assertNotIn("will be heard aloud", self.client.respond.call_args.args[0])
        self.features.speech.speak.assert_not_called()

    def test_voice_toggle_disables_prompt_and_audio_and_persists(self):
        self.owner.history.spoken_answers_toggle.setChecked(False)
        self.assertFalse(self.owner.history.settings.value("spoken_assistant_answers", type=bool))
        self.panel.selection.setPlainText("A short passage.")
        self.client.respond.return_value = "A quiet answer."
        self.features.command("send this text", spoken=True)
        self.finish_job()
        self.assertNotIn("will be heard aloud", self.client.respond.call_args.args[0])
        self.assertIsNone(self.features.speech)

    def test_spoken_notes_use_verbal_sources_and_structured_followups_stay_json(self):
        self.owner.history.records.append({"text": "Launch Friday.", "time": "2026-10-24T12:00:00"})
        self.panel.question.setText("launch")
        self.features.find_notes()
        self.client.respond.return_value = "The launch is Friday, according to source one."
        self.features.command("answer from these notes", spoken=True)
        self.finish_job()
        self.assertIn("source one", self.client.respond.call_args.args[0])
        self.assertNotIn("[1]", self.client.respond.call_args.args[0])
        self.owner.history.add_meeting("Alex will send slides.", {"title": "Planning"})
        self.features.refresh_meetings()
        self.client.respond.return_value = '[{"text":"Send slides","evidence":"Alex will send slides."}]'
        self.features.command("find tasks", spoken=True)
        self.finish_job()
        self.assertIn("JSON array", self.client.respond.call_args.args[0])
        self.assertNotIn("will be heard aloud", self.client.respond.call_args.args[0])
        self.features.speech.speak.assert_called_with("Task 1. Send slides.")

    def test_new_recording_and_toggle_stop_speech_and_cleanup_closes_it(self):
        self.features.speak_answer("Hello")
        speech = self.features.speech
        self.owner.engine.run = Mock()
        with patch("neyra.main.Microphone", return_value=Mock()):
            self.owner.start("assistant")
        speech.stop.assert_called()
        self.owner.stop()
        speech.reset_mock()
        self.owner.history.spoken_answers_toggle.setChecked(False)
        speech.stop.assert_called_once()
        self.owner.cleanup()
        speech.close.assert_called_once()

    def test_releasing_assistant_recording_answers_notes_without_opening_ui(self):
        self.owner.history.records.append({"text": "The launch is Friday.", "time": "2026-10-24T12:00:00"})
        self.owner.engine.run = Mock()
        self.client.respond.return_value = "The launch is Friday."
        with patch.object(self.owner, "show_history") as show, patch("neyra.main.Microphone", return_value=Mock()):
            self.owner.start("assistant")
            self.owner.stop()
            self.owner.complete("ask my notes launch")
            self.finish_job()
            show.assert_not_called()
        self.client.respond.assert_called_once()
        self.features.speech.speak.assert_called_with("The launch is Friday.")

    def test_voice_selection_automatically_runs_tool_and_speaks_without_ui(self):
        self.client.respond.return_value = "A short summary."
        with patch.object(self.owner, "show_history") as show, patch.object(self.features, "capture_selection"):
            self.features.command("summarize selected text", spoken=True)
            self.features.selection_ready("The selected text from another app.")
            self.finish_job()
            show.assert_not_called()
        self.client.respond.assert_called_once()
        self.features.speech.speak.assert_called_with("A short summary.")

    def test_voice_followups_automatically_extract_without_an_extra_send(self):
        self.owner.history.add_meeting("Alex will send slides.", {"title": "Planning"})
        self.client.respond.return_value = '[{"text":"Send slides","evidence":"Alex will send slides."}]'
        with patch.object(self.owner, "show_history") as show:
            self.features.command("follow-ups for the latest meeting", spoken=True)
            self.finish_job()
            show.assert_not_called()
        self.client.respond.assert_called_once()
        self.features.speech.speak.assert_called_with("Task 1. Send slides.")
        self.assertEqual(self.owner.reminder_store.records, [])

    def test_general_voice_question_has_a_direct_spoken_answer(self):
        self.connect_intent_account()
        self.client.respond.return_value = '{"answer":"Photosynthesis is how plants use light to make food."}'
        with patch.object(self.owner, "show_history") as show:
            self.features.command("Can you explain photosynthesis?", spoken=True)
            self.finish_job()
            show.assert_not_called()
        self.client.respond.assert_called_once()
        self.assertTrue(json.loads(self.client.respond.call_args.args[1])["voice_mode"])
        self.features.speech.speak.assert_called_with("Photosynthesis is how plants use light to make food.")

    def test_voice_clarification_is_spoken_without_opening_ui(self):
        self.connect_intent_account()
        self.client.respond.return_value = '{"clarification":"When should I remind you?"}'
        with patch.object(self.owner, "show_history") as show:
            self.features.command("I need to call Alex sometime", spoken=True)
            self.finish_job()
            show.assert_not_called()
        self.features.speech.speak.assert_called_with("When should I remind you?")

    def test_new_voice_request_replaces_cancelled_work(self):
        self.features.job.running = True
        self.features.command("show today", spoken=True)
        self.assertTrue(self.features.job.cancelled.is_set())
        self.features.failed("Cancelled.")
        QTest.qWait(20)
        self.assertIsNone(self.features.pending_command)
        self.features.speech.speak.assert_called()

    def test_interrupt_invalidates_deferred_voice_actions_and_copy_callbacks(self):
        generation = self.features.voice_generation
        self.features.interrupt_voice()
        with patch.object(self.features, "command") as command, patch.object(self.owner, "show_history") as show:
            self.features.continue_command("open calculator", None, True, generation, use_ai=False)
            self.features.selection_tick()
            command.assert_not_called()
            show.assert_not_called()

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
