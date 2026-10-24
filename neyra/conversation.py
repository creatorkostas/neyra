"""Bounded, account-scoped conversation context. Never persisted to disk."""
from collections import deque
import time


class ConversationMemory:
    def __init__(self, ttl=600, max_turns=4, max_chars=12000):
        self.ttl = ttl
        self.max_turns = max_turns
        self.max_chars = max_chars
        self._account = None
        self._turns = deque()

    def clear(self):
        self._account = None
        self._turns.clear()

    def _select(self, account):
        if not isinstance(account, str) or not account:
            self.clear()
            return False
        if account != self._account:
            self.clear()
            self._account = account
        now = time.monotonic()
        while self._turns and now - self._turns[0][0] >= self.ttl:
            self._turns.popleft()
        return True

    def remember(self, account, request, answer):
        if not self._select(account) or not isinstance(request, str) or not isinstance(answer, str) or not answer.strip():
            return
        request, answer = request[:2000], answer[:4000]
        self._turns.append((time.monotonic(), request, answer))
        while len(self._turns) > self.max_turns or sum(len(t[1]) + len(t[2]) for t in self._turns) > self.max_chars:
            self._turns.popleft()

    def context(self, account):
        if not self._select(account):
            return []
        return [{"request": request, "answer": answer} for _, request, answer in self._turns]
