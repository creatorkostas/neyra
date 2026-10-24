import unittest
from unittest.mock import patch
from neyra.conversation import ConversationMemory


class ConversationTests(unittest.TestCase):
    def test_turn_bounds_expiry_and_detached_context(self):
        memory = ConversationMemory(ttl=10, max_turns=2, max_chars=20)
        with patch("neyra.conversation.time.monotonic", return_value=100):
            memory.remember("a", "one", "answer")
            memory.remember("a", "two", "answer")
            memory.remember("a", "three", "reply")
            context = memory.context("a")
            self.assertEqual(len(context), 2)
            self.assertLessEqual(sum(len(t["request"]) + len(t["answer"]) for t in context), 20)
            context[0]["answer"] = "tampered"
            self.assertNotEqual(memory.context("a")[0]["answer"], "tampered")
        with patch("neyra.conversation.time.monotonic", return_value=110):
            self.assertEqual(memory.context("a"), [])

    def test_account_changes_and_clear_forget_context(self):
        memory = ConversationMemory()
        memory.remember("a", "question", "answer")
        self.assertEqual(memory.context("b"), [])
        self.assertEqual(memory.context("a"), [])
        memory.remember("a", "question", "answer")
        memory.clear()
        self.assertEqual(memory.context("a"), [])
        memory.remember(None, "question", "answer")
        self.assertEqual(memory.context(None), [])
