"""Cancellable local Piper speech; downloads and audio stay off the GUI thread."""
import hashlib
from collections import deque
import html
import math
import os
from pathlib import Path
import re
import tempfile
import textwrap
import threading
import time
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


VOICE = "en_US-lessac-medium"
MAX_STREAM_CHARS = 24000
MAX_STREAM_PENDING = 128
_REVISION = "5041a7a49ae5b3a0f30e6837769eb03fdbb231bd"
VOICE_CATALOG = {
    VOICE: {"label": "Lessac · US English", "language": "en-US",
            "sample": "Hello. This is Neyra speaking with the Lessac voice.", "path": "en/en_US/lessac/medium"},
    "en_GB-alan-medium": {"label": "Alan · British English", "language": "en-GB",
                          "sample": "Hello. This is Neyra speaking with the Alan voice.", "path": "en/en_GB/alan/medium"},
    "el_GR-rapunzelina-low": {"label": "Rapunzelina · Greek", "language": "el-GR",
                             "sample": "Γεια σας. Αυτή είναι η ελληνική φωνή της Νέιρα.", "path": "el/el_GR/rapunzelina/low"},
}
_VOICE_URLS = {key: f"https://huggingface.co/rhasspy/piper-voices/resolve/{_REVISION}/{value['path']}/"
               for key, value in VOICE_CATALOG.items()}
# Pinned official repository LFS SHA256 and companion configuration SHA256.
_FILES = {
    f"{VOICE}.onnx": (63201294, "5efe09e69902187827af646e1a6e9d269dee769f9877d17b16b1b46eeaaf019f"),
    f"{VOICE}.onnx.json": (4885, "efe19c417bed055f2d69908248c6ba650fa135bc868b0e6abb3da181dab690a0"),
    "en_GB-alan-medium.onnx": (63201294, "0a309668932205e762801f1efc2736cd4b0120329622adf62be09e56339d3330"),
    "en_GB-alan-medium.onnx.json": (4888, "c0f0d124e5895c00e7c03b35dcc8287f319a6998a365b182deb5c8e752ee8c1e"),
    "el_GR-rapunzelina-low.onnx": (63104526, "eebb335946c5d868743ff35fbb66b6f00e431b5b9b2e18caf47d3f609a2bf2e1"),
    "el_GR-rapunzelina-low.onnx.json": (4198, "24ccc31c1306df4364fd85b56aeb09aba8c185a1fdf7db1367a72d4affe478e4"),
}


class _Cancelled(Exception):
    pass


def _check_cancel(cancel):
    if cancel.is_set():
        raise _Cancelled()


def _safe_url(url):
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    if (parsed.scheme != "https" or parsed.username or parsed.password
            or parsed.port not in (None, 443)
            or not (host == "huggingface.co" or host.endswith(".huggingface.co") or host.endswith(".hf.co"))):
        raise OSError("Piper voice download redirected outside its trusted HTTPS hosts.")


class _VoiceRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _safe_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _verified(path, size, digest, cancel):
    try:
        if path.stat().st_size != size:
            return False
        hashed = hashlib.sha256()
        with path.open("rb") as handle:
            while data := handle.read(65536):
                _check_cancel(cancel)
                hashed.update(data)
        return hashed.hexdigest() == digest
    except FileNotFoundError:
        return False


def _download(cache_dir, name, cancel, voice_id=VOICE):
    size, digest = _FILES[name]
    destination = cache_dir / name
    _check_cancel(cancel)
    if _verified(destination, size, digest, cancel):
        return destination
    cache_dir.mkdir(parents=True, exist_ok=True)
    url = _VOICE_URLS[voice_id] + name
    _safe_url(url)
    temporary = None
    deadline = time.monotonic() + 180
    try:
        request = Request(url, headers={"User-Agent": "Neyra-Piper/1", "Accept-Encoding": "identity"})
        with build_opener(_VoiceRedirect()).open(request, timeout=10) as response:
            _safe_url(response.geturl())
            length = response.headers.get("Content-Length")
            if length is not None and int(length) != size:
                raise OSError("Piper voice download has an unexpected size.")
            hashed, received = hashlib.sha256(), 0
            with tempfile.NamedTemporaryFile(dir=cache_dir, prefix=f".{name}.", suffix=".tmp", delete=False) as handle:
                temporary = Path(handle.name)
                while True:
                    _check_cancel(cancel)
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Piper voice download timed out.")
                    data = response.read(65536)
                    if not data:
                        break
                    received += len(data)
                    if received > size:
                        raise OSError("Piper voice download exceeds its expected size.")
                    hashed.update(data)
                    handle.write(data)
                if received != size or hashed.hexdigest() != digest:
                    raise OSError("Piper voice download failed its integrity check.")
                handle.flush()
                os.fsync(handle.fileno())
        _check_cancel(cancel)
        os.replace(temporary, destination)
        return destination
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def spoken_text(text):
    """Read prose, retaining link labels and inline words but omitting code blocks."""
    text = text[:24000]
    text = re.sub(r"(?ms)^\s*(`{3,}|~{3,})[^\n]*\n.*?(?:^\s*\1\s*$|\Z)", " Code example shown in the response. ", text)
    text = re.sub(r"(?m)^ {4,}[^\n]+", "", text)
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"<[^>]*>", "", text)
    text = html.unescape(text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"(?m)^\s*(?:#{1,6}\s+|>\s*|[-*+]\s+|\d+[.)]\s+)", "", text)
    text = re.sub(r"[`*_{}\[\]()|#]", " ", text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    return " ".join(text.split())


def _sentences(text):
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        yield from textwrap.wrap(sentence, width=400, break_long_words=True, break_on_hyphens=False)


def _play(chunk, cancel):
    import sounddevice as sd

    _check_cancel(cancel)
    if chunk.sample_width != 2 or chunk.sample_channels != 1 or not 8000 <= chunk.sample_rate <= 96000:
        raise ValueError("Piper returned an unsupported audio format.")
    data = memoryview(chunk.audio_int16_bytes)
    if len(data) > chunk.sample_rate * 2 * 120:
        raise ValueError("Piper returned an oversized audio chunk.")
    position = 0
    finished = threading.Event()

    def callback(outdata, frames, timing, status):
        nonlocal position
        if cancel.is_set():
            raise sd.CallbackAbort
        count = min(len(outdata), len(data) - position)
        outdata[:count] = data[position:position + count]
        outdata[count:] = bytes(len(outdata) - count)
        position += count
        if position >= len(data):
            raise sd.CallbackStop

    stream = sd.RawOutputStream(samplerate=chunk.sample_rate, channels=1, dtype="int16", blocksize=1024,
                                callback=callback, finished_callback=finished.set)
    try:
        stream.start()
        deadline = time.monotonic() + len(data) / (chunk.sample_rate * 2) + 3
        while not finished.wait(0.03):
            if cancel.is_set():
                break
            if time.monotonic() >= deadline:
                raise TimeoutError("Piper audio playback did not finish.")
    finally:
        try:
            if cancel.is_set():
                stream.abort()
        finally:
            stream.close()
    _check_cancel(cancel)


class PiperSpeech:
    """Latest utterance wins. All public methods return without waiting for audio.

    Callbacks receive status/error strings on the worker thread. Pass Qt signal
    emit methods when updating a GUI. close cancels work and releases the voice;
    native model loading/synthesis finishes its current bounded sentence safely.
    """

    def __init__(self, cache_dir, on_error=None, on_status=None):
        self.cache_dir = Path(cache_dir)
        self._on_error = on_error
        self._on_status = on_status
        self._condition = threading.Condition()
        self._cancel = threading.Event()
        self._chunks = deque()
        self._stream_id = None
        self._stream_open = False
        self._stream_chars = 0
        self._closed = False
        self._thread = None
        self._voice = None
        self._loaded_voice_id = None
        self.voice_id = VOICE
        self.speed = 1.0
        self._busy = False

    @property
    def is_busy(self):
        with self._condition:
            return self._busy

    @staticmethod
    def _emit(callback, value):
        if callback is not None:
            try:
                callback(value)
            except Exception:
                pass

    def _invalidate(self):
        self._cancel.set()
        self._chunks.clear()
        self._stream_id = None
        self._stream_open = False
        self._stream_chars = 0
        self._busy = False

    def _start(self):
        self._cancel = threading.Event()
        self._busy = True
        if self._thread is None:
            self._thread = threading.Thread(target=self._work, name="piper-speech", daemon=False)
            self._thread.start()

    def configure(self, voice_id=VOICE, speed=1.0):
        """Apply a known voice and speed to future speech, cancelling current work."""
        if not isinstance(voice_id, str) or voice_id not in VOICE_CATALOG:
            raise ValueError("Choose a supported Piper voice.")
        if (not isinstance(speed, (int, float)) or isinstance(speed, bool)
                or not math.isfinite(speed) or not 0.75 <= speed <= 1.5):
            raise ValueError("Piper speaking speed must be between 0.75 and 1.5.")
        with self._condition:
            self._invalidate()
            self.voice_id, self.speed = voice_id, float(speed)
            self._condition.notify()

    def speak(self, text):
        if not isinstance(text, str):
            return
        with self._condition:
            if self._closed:
                return
            self._invalidate()
            self._start()
            self._chunks.extend((text[:MAX_STREAM_CHARS], None))
            self._condition.notify()

    def begin_stream(self):
        """Start a latest-wins stream; busy remains true until finish and drain."""
        with self._condition:
            if self._closed:
                return None
            self._invalidate()
            self._start()
            self._stream_id = object()
            self._stream_open = True
            self._condition.notify()
            return self._stream_id

    def append_stream(self, stream_id, text):
        """Queue complete prose without interrupting earlier sentences.

        Return False for stale/sealed streams or a full queue/text budget. The
        caller can retry queue pressure; accepted text is never truncated.
        """
        if not isinstance(text, str):
            return False
        with self._condition:
            if (self._closed or stream_id is None or stream_id is not self._stream_id or not self._stream_open
                    or len(self._chunks) >= MAX_STREAM_PENDING or self._stream_chars + len(text) > MAX_STREAM_CHARS):
                return False
            self._chunks.append(text)
            self._stream_chars += len(text)
            self._condition.notify()
            return True

    def finish_stream(self, stream_id):
        with self._condition:
            if self._closed or stream_id is None or stream_id is not self._stream_id or not self._stream_open:
                return False
            self._stream_open = False
            self._chunks.append(None)
            self._condition.notify()
            return True

    def stop(self):
        with self._condition:
            self._invalidate()
            self._condition.notify()

    def close(self):
        with self._condition:
            self._invalidate()
            self._closed = True
            self._condition.notify()

    def _load_voice(self, cancel, voice_id=VOICE):
        if self._voice is None or self._loaded_voice_id != voice_id:
            from piper import PiperVoice

            self._emit(self._on_status, "Preparing Piper voice")
            for name in (f"{voice_id}.onnx", f"{voice_id}.onnx.json"):
                size, digest = _FILES[name]
                if not _verified(self.cache_dir / name, size, digest, cancel):
                    self._emit(self._on_status, "Downloading Piper voice (first use)")
                _download(self.cache_dir, name, cancel, voice_id)
            _check_cancel(cancel)
            self._emit(self._on_status, "Loading Piper voice")
            self._voice = PiperVoice.load(self.cache_dir / f"{voice_id}.onnx", use_cuda=False,
                                          download_dir=self.cache_dir)
            self._loaded_voice_id = voice_id
        _check_cancel(cancel)
        return self._voice

    def _work(self):
        try:
            while True:
                with self._condition:
                    self._condition.wait_for(lambda: self._chunks or self._closed)
                    if self._closed:
                        return
                    text = self._chunks.popleft()
                    cancel, voice_id, speed = self._cancel, self.voice_id, self.speed
                    if text is None:
                        self._busy = False
                        self._stream_id = None
                        self._emit(self._on_status, "Ready")
                        continue
                try:
                    text = spoken_text(text)
                    _check_cancel(cancel)
                    if text:
                        voice = self._load_voice(cancel, voice_id)
                        syn_config = None
                        if speed != 1.0:
                            from piper import SynthesisConfig

                            syn_config = SynthesisConfig(length_scale=1.0 / speed)
                        self._emit(self._on_status, "Speaking")
                        for sentence in _sentences(text):
                            _check_cancel(cancel)
                            chunks = (voice.synthesize(sentence) if syn_config is None
                                      else voice.synthesize(sentence, syn_config=syn_config))
                            for chunk in chunks:
                                _check_cancel(cancel)
                                _play(chunk, cancel)
                    _check_cancel(cancel)
                except _Cancelled:
                    with self._condition:
                        current = cancel is self._cancel
                    if current:
                        self._emit(self._on_status, "Stopped")
                except Exception as exc:
                    if not cancel.is_set():
                        with self._condition:
                            if cancel is self._cancel:
                                self._invalidate()
                        self._emit(self._on_error, f"Piper speech unavailable: {exc}")
                        self._emit(self._on_status, "Speech unavailable")
        finally:
            self._voice = None
