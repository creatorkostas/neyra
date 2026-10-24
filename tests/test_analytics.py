"""Local analytics persistence, timing boundaries and compact Qt presentation."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication
from neyra.analytics import AnalyticsPanel, AnalyticsStore, dictation_stats
from neyra.ui import THEME

APP = QApplication.instance() or QApplication([])
USAGE = {"input_tokens": 12, "output_tokens": 8, "total_tokens": 20}


class AnalyticsStoreTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="neyra-analytics-")
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "nested" / "usage.json"
        self.store = AnalyticsStore(self.path)

    def test_reload_account_scoping_and_aggregate(self):
        self.assertTrue(self.store.record("account-a", USAGE, "request-1"))
        self.store.record("account-b", USAGE, "request-1")
        loaded = AnalyticsStore(self.path)
        self.assertEqual(loaded.snapshot("account-a")["total_tokens"], 20)
        self.assertEqual(loaded.snapshot()["total_tokens"], 40)
        self.assertEqual(loaded.snapshot()["requests"], 2)
        self.assertIsNotNone(loaded.snapshot()["started_at"])
        self.assertEqual(loaded.snapshot("missing")["requests"], 0)

    def test_duplicate_ids_are_not_counted_even_after_reload(self):
        self.store.record("account-a", USAGE, "request-1")
        loaded = AnalyticsStore(self.path)
        self.assertFalse(loaded.record("account-a", USAGE, "request-1"))
        loaded.record("account-a", USAGE)
        loaded.record("account-a", USAGE)
        self.assertEqual(loaded.snapshot()["requests"], 3)

    def test_cached_tokens_are_a_subset_of_input_and_reload_per_account(self):
        cached_usage = {**USAGE, "input_tokens_details": {"cached_tokens": 8}}
        self.store.record("account-a", cached_usage, "request-1")
        self.assertFalse(self.store.record("account-a", cached_usage, "request-1"))
        self.store.record("account-b", cached_usage, "request-1")
        loaded = AnalyticsStore(self.path)
        self.assertEqual(loaded.snapshot("account-a")["cached_input_tokens"], 8)
        self.assertEqual(loaded.snapshot()["cached_input_tokens"], 16)
        self.assertEqual(loaded.snapshot()["input_tokens"], 24)
        self.assertEqual(loaded.snapshot()["output_tokens"], 16)
        self.assertEqual(loaded.snapshot()["total_tokens"], 40)

    def test_missing_cached_details_default_to_zero(self):
        self.store.record("account-a", USAGE)
        self.store.record("account-a", {**USAGE, "input_tokens_details": {}})
        self.assertEqual(self.store.snapshot()["cached_input_tokens"], 0)

    def test_legacy_version_one_usage_file_migrates_cached_count_to_zero(self):
        self.store.record("account-a", USAGE, "request-1")
        data = json.loads(self.path.read_text())
        del data["accounts"]["account-a"]["cached_input_tokens"]
        self.path.write_text(json.dumps(data))
        loaded = AnalyticsStore(self.path)
        self.assertEqual(loaded.snapshot("account-a")["cached_input_tokens"], 0)
        self.assertEqual(loaded.snapshot("account-a")["total_tokens"], 20)
        loaded.record("account-a", {**USAGE, "input_tokens_details": {"cached_tokens": 5}}, "request-2")
        self.assertEqual(loaded.snapshot()["cached_input_tokens"], 5)
        self.assertEqual(loaded.snapshot()["total_tokens"], 40)
        persisted = json.loads(self.path.read_text())
        self.assertEqual(persisted["version"], 1)
        self.assertEqual(persisted["accounts"]["account-a"]["cached_input_tokens"], 5)

    def test_invalid_cached_usage_is_rejected_without_writing(self):
        for value in (-1, True, 1.5, "1", None, 13):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.store.record("account-a", {**USAGE, "input_tokens_details": {"cached_tokens": value}})
        for details in (None, 1, [], "invalid"):
            with self.subTest(details=details), self.assertRaises(ValueError):
                self.store.record("account-a", {**USAGE, "input_tokens_details": details})
        self.assertFalse(self.path.exists())

    def test_invalid_persisted_cached_counter_is_reported(self):
        self.store.record("account-a", USAGE)
        data = json.loads(self.path.read_text())
        for value in (-1, True, 13):
            data["accounts"]["account-a"]["cached_input_tokens"] = value
            self.path.write_text(json.dumps(data))
            with self.subTest(value=value), self.assertRaises(OSError):
                AnalyticsStore(self.path).snapshot()

    def test_deduplication_keeps_latest_1000_request_hashes(self):
        with patch.object(self.store, "_save"), patch.object(self.store, "_load"):
            for index in range(1001):
                self.store.record("account-a", USAGE, f"request-{index}")
            self.assertFalse(self.store.record("account-a", USAGE, "request-1000"))
        self.store._save(self.store._accounts)
        saved = json.loads(self.path.read_text())["accounts"]["account-a"]["request_hashes"]
        self.assertEqual(len(saved), 1000)
        self.assertNotIn(hashlib.sha256(b"request-0").hexdigest(), saved)
        self.assertTrue(AnalyticsStore(self.path).record("account-a", USAGE, "request-0"))

    def test_invalid_usage_is_rejected_without_writing(self):
        for key in USAGE:
            for value in (-1, True, 1.5, "1", None):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    self.store.record("account-a", {**USAGE, key: value})
        for usage in ({}, None, {"input_tokens": 1}):
            with self.subTest(usage=usage), self.assertRaises(ValueError):
                self.store.record("account-a", usage)
        self.assertFalse(self.path.exists())
        self.assertEqual(self.store.snapshot()["requests"], 0)

    def test_invalid_identifiers_are_rejected(self):
        for account in (None, "", " ", True):
            with self.subTest(account=account), self.assertRaises(ValueError):
                self.store.record(account, USAGE)
        for request in ("", 1, True):
            with self.subTest(request=request), self.assertRaises(ValueError):
                self.store.record("account-a", USAGE, request)

    def test_no_prompt_response_or_raw_request_id_is_saved(self):
        self.store.record("account-a", {**USAGE, "prompt": "PRIVATE PROMPT", "text": "PRIVATE RESPONSE"}, "raw-request-id")
        saved = self.path.read_text()
        for value in ("PRIVATE PROMPT", "PRIVATE RESPONSE", "raw-request-id", '"prompt"', '"text"'):
            self.assertNotIn(value, saved)
        self.assertEqual(json.loads(saved)["accounts"]["account-a"]["requests"], 1)

    def test_failed_atomic_replace_preserves_disk_and_memory_and_can_retry(self):
        self.store.record("account-a", USAGE, "first")
        before = self.path.read_bytes()
        with patch("neyra.analytics.os.replace", side_effect=OSError("disk unavailable")):
            with self.assertRaisesRegex(OSError, "disk unavailable"):
                self.store.record("account-a", USAGE, "second")
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.store.snapshot()["requests"], 1)
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])
        self.assertTrue(self.store.record("account-a", USAGE, "second"))

    def test_concurrent_requests_and_duplicates_do_not_lose_updates(self):
        with ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(lambda index: self.store.record("account-a", USAGE, f"request-{index % 10}"), range(40)))
        self.assertEqual(self.store.snapshot()["requests"], 10)
        self.assertEqual(AnalyticsStore(self.path).snapshot()["total_tokens"], 200)

    def test_distinct_store_instances_share_lock_and_reload_updates(self):
        another = AnalyticsStore(self.path)
        stores = (self.store, another)
        with ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(lambda index: stores[index % 2].record("account-a", USAGE, f"request-{index}"), range(20)))
        self.assertEqual(self.store.snapshot()["requests"], 20)
        self.assertEqual(another.snapshot()["total_tokens"], 400)
        self.assertFalse(another.record("account-a", USAGE, "request-0"))

    def test_snapshot_is_detached_and_contains_no_request_ids(self):
        self.store.record("account-a", USAGE, "request-1")
        snapshot = self.store.snapshot("account-a")
        snapshot["requests"] = 999
        self.assertEqual(self.store.snapshot("account-a")["requests"], 1)
        self.assertNotIn("request_hashes", snapshot)

    def test_corrupt_existing_file_is_reported_without_overwriting_it(self):
        self.path.parent.mkdir(parents=True)
        for raw in ("broken", '{"version": 1, "accounts": {"a": {}}}'):
            self.path.write_text(raw)
            store = AnalyticsStore(self.path)
            with self.assertRaises(OSError):
                store.snapshot()
            with self.assertRaises(OSError):
                store.record("account-a", USAGE)
            self.assertEqual(self.path.read_text(), raw)


class AnalyticsPanelTests(unittest.TestCase):
    def panel(self):
        panel = AnalyticsPanel()
        panel.setStyleSheet(THEME)
        self.addCleanup(panel.close)
        return panel

    def test_wpm_only_uses_words_from_timed_dictations(self):
        records = [{"text": "one two three", "duration": 30},
                   {"text": "one two three four five", "duration": 30},
                   {"text": "old saved dictation with no timing"}]
        stats = dictation_stats(records)
        self.assertEqual(stats["dictations"], 3)
        self.assertEqual(stats["words"], 14)
        self.assertEqual(stats["duration"], 60)
        self.assertEqual(stats["wpm"], 8)
        panel = self.panel()
        panel.refresh(records, [{"text": "meeting words stay separate"}], {**USAGE, "requests": 2})
        self.assertEqual(panel.values["words"].text(), "14")
        self.assertEqual(panel.values["wpm"].text(), "8")
        self.assertEqual(panel.values["meetings"].text(), "1")
        self.assertEqual(panel.values["duration"].text(), "1m 00s")

    def test_invalid_or_absent_duration_does_not_produce_a_fake_wpm(self):
        records = [{"text": "a b", "duration": value} for value in (None, 0, -1, True, "30", float("nan"), float("inf"))]
        stats = dictation_stats(records)
        self.assertEqual(stats["duration"], 0)
        self.assertIsNone(stats["wpm"])
        panel = self.panel()
        panel.refresh(records, [], {})
        self.assertEqual(panel.values["wpm"].text(), "No timed dictations")

    def test_usage_is_explicitly_local_and_not_a_quota(self):
        panel = self.panel()
        panel.refresh([], [], {**USAGE, "cached_input_tokens": 8, "requests": 3, "started_at": "2026-10-24T12:00:00+00:00"})
        self.assertEqual(panel.values["input_tokens"].text(), "12")
        self.assertEqual(panel.values["cached_input_tokens"].text(), "8")
        self.assertEqual(panel.values["output_tokens"].text(), "8")
        self.assertEqual(panel.values["total_tokens"].text(), "20")
        self.assertEqual(panel.values["requests"].text(), "3")
        self.assertIn("24 Oct 2026", panel.usage_hint.text())
        self.assertIn("selected account", panel.usage_hint.text())
        self.assertIn("not account-wide usage or a remaining quota", panel.usage_hint.text())
        self.assertIn("provider-reported and already included in Input tokens", panel.usage_hint.text())

    def test_empty_and_large_counts_fit_compact_main_content(self):
        panel = self.panel()
        panel.resize(700, 500)
        panel.show()
        APP.processEvents()
        self.assertEqual(panel.horizontalScrollBar().maximum(), 0)
        self.assertLessEqual(panel.widget().minimumSizeHint().width(), panel.viewport().width())
        panel.refresh([], [], {key: 123456789012 for key in (*USAGE, "cached_input_tokens", "requests")})
        APP.processEvents()
        self.assertEqual(panel.horizontalScrollBar().maximum(), 0)
        self.assertLessEqual(panel.widget().minimumSizeHint().width(), panel.viewport().width())

    def test_storage_error_is_visible_and_counters_are_not_reported_as_zero(self):
        panel = self.panel()
        panel.refresh([], [], {"error": "Local usage counters could not be read."})
        self.assertIn("Local usage counters could not be read.", panel.usage_hint.text())
        self.assertEqual(panel.values["total_tokens"].text(), "Unavailable")


if __name__ == "__main__":
    unittest.main()
