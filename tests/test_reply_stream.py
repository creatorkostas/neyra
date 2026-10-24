import json
import unittest
from neyra.reply_stream import JsonAnswerDecoder, ReplySpeech


class ReplyStreamTests(unittest.TestCase):
    def test_sentence_stream_preserves_partial_words_and_flushes_tail(self):
        sentences = []
        stream = ReplySpeech(sentences.append)
        stream.feed("Dr. Smith paid 3.14 dollars. Next sen")
        self.assertEqual(sentences, ["Dr. Smith paid 3.14 dollars."])
        stream.feed("tence! Tail")
        self.assertEqual(sentences[-1], "Next sentence!")
        stream.finish()
        self.assertEqual(sentences[-1], "Tail")

    def test_json_answer_escapes_and_unicode_across_every_byte_boundary(self):
        text = 'A "quoted" answer.\nGreek \u03b1 and emoji \U0001f642.'
        encoded = json.dumps({"answer": text})
        for split in range(len(encoded) + 1):
            decoder = JsonAnswerDecoder()
            self.assertEqual(decoder.feed(encoded[:split]) + decoder.feed(encoded[split:]), text)
        decoder = JsonAnswerDecoder()
        self.assertEqual("".join(decoder.feed(char) for char in encoded), text)

    def test_tool_envelopes_and_clarifications_are_never_streamed_as_prose(self):
        for payload in ({"command": "open calculator"}, {"clarification": "When?"}):
            output = []
            stream = ReplySpeech(output.append, json_answer=True)
            for char in json.dumps(payload):
                stream.feed(char)
            stream.finish()
            self.assertEqual(output, [])

    def test_code_blocks_are_not_read_and_long_prose_is_bounded(self):
        output = []
        stream = ReplySpeech(output.append)
        stream.feed("First sentence. ```python\nprint('Not spoken. ')")
        self.assertEqual(output, ["First sentence."])
        stream.feed("\n``` Then more prose.")
        stream.finish()
        self.assertNotIn("print", " ".join(output))
        output.clear()
        stream = ReplySpeech(output.append)
        stream.feed("word " * 200)
        stream.finish()
        self.assertTrue(all(len(sentence) <= 400 for sentence in output))
        with self.assertRaises(ValueError):
            ReplySpeech(output.append).feed("x" * 24001)
