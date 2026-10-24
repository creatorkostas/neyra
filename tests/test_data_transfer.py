"""Portable backup validation, rollback, and Unicode note export."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QSettings

from neyra.data_transfer import create_backup, export_notes, restore_backup, validate_backup, write_text_atomic
from neyra.shortcuts import DEFAULT_SHORTCUTS


class Settings:
    def __init__(self, values=None):
        self.values = dict(values or {})
        self.writes = 0
        self.fail_write = None
        self.fail_sync = 0
        self.status_code = 0

    def value(self, key, default=None):
        return self.values.get(key, default)

    def contains(self, key):
        return key in self.values

    def setValue(self, key, value):
        self.writes += 1
        if self.writes == self.fail_write:
            raise OSError("Synthetic write failure")
        self.values[key] = value

    def remove(self, key):
        self.values.pop(key, None)

    def sync(self):
        if self.fail_sync:
            self.fail_sync -= 1
            raise OSError("Synthetic sync failure")

    def status(self):
        return self.status_code


def sample_settings():
    history = [{"text": "Καλημέρα 世界", "time": "2026-10-24T10:30:00", "duration": 4.5}]
    meetings = [{"text": "Discuss the launch.\nSend slides.", "time": "2026-10-23T14:00:00",
                 "title": "Launch [review] *today*", "topics": [{"name": "Technology", "slug": "technology"}],
                 "words": [{"text": "Discuss", "start": 0, "end": 0.5, "speakers": [0], "refined": True}],
                 "warnings": []}]
    reminders = [{"id": f"{index:032x}", "text": "Call Sam", "created_at": 100,
                  "due_at": 200 + index, "status": status}
                 for index, status in enumerate(("pending", "fired", "done"))]
    return Settings({"history": json.dumps(history), "meetings": json.dumps(meetings),
                     "reminders": json.dumps(reminders), "dictionary": json.dumps(["Neyra", "Αθήνα"]),
                     "vocabulary_corrections": json.dumps({"near a": "Neyra"}),
                     "snippets": json.dumps({"signature": "Thanks, Sam"}),
                     "assistant_agenda": json.dumps([{"id": "agenda", "text": "Lunch", "at": 200}]),
                     "shortcuts": json.dumps(DEFAULT_SHORTCUTS), "save_history": False})


class BackupTests(unittest.TestCase):
    def test_roundtrip_all_defaults_and_collections_without_account_or_device_state(self):
        source = sample_settings()
        excluded = {"chatgpt_access_token": "secret-token", "chatgpt_accounts": "private-account",
                    "assistant_apps": '{"editor":"C:/private/editor.exe"}', "microphone": "private-device",
                    "autostart": True, "notetaker_intro_dismissed": True}
        source.values.update(excluded)
        payload = create_backup(source)
        self.assertEqual(set(payload), {"format", "version", "data"})
        self.assertEqual(payload["format"], "neyra-backup")
        self.assertIsInstance(payload["data"]["history"], list)
        self.assertIsInstance(payload["data"]["shortcuts"], dict)
        for key, value in excluded.items():
            self.assertNotIn(key, payload["data"])
            self.assertNotIn(str(value), json.dumps(payload))
        self.assertEqual(payload["data"]["style"], "Clean up speech")
        self.assertFalse(payload["data"]["meeting_speakers"])
        self.assertTrue(payload["data"]["meeting_organize"])
        self.assertEqual(payload["data"]["meeting_language"], "en")
        target = Settings({"chatgpt_access_token": "keep-this-token", "microphone": "keep-device"})
        restore_backup(target, payload)
        self.assertEqual(create_backup(target), payload)
        self.assertEqual(target.values["chatgpt_access_token"], "keep-this-token")
        self.assertEqual(target.values["microphone"], "keep-device")
        self.assertIsInstance(target.values["history"], str)
        self.assertEqual(json.loads(target.values["reminders"]), payload["data"]["reminders"])

    def test_roundtrip_actual_ini_settings_and_boolean_defaults(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "settings.ini")
            settings = QSettings(path, QSettings.Format.IniFormat)
            restore_backup(settings, create_backup(sample_settings()))
            reopened = QSettings(path, QSettings.Format.IniFormat)
            self.assertEqual(create_backup(reopened), create_backup(sample_settings()))
            strings = Settings({"save_history": "false", "meeting_organize": "true"})
            self.assertFalse(create_backup(strings)["data"]["save_history"])
            self.assertTrue(create_backup(strings)["data"]["meeting_organize"])

    def test_invalid_payloads_reject_before_any_settings_mutation(self):
        valid = create_backup(sample_settings())
        invalid = [None, [], {}, {**valid, "format": "other"}, {**valid, "version": True},
                   {**valid, "version": 2}, {**valid, "unexpected": 1}]
        changes = [
            ("history", {}), ("history", [{"text": "Go", "time": "invalid"}]),
            ("history", [{"text": 3, "time": "2026-10-24"}]),
            ("meetings", [{"text": "Go", "time": "2026-10-24", "topics": ["bad"]}]),
            ("meetings", [{"text": "Go", "time": "2026-10-24", "warnings": [1]}]),
            ("meetings", [{"text": "Go", "time": "2026-10-24", "words": [{"text": "Hi", "start": -1, "end": 0}]}]),
            ("meetings", [{"text": "Go", "time": "2026-10-24", "words": [{"text": "Hi", "start": 0, "end": 10**1000}]}]),
            ("dictionary", [42]), ("vocabulary_corrections", {"word": []}),
            ("vocabulary_corrections", {"": "word"}), ("snippets", []),
            ("assistant_agenda", [{"id": "a", "text": "", "at": 200}]),
            ("reminders", [{"id": "bad", "text": "Go", "created_at": 100, "due_at": 200, "status": "done"}]),
            ("save_history", "true"), ("meeting_cleanup", 1), ("style", "invented"),
            ("transcription_engine", "remote"), ("meeting_language", "unknown"), ("shortcuts", {}),
        ]
        for key, value in changes:
            changed = deepcopy(valid)
            changed["data"][key] = value
            invalid.append(changed)
        missing = deepcopy(valid)
        missing["data"].pop("dictionary")
        invalid.append(missing)
        injected = deepcopy(valid)
        injected["data"]["chatgpt_access_token"] = "injected"
        invalid.append(injected)
        target = Settings({"history": "keep", "other": "untouched"})
        original = target.values.copy()
        for payload in invalid:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                restore_backup(target, payload)
            self.assertEqual(target.values, original)
            self.assertEqual(target.writes, 0)

    def test_nonfinite_numbers_anywhere_and_nonstring_mapping_keys_reject(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            payload = create_backup(sample_settings())
            payload["data"]["history"][0]["extra"] = {"nested": [value]}
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_backup(payload)
        payload = create_backup(sample_settings())
        payload["data"]["snippets"] = {1: "bad"}
        with self.assertRaises(ValueError):
            validate_backup(payload)

    def test_record_caps_duplicates_and_silent_loader_drops_reject(self):
        valid = create_backup(sample_settings())
        for key, count in (("history", 501), ("meetings", 101), ("assistant_agenda", 501)):
            payload = deepcopy(valid)
            payload["data"][key] = [payload["data"][key][0]] * count
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_backup(payload)
        for key in ("reminders", "assistant_agenda"):
            payload = deepcopy(valid)
            payload["data"][key].append(deepcopy(payload["data"][key][0]))
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_backup(payload)
        payload = deepcopy(valid)
        payload["data"]["reminders"][0]["source_key"] = "invalid-source"
        with self.assertRaises(ValueError):
            validate_backup(payload)
        payload["data"]["reminders"] = [
            {"id": f"{index:032x}", "text": "Go", "created_at": 0, "due_at": index + 1, "status": "done"}
            for index in range(101)]
        with self.assertRaises(ValueError):
            validate_backup(payload)

    def test_write_failure_rolls_back_existing_values_and_absent_keys(self):
        target = Settings({"history": "original-history", "style": "Natural", "private": "keep"})
        before = target.values.copy()
        target.fail_write = 5
        with self.assertRaisesRegex(RuntimeError, "previous settings were restored"):
            restore_backup(target, create_backup(sample_settings()))
        self.assertEqual(target.values, before)

    def test_sync_failure_rolls_back_and_status_errors_are_reported(self):
        target = Settings({"history": "original-history", "private": "keep"})
        before = target.values.copy()
        target.fail_sync = 1
        with self.assertRaisesRegex(RuntimeError, "previous settings were restored"):
            restore_backup(target, create_backup(sample_settings()))
        self.assertEqual(target.values, before)
        target.status_code = 1
        with self.assertRaises(OSError):
            create_backup(target)
        with self.assertRaisesRegex(RuntimeError, "rollback could not be confirmed"):
            restore_backup(target, create_backup(sample_settings()))
        self.assertEqual(target.values, before)

    def test_corrupt_saved_collections_and_oversized_nested_input_reject(self):
        with self.assertRaises(ValueError):
            create_backup(Settings({"history": "not-json"}))
        payload = create_backup(sample_settings())
        nested = []
        for _ in range(40):
            nested = [nested]
        payload["data"]["history"][0]["extra"] = nested
        with self.assertRaises(ValueError):
            validate_backup(payload)


class ExportTests(unittest.TestCase):
    def test_unicode_markdown_and_plain_text_are_chronological(self):
        data = create_backup(sample_settings())["data"]
        markdown = export_notes(data["history"], data["meetings"])
        plain = export_notes(data["history"], data["meetings"], markdown=False)
        self.assertIn("## Launch \\[review\\] \\*today\\*", markdown)
        self.assertIn("Launch [review] *today*", plain)
        self.assertNotIn("## ", plain)
        for result in (markdown, plain):
            self.assertIn("Καλημέρα 世界", result)
            self.assertIn("Discuss the launch.\nSend slides.", result)
            self.assertIn("2026-10-23 14:00:00", result)
            self.assertLess(result.index("Discuss the launch"), result.index("Καλημέρα"))

    def test_mixed_aware_and_naive_dates_and_multiline_titles(self):
        history = [{"text": "Local", "time": "2026-10-24T12:00:00"}]
        meetings = [{"text": "Old", "time": "2020-10-24T12:00:00+02:00", "title": "Title\n# Injected"}]
        result = export_notes(history, meetings)
        self.assertIn("## Title \\# Injected", result)
        self.assertLess(result.index("Old"), result.index("Local"))

    def test_atomic_write_unicode_and_replace_failure_preserves_original(self):
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "notes.md"
            write_text_atomic(destination, "Καλημέρα 世界\n")
            self.assertEqual(destination.read_text(encoding="utf-8"), "Καλημέρα 世界\n")
            with patch("neyra.data_transfer.os.replace", side_effect=OSError("Synthetic replace failure")):
                with self.assertRaises(OSError):
                    write_text_atomic(destination, "Changed")
            self.assertEqual(destination.read_text(encoding="utf-8"), "Καλημέρα 世界\n")
            self.assertEqual(list(Path(folder).iterdir()), [destination])


if __name__ == "__main__":
    unittest.main()
