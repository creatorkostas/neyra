"""Cancellable local Piper speech; downloads and audio stay off the GUI thread."""
import hashlib
import html
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
_REVISION = "5041a7a49ae5b3a0f30e6837769eb03fdbb231bd"
_VOICE_URL = f"https://huggingface.co/rhasspy/piper-voices/resolve/{_REVISION}/en/en_US/lessac/medium/"
# Pinned official repository LFS SHA256 and companion configuration SHA256.
_FILES = {
    f"{VOICE}.onnx": (63201294, "5efe09e69902187827af646e1a6e9d269dee769f9877d17b16b1b46eeaaf019f"),
    f"{VOICE}.onnx.json": (4885, "efe19c417bed055f2d69908248c6ba650fa135bc868b0e6abb3da181dab690a0"),
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


def _download(cache_dir, name, cancel):
    size, digest = _FILES[name]
    destination = cache_dir / name
    _check_cancel(cancel)
    if _verified(destination, size, digest, cancel):
        return destination
    cache_dir.mkdir(parents=True, exist_ok=True)
    url = _VOICE_URL + name
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
        self._pending = None
        self._closed = False
        self._thread = None
        self._voice = None

    @staticmethod
    def _emit(callback, value):
        if callback is not None:
            try:
                callback(value)
            except Exception:
                pass

    def speak(self, text):
        if not isinstance(text, str):
            return
        with self._condition:
            if self._closed:
                return
            self._cancel.set()
            self._cancel = threading.Event()
            self._pending = (text[:24000], self._cancel)
            if self._thread is None:
                self._thread = threading.Thread(target=self._work, name="piper-speech", daemon=False)
                self._thread.start()
            self._condition.notify()

    def stop(self):
        with self._condition:
            self._cancel.set()
            self._pending = None
            self._condition.notify()

    def close(self):
        with self._condition:
            self._closed = True
            self._cancel.set()
            self._pending = None
            self._condition.notify()

    def _load_voice(self, cancel):
        if self._voice is None:
            from piper import PiperVoice

            self._emit(self._on_status, "Preparing Piper voice")
            for name in _FILES:
                size, digest = _FILES[name]
                if not _verified(self.cache_dir / name, size, digest, cancel):
                    self._emit(self._on_status, "Downloading Piper voice (first use)")
                _download(self.cache_dir, name, cancel)
            _check_cancel(cancel)
            self._emit(self._on_status, "Loading Piper voice")
            self._voice = PiperVoice.load(self.cache_dir / f"{VOICE}.onnx", use_cuda=False,
                                          download_dir=self.cache_dir)
        _check_cancel(cancel)
        return self._voice

    def _work(self):
        try:
            while True:
                with self._condition:
                    self._condition.wait_for(lambda: self._pending is not None or self._closed)
                    if self._closed:
                        return
                    text, cancel = self._pending
                    self._pending = None
                try:
                    text = spoken_text(text)
                    _check_cancel(cancel)
                    if text:
                        voice = self._load_voice(cancel)
                        self._emit(self._on_status, "Speaking")
                        for sentence in _sentences(text):
                            _check_cancel(cancel)
                            for chunk in voice.synthesize(sentence):
                                _check_cancel(cancel)
                                _play(chunk, cancel)
                    _check_cancel(cancel)
                    self._emit(self._on_status, "Ready")
                except _Cancelled:
                    self._emit(self._on_status, "Stopped")
                except Exception as exc:
                    if not cancel.is_set():
                        self._emit(self._on_error, f"Piper speech unavailable: {exc}")
                        self._emit(self._on_status, "Speech unavailable")
        finally:
            self._voice = None
