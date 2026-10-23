"""Reminder command parsing and persistence without a running Qt application."""

import json
import unittest
from unittest.mock import Mock, patch

from neyra.reminders import ReminderStore, parse_reminder


class Settings:
    def __init__(self, raw="[]"):
        self.raw = raw
        self.writes = 0

    def value(self, key, default=None):
        assert key == "reminders"
        return self.raw

    def setValue(self, key, value):
        assert key == "reminders"
        self.raw = value
        self.writes += 1


class ParserTests(unittest.TestCase):
    def test_relative_durations_and_task_preservation(self):
        cases = [
            ("remind me in an hour to throw out the garbage", "throw out the garbage", 3600),
            ("Remind me, in an hour, to take out the garbage.", "take out the garbage", 3600),
            ("Remind me to Call MOM! in twenty-five minutes.", "Call MOM", 1500),
            ("remind me in one hour and thirty minutes to Call Mom!", "Call Mom", 5400),
            ("remind me in 1 hour, 20 minutes and 3 seconds to Go", "Go", 4803),
            ("remind me in one hundred and five seconds to Go", "Go", 105),
            ("remind me in one hundred seconds to Go", "Go", 100),
            ("remind me in half an hour to Go", "Go", 1800),
            ("remind me in a quarter of an hour to Go", "Go", 900),
            ("remind me in quarter of an hour to Go", "Go", 900),
            ("remind me in two days and a minute to Go", "Go", 172860),
            ("remind me in a week to Go", "Go", 604800),
            ("remind me in 0.5 seconds to Go", "Go", 0.5),
            ("remind me in 365 days to Go", "Go", 365 * 86400),
            ("remind me to put food in the fridge in an hour", "put food in the fridge", 3600),
        ]
        for command, text, delay in cases:
            with self.subTest(command=command):
                self.assertEqual(parse_reminder(command, 1000), (text, 1000 + delay))

    def test_unsupported_or_ambiguous_commands_explain_valid_format(self):
        commands = [
            "", None, "in an hour to Go", "remind me tomorrow to Go",
            "remind me in an hour", "remind me in an hour to !!!",
            "remind me in zero minutes to Go", "remind me in -5 minutes to Go",
            "remind me in 366 days to Go", "remind me in 52 weeks and 2 days to Go",
            "remind me in 1 hour ago to Go", "remind me in a few minutes to Go",
            "remind me in twenty ten minutes to Go", "remind me in two and three minutes to Go",
            "remind me in one hundred and seconds to Go",
            "remind me in 1 hour or 2 hours to Go", "remind me in 1 hour 2 hours to Go",
            "remind me to Go in 5 minutes in an hour",
            "remind me in 1 minute and 0 seconds to Go",
        ]
        for command in commands:
            with self.subTest(command=command), self.assertRaisesRegex(ValueError, "Try.*remind me in an hour"):
                parse_reminder(command, 1000)

    def test_clock_validation_and_default_clock(self):
        for now in (True, "now", float("nan"), float("inf"), 10**1000, 1e308):
            with self.subTest(now=now), self.assertRaises(ValueError):
                parse_reminder("remind me in a second to Go", now)
        with patch("neyra.reminders.time.time", return_value=200):
            self.assertEqual(parse_reminder("remind me in a second to Go"), ("Go", 201))


class StoreTests(unittest.TestCase):
    def test_due_reminders_survive_until_delivery_acknowledged(self):
        settings = Settings()
        store = ReminderStore(settings)
        first = store.add("remind me in a second to First", now=100)
        cancelled = store.add("remind me in two seconds to Cancelled", now=100)
        self.assertEqual(store.pending_due(103), [first, cancelled])
        self.assertEqual(settings.writes, 2)
        reopened = ReminderStore(settings)
        self.assertEqual(reopened.pending_due(103), [first, cancelled])
        self.assertEqual(reopened.pending_due(103), [first, cancelled])
        self.assertTrue(reopened.remove(cancelled["id"]))
        changed = reopened.mark_fired([first["id"], first["id"], cancelled["id"], "missing"])
        self.assertEqual(changed, [{**first, "status": "fired"}])
        self.assertEqual(settings.writes, 4)
        self.assertEqual(reopened.mark_fired([first["id"], cancelled["id"]]), [])
        self.assertEqual(settings.writes, 4)
        self.assertEqual(ReminderStore(settings).pending_due(103), [])

    def test_persistence_overdue_restart_and_single_delivery(self):
        settings = Settings()
        store = ReminderStore(settings)
        first = store.add("remind me in a minute to First", now=100)
        second = store.add("remind me in an hour to Second", now=100)
        reopened = ReminderStore(settings)
        self.assertEqual(reopened.records, [first, second])
        self.assertEqual(reopened.take_due(159), [])
        self.assertEqual(settings.writes, 2)
        self.assertEqual(reopened.take_due(200), [{**first, "status": "fired"}])
        self.assertEqual(settings.writes, 3)
        self.assertEqual(ReminderStore(settings).take_due(200), [])
        self.assertEqual([record["id"] for record in ReminderStore(settings).take_due(4000)], [second["id"]])

    def test_batch_firing_persists_once_and_cancellation(self):
        settings = Settings()
        store = ReminderStore(settings)
        records = [store.add(f"remind me in {delay} seconds to Go", now=100) for delay in (30, 10, 20)]
        self.assertTrue(store.remove(records[2]["id"]))
        self.assertFalse(store.remove("missing"))
        self.assertEqual(settings.writes, 4)
        self.assertEqual([record["id"] for record in store.take_due(1000)], [records[1]["id"], records[0]["id"]])
        self.assertEqual(settings.writes, 5)
        self.assertEqual(store.take_due(1000), [])

    def test_corrupt_settings_do_not_crash(self):
        for raw in (None, True, 42, "not json", "null", "{}", '"hello"'):
            with self.subTest(raw=raw):
                self.assertEqual(ReminderStore(Settings(raw)).records, [])

    def test_strict_record_validation_and_duplicate_ids(self):
        valid = {"id": "a" * 32, "text": "Go", "due_at": 200, "created_at": 100, "status": "pending"}
        invalid = [None, 42, {}, {**valid},
                   {**valid, "id": "not a uuid"}, {**valid, "id": []},
                   {**valid, "id": "b" * 32, "text": " "},
                   {**valid, "id": "c" * 32, "due_at": float("nan")},
                   {**valid, "id": "d" * 32, "due_at": float("inf")},
                   {**valid, "id": "e" * 32, "due_at": True},
                   {**valid, "id": "f" * 32, "created_at": "100"},
                   {**valid, "id": "1" * 32, "status": "unknown"},
                   {**valid, "id": "2" * 32, "due_at": 99},
                   {**valid, "id": "3" * 32, "due_at": 10**1000}]
        self.assertEqual(ReminderStore(Settings(json.dumps([valid, *invalid]))).records, [valid])

    def test_unrepresentable_persisted_timestamps_are_skipped(self):
        valid = {"id": "a" * 32, "text": "Go", "due_at": 200, "created_at": 100, "status": "pending"}
        invalid = [{**valid, "id": "b" * 32, "due_at": 1e100},
                   {**valid, "id": "c" * 32, "created_at": -1e100}]
        self.assertEqual(ReminderStore(Settings(json.dumps([valid, *invalid]))).records, [valid])

    def test_saves_flush_settings_when_supported(self):
        settings = Settings()
        settings.sync = Mock()
        store = ReminderStore(settings)
        reminder = store.add("remind me in a second to Go", now=100)
        settings.sync.assert_called_once_with()
        store.take_due(102)
        self.assertEqual(settings.sync.call_count, 2)
        store.remove(reminder["id"])
        self.assertEqual(settings.sync.call_count, 3)

    def test_retention_keeps_every_pending_and_latest_100_fired(self):
        records = [{"id": f"{index:032x}", "text": "Go", "created_at": 0,
                    "due_at": index + 1, "status": "fired" if index < 110 else "pending"}
                   for index in range(250)]
        settings = Settings(json.dumps(records))
        store = ReminderStore(settings)
        self.assertEqual(len(store.records), 240)
        self.assertEqual(sum(record["status"] == "pending" for record in store.records), 140)
        self.assertEqual(min(record["due_at"] for record in store.records), 11)
        due = store.take_due(1000)
        self.assertEqual(len(due), 140)
        self.assertEqual(len(ReminderStore(settings).records), 100)
        self.assertEqual(min(record["due_at"] for record in store.records), 151)

    def test_invalid_add_does_not_write(self):
        settings = Settings()
        store = ReminderStore(settings)
        with self.assertRaises(ValueError):
            store.add("remind me sometime", now=100)
        self.assertEqual(store.records, [])
        self.assertEqual(settings.writes, 0)


if __name__ == "__main__":
    unittest.main()
