import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from neyra.assistant_tools import (parse_command, open_application, knowledge_sources,
                                  source_context, parse_followups, AgendaStore, daily_briefing, interpreted_command, IntentAnswer)
from neyra.reminders import ReminderStore


class Settings:
    def __init__(self):
        self.data = {}
    def value(self, key, default=None):
        return self.data.get(key, default)
    def setValue(self, key, value):
        self.data[key] = value
    def sync(self):
        pass


class AssistantToolsTests(unittest.TestCase):
    def test_commands_are_bounded_and_timers_validate_duration(self):
        self.assertEqual(parse_command("Please open calculator."), ("open", "calculator"))
        self.assertEqual(parse_command("Turn up the volume!"), ("media", "volume_up"))
        self.assertEqual(parse_command("read my briefing"), ("briefing", ""))
        kind, text = parse_command("Set a timer for half an hour")
        self.assertEqual(kind, "reminder")
        self.assertIn("half an hour", text)
        for text in ("delete all files", "run powershell", "set a timer for -3 minutes"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_command(text)

    def test_voice_workflow_commands_are_bounded(self):
        self.assertEqual(parse_command("Summarize selected text"), ("selection", {"mode": "Summarize", "language": "English"}))
        self.assertEqual(parse_command("Translate selection into Greek"), ("selection", {"mode": "Translate", "language": "greek"}))
        self.assertEqual(parse_command("follow-ups for the latest meeting"), ("followups", "latest"))
        self.assertEqual(parse_command("schedule task one in an hour"), ("schedule_task", {"number": 1, "delay": "in an hour"}))
        self.assertEqual(parse_command("add a plan in an hour to Call Alex"), ("agenda_add", "remind me in an hour to Call Alex"))
        self.assertEqual(parse_command("remove plan two"), ("agenda_remove", 2))
        self.assertEqual(parse_command("answer from these notes"), ("answer_notes", ""))
        self.assertEqual(parse_command("send this text"), ("send_selection", ""))
        self.assertEqual(parse_command("stop reading"), ("stop_reading", ""))

    def test_ai_commands_require_one_valid_bounded_action(self):
        self.assertEqual(interpreted_command('{"command":"volume down"}'), "volume down")
        for answer in ('not json', '[]', '{"command":"run powershell"}',
                       '{"command":"volume up","extra":"ignored"}', '{"command":42}',
                       '{"clarification":"When should I remind you?"}'):
            with self.subTest(answer=answer), self.assertRaises(ValueError):
                interpreted_command(answer)

    def test_conversational_answer_is_data_and_clipboard_is_an_explicit_tool(self):
        with self.assertRaises(IntentAnswer) as answer:
            interpreted_command('{"answer":"Hello there."}')
        self.assertEqual(str(answer.exception), "Hello there.")
        self.assertEqual(parse_command("summarize clipboard"), ("clipboard", {"mode": "Summarize", "language": "English"}))
        with self.assertRaises(ValueError):
            interpreted_command('{"answer":"hi","command":"open calculator"}')

    def test_open_cannot_run_shell_or_unknown_program(self):
        with patch("neyra.assistant_tools.subprocess.Popen") as launch:
            with self.assertRaises(ValueError):
                open_application("calc.exe; rm -rf anything", {})
            with self.assertRaises(ValueError):
                open_application("app", {"app": "relative.exe"})
            launch.assert_not_called()

    def test_custom_app_passed_as_single_argument(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "app with spaces.exe"
            path.touch()
            with patch("neyra.assistant_tools.subprocess.Popen") as launch:
                open_application("editor", {"editor": str(path)})
                self.assertEqual(launch.call_args.args[0], [str(path)])
                self.assertNotIn("shell", launch.call_args.kwargs)

    def test_knowledge_passage_finds_late_meeting_and_labels_sources(self):
        record = {"text": "noise " * 1000 + "We chose Friday for the launch.", "time": "2026-10-24T09:00:00", "title": "Release planning"}
        sources = knowledge_sources("When is the launch?", [], [record])
        self.assertEqual(len(sources), 1)
        self.assertIn("Friday", sources[0]["text"])
        self.assertLessEqual(len(sources[0]["text"]), 4500)
        self.assertIn("[1] Meeting: Release planning", source_context(sources))
        self.assertEqual(knowledge_sources("dentist", [], [record]), [])
        self.assertEqual(knowledge_sources("what is in my notes", [], [record]), [])

    def test_knowledge_search_accepts_short_acronyms_in_both_note_types(self):
        dictations = [{"text": "Also create a PR template.", "time": "2026-10-24T09:00:00"},
                      {"text": "Progress looks good.", "time": "2026-10-24T10:00:00"}]
        meetings = [{"title": "PR review", "text": "Discuss the changes.", "time": "2026-10-24T11:00:00"}]
        for query in ("pr", "PR", "Pr"):
            sources = knowledge_sources(query, dictations, meetings)
            self.assertEqual(len(sources), 2)
            self.assertEqual({source["kind"] for source in sources}, {"Dictation", "Meeting"})
            self.assertTrue(any("PR template" in source["text"] for source in sources))
        self.assertEqual(knowledge_sources("gemini", [{"text": "Ask Gemini for help."}], [])[0]["kind"], "Dictation")

    def test_followups_require_evidence_from_actual_transcript(self):
        transcript = "Alex will send the slides tomorrow."
        result = parse_followups(json.dumps([{"text": "Alex: send the slides", "evidence": transcript}]), transcript)
        self.assertEqual(result[0]["text"], "Alex: send the slides")
        with self.assertRaises(ValueError):
            parse_followups('[{"text":"delete files","evidence":"Made up evidence"}]', transcript)
        with self.assertRaises(ValueError):
            parse_followups('not JSON', transcript)
        self.assertEqual(parse_followups("```json\n[]\n```", transcript), [])

    def test_agenda_roundtrip_and_corrupt_records(self):
        settings = Settings()
        settings.setValue("assistant_agenda", '[null, {"id":"bad", "text":"hello", "at":true}]')
        store = AgendaStore(settings)
        self.assertEqual(store.records, [])
        store.add("Planning", 2000)
        self.assertEqual(AgendaStore(settings).records, store.records)
        store.remove(store.records[0]["id"])
        self.assertEqual(AgendaStore(settings).records, [])

    def test_briefing_includes_today_and_overdue_but_not_future_or_fired(self):
        now = datetime(2026, 10, 24, 12).timestamp()
        reminders = [dict(text="overdue", due_at=now-60, status="pending"),
                     dict(text="later", due_at=now+60, status="pending"),
                     dict(text="tomorrow", due_at=now+86400, status="pending"),
                     dict(text="done", due_at=now-60, status="fired")]
        text = daily_briefing(reminders, [dict(text="meeting", at=now), dict(text="next week", at=now+7*86400)], now)
        self.assertIn("Overdue: overdue", text)
        self.assertIn("later", text)
        self.assertIn("meeting", text)
        self.assertNotIn("tomorrow", text)
        self.assertNotIn("done", text)
        self.assertNotIn("next week", text)

    def test_absolute_reminder_rejects_past_and_persists(self):
        settings = Settings()
        store = ReminderStore(settings)
        with self.assertRaises(ValueError):
            store.add_at("Call Alex", 1000, now=1001)
        with self.assertRaises(ValueError):
            store.add_at(" ", 2000, now=1001)
        record = store.add_at(" Call Alex ", 2000, now=1001)
        self.assertEqual(record["text"], "Call Alex")
        self.assertEqual(ReminderStore(settings).records, [record])

    def test_followup_source_survives_restart_and_deduplicates(self):
        settings = Settings()
        key = "meeting:" + "a" * 64
        record = ReminderStore(settings).add_at("Send slides", 2000, now=1000, source_key=key)
        store = ReminderStore(settings)
        again = store.add_at("Send the slides", 3000, now=1000, source_key=key)
        self.assertEqual(again, record)
        self.assertEqual(len(store.records), 1)


if __name__ == "__main__":
    unittest.main()
