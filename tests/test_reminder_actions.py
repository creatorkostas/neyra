"""Reminder actions preserve task identity and remain separate from delivery."""

from datetime import datetime, timedelta, timezone
import json
import os
import unittest
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from neyra.reminders import ReminderStore, snooze_deadline
from neyra.reminders_ui import RemindersPanel
from neyra.ui import THEME


class Settings:
    def __init__(self, records=()):
        self.raw = json.dumps(list(records))
        self.writes = 0

    def value(self, key, default=None):
        return self.raw

    def setValue(self, key, value):
        self.raw = value
        self.writes += 1


class ReminderActionTests(unittest.TestCase):
    def test_snooze_pending_and_fired_preserves_identity_source_and_reload(self):
        settings = Settings()
        store = ReminderStore(settings)
        reminder = store.add_at("Send slides", 200, now=100, source_key="meeting:" + "a" * 64)
        original = reminder.copy()
        self.assertTrue(store.snooze(reminder["id"], 300, now=150))
        self.assertEqual(reminder, {**original, "due_at": 300})
        store.mark_fired([reminder["id"]])
        self.assertTrue(store.snooze(reminder["id"], 900, now=400))
        reopened = ReminderStore(settings)
        self.assertEqual(reopened.records, [{**original, "due_at": 900}])
        self.assertEqual(reopened.pending_due(899), [])
        self.assertEqual(reopened.take_due(900), [{**original, "due_at": 900, "status": "fired"}])

    def test_done_is_saved_and_never_acknowledged_as_delivered(self):
        settings = Settings()
        store = ReminderStore(settings)
        pending = store.add_at("Send slides", 200, now=100)
        fired = store.add_at("Call Sam", 250, now=100)
        store.mark_fired([fired["id"]])
        for record in (pending, fired):
            self.assertTrue(store.complete(record["id"]))
            self.assertEqual(record["status"], "done")
        reopened = ReminderStore(settings)
        self.assertEqual(reopened.records, store.records)
        self.assertEqual(reopened.pending_due(1000), [])
        self.assertEqual(reopened.mark_fired([pending["id"], fired["id"]]), [])
        self.assertEqual(reopened.take_due(1000), [])
        writes = settings.writes
        self.assertFalse(reopened.complete(pending["id"]))
        self.assertFalse(reopened.complete("missing"))
        self.assertFalse(reopened.snooze(pending["id"], 2000, now=1000))
        self.assertFalse(reopened.snooze("missing", 2000, now=1000))
        self.assertEqual(settings.writes, writes)
        self.assertTrue(reopened.remove(pending["id"]))

    def test_invalid_deadlines_leave_record_and_settings_unchanged(self):
        settings = Settings()
        store = ReminderStore(settings)
        reminder = store.add_at("Go", 200, now=100)
        store.mark_fired([reminder["id"]])
        original = reminder.copy()
        saved = settings.raw
        writes = settings.writes
        for due_at in (None, True, "soon", 300, 299, float("nan"), float("inf"), 10**1000):
            with self.subTest(due_at=due_at), self.assertRaises(ValueError):
                store.snooze(reminder["id"], due_at, now=300)
        with self.assertRaises(ValueError):
            store.snooze(reminder["id"], 99, now=50)
        with self.assertRaises(ValueError):
            store.snooze(reminder["id"], 900, now=float("nan"))
        self.assertEqual(reminder, original)
        self.assertEqual(settings.raw, saved)
        self.assertEqual(settings.writes, writes)

    def test_retention_shares_latest_100_between_done_and_fired(self):
        records = [{"id": f"{index:032x}", "text": "Go", "created_at": 0,
                    "due_at": index + 1,
                    "status": "pending" if index >= 120 else ("fired" if index % 2 else "done")}
                   for index in range(130)]
        settings = Settings(records)
        store = ReminderStore(settings)
        self.assertEqual(len(store.records), 110)
        self.assertEqual(sum(r["status"] == "pending" for r in store.records), 10)
        self.assertEqual(min(r["due_at"] for r in store.records), 21)
        store.complete(records[-1]["id"])
        reopened = ReminderStore(settings)
        self.assertEqual(len(reopened.records), 109)
        self.assertEqual(sum(r["status"] != "pending" for r in reopened.records), 100)


class SnoozeDeadlineTests(unittest.TestCase):
    def test_ten_minutes_and_default_clock(self):
        self.assertEqual(snooze_deadline("10min", now=1000), 1600)
        with patch("neyra.reminders.time.time", return_value=1000):
            self.assertEqual(snooze_deadline("10min"), 1600)

    def test_tomorrow_rolls_calendar_month_and_year_to_local_nine(self):
        for today in (datetime(2026, 1, 31, 23, 55), datetime(2026, 12, 31, 6)):
            with self.subTest(today=today):
                result = datetime.fromtimestamp(snooze_deadline("tomorrow", now=today.timestamp()))
                self.assertEqual(result.date(), today.date() + timedelta(days=1))
                self.assertEqual((result.hour, result.minute, result.second), (9, 0, 0))

    def test_tomorrow_uses_local_calendar_across_dst(self):
        # Model the local datetime API at Athens' 2026 clock changes without tzdata.
        for day, before, after, hours in ((datetime(2026, 3, 28, 9), 2, 3, 23),
                                          (datetime(2026, 10, 24, 9), 3, 2, 25)):
            today = day.replace(tzinfo=timezone(timedelta(hours=before)))
            tomorrow_zone = timezone(timedelta(hours=after))

            class LocalDateTime(datetime):
                @classmethod
                def fromtimestamp(cls, timestamp):
                    return datetime.fromtimestamp(timestamp, today.tzinfo).replace(tzinfo=None)

                @classmethod
                def combine(cls, date, clock):
                    return datetime.combine(date, clock, tzinfo=tomorrow_zone)

            with self.subTest(today=today), patch("neyra.reminders.datetime", LocalDateTime):
                deadline = snooze_deadline("tomorrow", now=today.timestamp())
                self.assertEqual(deadline - today.timestamp(), hours * 3600)
                expected = datetime.combine(day.date() + timedelta(days=1), datetime.min.time(),
                                            tzinfo=tomorrow_zone).replace(hour=9)
                self.assertEqual(deadline, expected.timestamp())

    def test_invalid_presets_and_clocks(self):
        for preset in ("later", "", None):
            with self.subTest(preset=preset), self.assertRaises(ValueError):
                snooze_deadline(preset, now=1000)
        for now in (True, "now", float("nan"), float("inf"), 10**1000):
            with self.subTest(now=now), self.assertRaises(ValueError):
                snooze_deadline("tomorrow", now=now)


class ReminderPanelActionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_compact_menus_emit_record_identity_and_presets(self):
        panel = RemindersPanel()
        self.addCleanup(panel.close)
        panel.setStyleSheet(THEME)
        panel.resize(760, 580)
        records = [{"id": str(index), "text": "Call Sam", "due_at": 2000, "status": status}
                   for index, status in enumerate(("pending", "fired", "done"))]
        snoozed, completed, removed = [], [], []
        panel.snooze_requested.connect(lambda identity, preset: snoozed.append((identity, preset)))
        panel.done_requested.connect(completed.append)
        panel.remove_requested.connect(removed.append)
        panel.refresh(records)
        panel.show()
        self.app.processEvents()
        buttons = panel.feed.widget().findChildren(QPushButton)
        menus = [button.menu() for button in buttons if button.menu()]
        self.assertEqual(len(menus), 2)
        for index, menu in enumerate(menus):
            actions = [action for action in menu.actions() if not action.isSeparator()]
            self.assertEqual([action.text() for action in actions],
                             ["Snooze 10 minutes", "Tomorrow 9AM", "Mark done"])
            for action in actions:
                action.trigger()
        self.assertEqual(snoozed, [("0", "10min"), ("0", "tomorrow"), ("1", "10min"), ("1", "tomorrow")])
        self.assertEqual(completed, ["0", "1"])
        for button in buttons:
            if button.text() in ("Cancel", "Dismiss"):
                button.click()
        self.assertEqual(removed, ["0", "1", "2"])
        self.assertTrue(any(label.text() == "Done" for label in panel.feed.widget().findChildren(QLabel)))
        self.assertTrue(any(label.font().strikeOut() for label in panel.feed.widget().findChildren(QLabel)))
        self.assertLessEqual(panel.feed.widget().minimumSizeHint().width(), panel.feed.viewport().width())


if __name__ == "__main__":
    unittest.main()
