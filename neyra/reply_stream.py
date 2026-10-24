"""Incremental spoken sentences, including answer-only JSON envelopes."""
import json
import re


class JsonAnswerDecoder:
    def __init__(self):
        self.prefix = ""
        self.stage = "prefix"
        self.escape = False
        self.unicode = None
        self.high = None

    def feed(self, delta):
        if self.stage in ("done", "ignore"):
            return ""
        if self.stage == "prefix":
            self.prefix += delta
            match = re.match(r'^\s*\{\s*"([^"\\]*)"\s*:\s*', self.prefix)
            if not match:
                if len(self.prefix) > 128:
                    self.stage = "ignore"
                return ""
            if match[1] != "answer":
                self.stage = "ignore"
                return ""
            if len(self.prefix) == match.end():
                return ""
            if self.prefix[match.end()] != '"':
                self.stage = "ignore"
                return ""
            delta = self.prefix[match.end() + 1:]
            self.prefix = ""
            self.stage = "value"
        output = []
        for char in delta:
            if self.unicode is not None:
                self.unicode += char
                if len(self.unicode) < 4:
                    continue
                if not re.fullmatch(r"[0-9a-fA-F]{4}", self.unicode):
                    self.stage = "ignore"
                    break
                value = int(self.unicode, 16)
                self.unicode = None
                if 0xD800 <= value <= 0xDBFF:
                    self.high = value
                    continue
                if self.high is not None:
                    if not 0xDC00 <= value <= 0xDFFF:
                        self.stage = "ignore"
                        break
                    value = 0x10000 + ((self.high - 0xD800) << 10) + value - 0xDC00
                    self.high = None
                elif 0xDC00 <= value <= 0xDFFF:
                    self.stage = "ignore"
                    break
                output.append(chr(value))
            elif self.escape:
                self.escape = False
                if char == "u":
                    self.unicode = ""
                elif char in '"\\/bfnrt':
                    output.append(json.loads('"\\' + char + '"'))
                else:
                    self.stage = "ignore"
                    break
            elif char == "\\":
                self.escape = True
            elif char == '"':
                self.stage = "done"
                break
            elif ord(char) < 32 or self.high is not None:
                self.stage = "ignore"
                break
            else:
                output.append(char)
        return "".join(output)


class ReplySpeech:
    """Emit completed prose sentences, bounded chunks, and a final trailing phrase."""
    def __init__(self, emit, json_answer=False):
        self.emit = emit
        self.decoder = JsonAnswerDecoder() if json_answer else None
        self.buffer = ""
        self.received = False
        self.count = 0

    def feed(self, delta):
        if not isinstance(delta, str):
            return
        text = self.decoder.feed(delta) if self.decoder else delta
        if not text:
            return
        self.received = True
        self.count += len(text)
        if self.count > 24000:
            raise ValueError("Spoken reply exceeds the voice limit. The full text is available in Assistant.")
        self.buffer += text
        self._drain()

    def _drain(self, final=False):
        while self.buffer:
            # Never read a partial fenced code block as prose.
            fence = re.search(r"```|~~~", self.buffer)
            if fence:
                end = self.buffer.find(fence[0], fence.end())
                if end >= 0:
                    self.buffer = self.buffer[:fence.start()] + " Code example shown in the response. " + self.buffer[end + 3:]
                    continue
                safe = self.buffer[:fence.start()]
            else:
                safe = self.buffer
            boundary = None
            for match in re.finditer(r"[.!?](?:[\"'”’)]*)(?=\s)", safe):
                last = safe[:match.end()].split()[-1].casefold().strip('"\'')
                if last in ("mr.", "mrs.", "ms.", "dr.", "prof.", "e.g.", "i.e.", "vs.", "st."):
                    continue
                boundary = match.end()
                break
            if boundary is None and len(safe) > 400:
                boundary = safe.rfind(" ", 0, 400)
                if boundary < 1:
                    boundary = 400
            if boundary is None:
                if final:
                    self.buffer = ""
                    if safe.strip():
                        self.emit(safe.strip())
                return
            sentence = self.buffer[:boundary].strip()
            self.buffer = self.buffer[boundary:].lstrip()
            if sentence:
                self.emit(sentence)

    def finish(self):
        self._drain(final=True)
