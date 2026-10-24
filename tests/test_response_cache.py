import unittest
from unittest.mock import patch
from neyra.response_cache import ResponseCache


class ResponseCacheTests(unittest.TestCase):
    def test_keys_include_account_content_instructions_and_budget(self):
        key = ResponseCache.key("a", "explain", "private text", 2048)
        for args in (("b", "explain", "private text", 2048), ("a", "summarize", "private text", 2048),
                     ("a", "explain", "changed", 2048), ("a", "explain", "private text", 1024)):
            self.assertNotEqual(key, ResponseCache.key(*args))
        self.assertNotIn("private", key)
        self.assertIsNone(ResponseCache.key(None, "", "", 2048))

    def test_ttl_lru_and_byte_bounds(self):
        cache = ResponseCache(ttl=10, max_entries=2, max_bytes=5)
        with patch("neyra.response_cache.time.monotonic", return_value=100):
            cache.put("a", "AA")
            cache.put("b", "BB")
            self.assertEqual(cache.get("a"), "AA")
            cache.put("c", "CC")
            self.assertIsNone(cache.get("b"))
            cache.put("oversized", "123456")
            self.assertIsNone(cache.get("oversized"))
        with patch("neyra.response_cache.time.monotonic", return_value=110):
            self.assertIsNone(cache.get("a"))
        cache.clear()
        self.assertEqual(cache.size, 0)
        self.assertEqual(len(cache.entries), 0)
