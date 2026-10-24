"""Short-lived, account-scoped reuse of completed assistant results in memory."""
from collections import OrderedDict
import hashlib
import json
import time


class ResponseCache:
    def __init__(self, ttl=600, max_entries=16, max_bytes=2_000_000):
        self.ttl = ttl
        self.max_entries = max_entries
        self.max_bytes = max_bytes
        self.entries = OrderedDict()
        self.size = 0

    @staticmethod
    def key(account, instructions, text, output_limit):
        if not isinstance(account, str) or not account:
            return None
        return hashlib.sha256(json.dumps([account, instructions, text, output_limit], ensure_ascii=False).encode()).hexdigest()

    def _remove(self, key):
        _, _, size = self.entries.pop(key)
        self.size -= size

    def get(self, key):
        if key is None or key not in self.entries:
            return None
        expires, answer, _ = self.entries[key]
        if time.monotonic() >= expires:
            self._remove(key)
            return None
        self.entries.move_to_end(key)
        return answer

    def put(self, key, answer):
        if key is None or not isinstance(answer, str):
            return
        size = len(answer.encode())
        if size > self.max_bytes:
            return
        if key in self.entries:
            self._remove(key)
        self.entries[key] = (time.monotonic() + self.ttl, answer, size)
        self.size += size
        while len(self.entries) > self.max_entries or self.size > self.max_bytes:
            self._remove(next(iter(self.entries)))

    def clear(self):
        self.entries.clear()
        self.size = 0
