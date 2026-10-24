import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from neyra.assistant_tools import (parse_command, open_application, knowledge_sources,
                                  source_context, parse_followups, AgendaStore, daily_briefing)
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
