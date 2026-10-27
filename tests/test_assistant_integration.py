"""Assistant routes, privacy boundaries, and reviewed reminder creation."""
import os
import json
import tempfile
import threading
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
        self.router = self.features.needle_router = Mock()
        self.router.route.return_value = None

    def test_assistant_reveals_controls_only_for_the_current_step(self):
        self.assertTrue(self.panel.language.isHidden())
        self.panel.selection_mode.setCurrentText("Translate")
        self.assertFalse(self.panel.language.isHidden())
        self.panel.selection_mode.setCurrentText("Summarize")
        self.assertTrue(self.panel.language.isHidden())
        self.assertEqual(self.panel.explain.text(), "Summarize with assistant")
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
        self.router.route.return_value = '{"command":"show today"}'
        self.features.command("Could you show me what my day looks like?")
        self.finish_job()
        QTest.qWait(20)
        self.assertEqual(self.panel.tabs.currentIndex(), 4)
        sent = self.router.route.call_args.args[0]
        self.assertIn("what my day looks like", sent)
        self.assertNotIn("Private selected content", sent)
        self.assertNotIn("Private saved content", sent)
        self.assertEqual(self.router.route.call_count, 1)

    def test_natural_selection_does_not_focus_dashboard_before_capture(self):
        self.connect_intent_account()
        self.router.route.return_value = '{"command":"summarize selected text"}'
        with patch.object(self.features, "capture_selection") as capture, patch.object(self.features, "show") as show:
            self.features.command("Can you shorten the text I highlighted?")
            self.finish_job()
            QTest.qWait(20)
            capture.assert_called_once()
            show.assert_not_called()
        self.assertEqual(self.router.route.call_count, 1)

    def test_bad_ai_intent_and_missing_preview_execute_nothing(self):
        self.connect_intent_account()
        for answer in ('{"command":"run powershell"}', '{"command":"send this text"}'):
            self.router.route.return_value = answer
            self.features.command("Do something for me")
            self.finish_job()
            QTest.qWait(20)
            self.assertEqual(self.owner.reminder_store.records, [])
            self.assertFalse(self.features.intent_pending)
        self.assertIn("review first", self.panel.status.text())

    def test_intent_clarification_keeps_previous_request_for_next_utterance(self):
        self.connect_intent_account()
        self.router.route.return_value = '{"clarification":"How long from now?"}'
        self.features.command("I need to remember to call Alex")
        self.finish_job()
        self.assertIn("How long", self.panel.status.text())
        self.router.route.return_value = '{"command":"show today"}'
        self.features.command("In about an hour")
        self.finish_job()
        QTest.qWait(20)
        self.assertIn("remember to call Alex", self.router.route.call_args.args[0])
        self.assertIsNone(self.features.intent_clarification)

    def test_cancelled_interpretation_does_not_dispatch(self):
        self.connect_intent_account()
        def respond(*args, **kwargs):
            self.features.job.cancelled.set()
            return '{"command":"show today"}'
        self.router.route.side_effect = respond
        with patch.object(self.features, "refresh_briefing") as refresh:
            self.features.command("How is my day looking?")
            self.finish_job()
            self.assertFalse(self.features.intent_pending)
            self.assertIn("Cancelled", self.panel.status.text())
            self.assertEqual(self.panel.tabs.currentIndex(), 0)
        self.router.route.side_effect = None

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
        self.assertIn("No new assistant request", self.panel.status.text())
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
        self.client.respond.return_value = 'Photosynthesis is how plants use light to make food.'
        with patch.object(self.owner, "show_history") as show:
            self.features.command("Can you explain photosynthesis?", spoken=True)
            self.finish_job()
            show.assert_not_called()
        self.client.respond.assert_called_once()
        self.assertTrue(json.loads(self.client.respond.call_args.args[1])["voice_mode"])
        self.features.speech.speak.assert_called_with("Photosynthesis is how plants use light to make food.")

    def test_voice_clarification_is_spoken_without_opening_ui(self):
        self.connect_intent_account()
        self.router.route.return_value = '{"clarification":"When should I remind you?"}'
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

    def test_voice_followup_uses_recent_answer_and_forget_clears_it(self):
        self.connect_intent_account()
        self.client.respond.return_value = 'The best approach is to start small and test.'
        self.features.command("How should I start?", spoken=True)
        self.finish_job()
        self.client.respond.return_value = 'Start small, then test.'
        self.features.command("Make that shorter", spoken=True)
        self.finish_job()
        sent = json.loads(self.client.respond.call_args.args[1])
        self.assertEqual(sent["recent_conversation"][0]["answer"], "The best approach is to start small and test.")
        self.features.command("forget our conversation", spoken=True)
        self.assertEqual(self.features.conversation.context("connected"), [])
        self.client.respond.return_value = 'A fresh start.'
        self.features.command("A new question please", spoken=True)
        self.finish_job()
        self.assertEqual(json.loads(self.client.respond.call_args.args[1])["recent_conversation"], [])

    def test_memory_toggle_and_account_switch_remove_previous_answers(self):
        self.connect_intent_account()
        self.features.get_client()
        self.features.conversation.remember("connected", "question", "private answer")
        self.owner.history.conversation_memory_toggle.setChecked(False)
        self.assertEqual(self.features.conversation.context("connected"), [])
        self.client.respond.return_value = 'New answer.'
        self.features.command("A new question", spoken=True)
        self.finish_job()
        self.assertNotIn("recent_conversation", json.loads(self.client.respond.call_args.args[1]))
        self.assertEqual(self.features.conversation.context("connected"), [])
        self.owner.history.conversation_memory_toggle.setChecked(True)
        self.features.conversation.remember("connected", "question", "private answer")
        self.client.active_id = "other"
        self.features.command("Another question", spoken=True)
        self.finish_job()
        self.assertNotIn("private answer", self.client.respond.call_args.args[1])

    def test_screen_question_sends_one_memory_only_image_without_ui(self):
        self.connect_intent_account()
        self.client.respond.return_value = "There is a chart showing rising sales."
        image = "data:image/jpeg;base64,synthetic-test-image"
        with patch("neyra.assistant_features.capture_screen", return_value=image) as capture, patch.object(self.owner, "show_history") as show:
            self.features.command("Based on what I see on the screen, explain the chart", spoken=True)
            QTest.qWait(150)
            self.finish_job()
            capture.assert_called_once()
            show.assert_not_called()
        self.client.respond.assert_called_once()
        self.assertEqual(self.client.respond.call_args.kwargs["image_data_url"], image)
        self.features.speech.speak.assert_called_with("There is a chart showing rising sales.")
        memory = self.features.conversation.context("connected")
        self.assertIn("rising sales", memory[0]["answer"])
        self.assertNotIn("base64", json.dumps(memory))
        self.assertEqual(len(self.features.response_cache.entries), 0)

    def test_ordinary_question_and_cancelled_capture_do_not_take_screenshots(self):
        self.connect_intent_account()
        self.client.respond.return_value = 'A normal answer.'
        with patch("neyra.assistant_features.capture_screen") as capture:
            self.features.command("Explain gravity", spoken=True)
            self.finish_job()
            capture.assert_not_called()
            self.features.command("Explain what is on my screen", spoken=True)
            self.features.interrupt_voice()
            QTest.qWait(150)
            capture.assert_not_called()

    def test_capture_failure_is_spoken_without_sending_a_request(self):
        self.connect_intent_account()
        with patch("neyra.assistant_features.capture_screen", side_effect=RuntimeError("Screen permission is required")):
            self.features.command("What is on my screen?", spoken=True)
            QTest.qWait(150)
        self.client.respond.assert_not_called()
        self.features.speech.speak.assert_called_with("Screen permission is required")

    def test_overlay_follows_recording_thinking_speaking_and_cancels(self):
        self.owner.engine.run = Mock()
        with patch("neyra.main.Microphone", return_value=Mock()):
            self.owner.start("assistant")
            self.assertEqual(self.owner.overlay.state, "Listening")
            self.assertEqual(self.owner.overlay.action_button.text(), "Cancel")
            self.owner.stop()
            self.assertEqual(self.owner.overlay.state, "Thinking")
            self.owner.overlay.action_button.click()
            self.assertTrue(self.owner._discard_assistant_transcript)
            with patch.object(self.features, "command") as command:
                self.owner.complete("open calculator")
                command.assert_not_called()
        self.features.speak_answer("Hello there")
        self.features.speech.is_busy = True
        self.features.handle_speech_status("Speaking")
        self.assertEqual(self.owner.overlay.state, "Speaking")
        self.assertEqual(self.owner.overlay.action_button.text(), "Stop")
        self.owner.overlay.action_button.click()
        self.features.speech.stop.assert_called()
        self.assertFalse(self.owner.overlay.isVisible())

    def test_editing_a_note_query_keeps_recent_conversation(self):
        self.connect_intent_account()
        self.features.get_client()
        self.features.conversation.remember("connected", "question", "recent answer")
        self.panel.question.setText("a different note question")
        self.assertEqual(self.features.conversation.context("connected")[0]["answer"], "recent answer")
        self.assertEqual(self.features.sources, [])

    def test_clarification_from_another_account_is_not_sent(self):
        self.connect_intent_account()
        self.client.respond.return_value = '{"clarification":"When?"}'
        self.features.command("Remind me about private account A details", spoken=True)
        self.finish_job()
        self.client.active_id = "other"
        self.client.accounts.return_value = [{"id": "other", "connected": True, "label": "Other"}]
        self.client.respond.return_value = 'A new answer.'
        self.features.command("In an hour", spoken=True)
        self.finish_job()
        self.assertNotIn("previous_request", json.loads(self.client.respond.call_args.args[1]))

    def test_reminder_pronoun_is_resolved_from_recent_answer(self):
        self.connect_intent_account()
        self.features.get_client()
        self.features.conversation.remember("connected", "What is my next task?", "Call Alex about the slides.")
        self.router.route.return_value = '{"command":"remind me in an hour to call Alex about the slides"}'
        self.features.command("remind me in an hour to do that", spoken=True)
        self.finish_job()
        QTest.qWait(30)
        self.assertEqual(self.owner.reminder_store.records[0]["text"].casefold(), "call alex about the slides")
        self.assertIn("Call Alex", self.router.route.call_args.args[0])

    def test_cancelled_request_does_not_reopen_the_overlay(self):
        self.features.job_voice = True
        self.features.job_generation = self.features.voice_generation
        self.features.job.running = True
        self.owner.set_assistant_voice_state("Thinking", "Working")
        self.owner.cancel_assistant()
        self.features.failed("Cancelled.")
        self.assertFalse(self.owner.overlay.isVisible())

    def test_streamed_voice_starts_before_model_completion_without_repeating(self):
        entered, release = threading.Event(), threading.Event()
        self.panel.selection.setPlainText("A selected passage.")
        def respond(instructions, text, cancel, on_delta, **kwargs):
            on_delta("First sentence. ")
            entered.set()
            release.wait(3)
            on_delta("Second sentence.")
            return "First sentence. Second sentence."
        self.client.respond.side_effect = respond
        try:
            self.features.command("send this text", spoken=True)
            self.assertTrue(entered.wait(1))
            for _ in range(100):
                QTest.qWait(10)
                if self.features.speech is not None and self.features.speech.append_stream.called:
                    break
            speech = self.features.speech
            self.assertIsNotNone(speech)
            self.assertTrue(self.features.job.running)
            self.assertEqual(speech.append_stream.call_args.args[1], "First sentence.")
        finally:
            release.set()
        self.finish_job()
        self.assertEqual([call.args[1] for call in speech.append_stream.call_args_list], ["First sentence.", "Second sentence."])
        speech.finish_stream.assert_called_once()
        speech.speak.assert_not_called()
        self.client.respond.side_effect = None

    def test_general_answer_streams_plain_provider_text(self):
        self.connect_intent_account()
        def respond(instructions, text, cancel, on_delta, **kwargs):
            for chunk in ('A spoken sentence. ', 'Another sentence.'):
                on_delta(chunk)
            return 'A spoken sentence. Another sentence.'
        self.client.respond.side_effect = respond
        self.features.command("Explain something useful", spoken=True)
        self.finish_job()
        speech = self.features.speech
        self.assertEqual([call.args[1] for call in speech.append_stream.call_args_list], ["A spoken sentence.", "Another sentence."])
        speech.speak.assert_not_called()
        self.client.respond.side_effect = None

    def test_stop_voice_during_generation_prevents_later_audio_restart(self):
        entered, release = threading.Event(), threading.Event()
        self.panel.selection.setPlainText("A selected passage.")
        def respond(instructions, text, cancel, on_delta, **kwargs):
            on_delta("First sentence. ")
            entered.set()
            release.wait(3)
            on_delta("Do not read this later sentence.")
            return "First sentence. Do not read this later sentence."
        self.client.respond.side_effect = respond
        try:
            self.features.command("send this text", spoken=True)
            self.assertTrue(entered.wait(1))
            QTest.qWait(30)
            self.features.stop_speech()
        finally:
            release.set()
        self.finish_job()
        speech = self.features.speech
        self.assertEqual([call.args[1] for call in speech.append_stream.call_args_list], ["First sentence."])
        speech.speak.assert_not_called()
        self.client.respond.side_effect = None

    def test_voice_preview_speed_and_translation_voice(self):
        from neyra.speech import VOICE_CATALOG
        window = self.owner.history
        greek = "el_GR-rapunzelina-low"
        window.piper_voice_choice.setCurrentIndex(window.piper_voice_choice.findData(greek))
        window.piper_speed_choice.setCurrentIndex(window.piper_speed_choice.findData(1.25))
        window.preview_voice_button.click()
        self.features.speech.configure.assert_called_with(greek, 1.25)
        self.features.speech.speak.assert_called_with(VOICE_CATALOG[greek]["sample"])
        self.assertEqual(window.settings.value("piper_voice"), greek)
        self.assertEqual(window.settings.value("piper_speed", type=float), 1.25)
        window.piper_voice_choice.setCurrentIndex(window.piper_voice_choice.findData("en_US-lessac-medium"))
        self.panel.selection_mode.setCurrentText("Translate")
        self.panel.language.setText("Greek")
        self.panel.selection.setPlainText("Hello.")
        self.client.respond.return_value = "Translated answer."
        self.features.command("send this text", spoken=True)
        self.finish_job()
        self.features.speech.configure.assert_called_with(greek, 1.25)

    def test_actual_assistant_shortcut_interrupts_running_model_and_listens(self):
        entered, release = threading.Event(), threading.Event()
        self.panel.selection.setPlainText("A selected passage.")
        def respond(instructions, text, cancel, on_delta, **kwargs):
            on_delta("First sentence. ")
            entered.set()
            release.wait(3)
            on_delta("Stale late sentence. ")
            return "First sentence. Stale late sentence."
        self.client.respond.side_effect = respond
        try:
            self.features.command("send this text", spoken=True)
            self.assertTrue(entered.wait(1))
            QTest.qWait(30)
            speech = self.features.speech
            with patch("neyra.main.Microphone", return_value=Mock()) as microphone:
                self.owner.start_assistant()
                self.assertTrue(self.owner.recording)
                self.assertEqual(self.owner.active_mode, "assistant")
                microphone.return_value.start.assert_called_once()
                self.assertFalse(self.features.job.running)
                speech.stop.assert_called()
                self.assertEqual(self.owner.overlay.state, "Listening")
                release.set()
                QTest.qWait(50)
                self.assertEqual([call.args[1] for call in speech.append_stream.call_args_list], ["First sentence."])
                self.assertTrue(self.owner.recording)
                self.assertEqual(self.owner.overlay.state, "Listening")
                self.owner.cancel_assistant()
                self.owner.complete("discard this audio")
        finally:
            release.set()
            self.client.respond.side_effect = None

    def test_new_voice_request_does_not_cancel_non_cancellable_signout(self):
        self.features.job.running = True
        self.features.can_cancel = False
        self.features.command("show today", spoken=True)
        self.assertFalse(self.features.job.cancelled.is_set())
        self.features.finished("Signed out")
        QTest.qWait(20)
        self.assertIsNone(self.features.pending_command)
        self.assertFalse(self.features.job.running)
        self.assertIn("Your briefing", self.panel.briefing.toPlainText())

    def finish_job(self):
        for _ in range(100):
            QTest.qWait(10)
            if not self.features.job.running and not self.features.continuation_pending:
                QTest.qWait(20)
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
