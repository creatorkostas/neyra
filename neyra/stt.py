"""Whistle live and optional Voz inference workers."""
import queue
import tempfile
import threading
import wave
from pathlib import Path
import numpy as np
from PySide6.QtCore import QObject, Signal
from .meeting import MeetingModels, validated_words, label_words, suggested_title

LANGUAGE = "en"
SAMPLE_RATE = 16_000
FRAME_SAMPLES = round(.02 * SAMPLE_RATE)
# libneedle's encoder has a fast path up to 64 frames (5.12 s); past that it is
# about seven times slower per second of audio, so transcription windows stop there.
WINDOW_SECONDS = 5.12
WINDOW_MIN_SECONDS = 2.5
WINDOW_SEARCH_SECONDS = 3.0
WINDOW_SAMPLES = round(WINDOW_SECONDS * SAMPLE_RATE)
WINDOW_MIN_SAMPLES = round(WINDOW_MIN_SECONDS * SAMPLE_RATE)
# A sustained gap this far below the typical speech frame is a pause between
# words; single quiet frames are usually a fricative inside a word.
PAUSE_RATIO = 10 ** (-12 / 10)
PAUSE_FRAMES = 3  # 60 ms
SILENCE = 1e-5  # mean square below this is room noise, which the model may hallucinate on


def window_end(samples):
    """Index to end the next Whistle window at, or None to keep listening.

    A window never grows past WINDOW_SAMPLES. It ends early in the middle of a
    pause, so a cut rarely splits a word, and else exactly at the cap, which
    keeps every encoder run on its fast path.
    """
    if len(samples) < WINDOW_MIN_SAMPLES:
        return None
    limit = min(len(samples), WINDOW_SAMPLES)
    begin = max(WINDOW_MIN_SAMPLES, limit - round(WINDOW_SEARCH_SECONDS * SAMPLE_RATE))
    begin -= begin % FRAME_SAMPLES
    block = samples[begin:begin + (limit - begin) // FRAME_SAMPLES * FRAME_SAMPLES]
    if not len(block):
        return limit if len(samples) >= WINDOW_SAMPLES else None
    energy = np.mean(block.reshape(-1, FRAME_SAMPLES) ** 2, axis=1)
    quiet = energy <= np.percentile(energy, 75) * PAUSE_RATIO
    edges = np.flatnonzero(np.diff(np.concatenate(([0], quiet.astype(np.int8), [0]))))
    pauses = [(start, stop) for start, stop in zip(edges[::2], edges[1::2]) if stop - start >= PAUSE_FRAMES]
    if pauses:
        # The quietest pause wins, later ones on a tie for more speech per window.
        start, stop = min(pauses, key=lambda pause: (float(energy[pause[0]:pause[1]].mean()), -pause[0]))
        return int(begin + ((start + stop) // 2) * FRAME_SAMPLES + FRAME_SAMPLES // 2)
    return limit if len(samples) >= WINDOW_SAMPLES else None


class Transcriber(QObject):
    partial = Signal(str)
    finished = Signal(str)
    failed = Signal(str)
    model_status = Signal(str, str, str, int)

    def __init__(self):
        super().__init__()
        self.thread = None
        self._worker_done = threading.Event()
        self._worker_done.set()
        self._voz_engine = None
        self._voz_start_lock = threading.Lock()
        self._voz_prepare_thread = None
        self._closed = False
        self._voz_ready = False
        self._voz_closed = threading.Event()
        self._whistle_ready = threading.Event()
        self._whistle_start_lock = threading.Lock()
        self._whistle_thread = None
        self._whistle_load_error = None
        self.meeting_models = MeetingModels()
        self.meeting_result = None

    def prepare_whistle(self):
        if self._closed:
            return
        if self._whistle_ready.is_set() and self._whistle_load_error is None:
            self.model_status.emit("whistle", "ready", "Whistle is ready. English recognition runs on your PC.", 100)
            return
        with self._whistle_start_lock:
            if self._closed or (self._whistle_ready.is_set() and self._whistle_load_error is None):
                return
            if self._whistle_thread and self._whistle_thread.is_alive():
                return
            self._whistle_ready.clear()
            self._whistle_load_error = None
            self.model_status.emit("whistle", "loading", "Loading Whistle on your PC...", -1)

            def load():
                try:
                    from neyra.bundled import configure_bundled_runtime
                    configure_bundled_runtime()
                    import needle
                    needle.Whistle()
                    self.model_status.emit("whistle", "ready", "Whistle is ready. English recognition runs on your PC.", 100)
                except Exception as exc:
                    self._whistle_load_error = exc
                    self.model_status.emit("whistle", "error", f"Whistle could not load: {exc}", -1)
                finally:
                    self._whistle_ready.set()

            self._whistle_thread = threading.Thread(target=load, name="whistle-model-loader", daemon=True)
            self._whistle_thread.start()

    def prepare_voz(self):
        if self._closed:
            return
        if self._voz_ready and self._voz_engine is not None:
            self.model_status.emit("voz", "ready", "Voz is ready. The loaded model stays in memory for your next recording.", 100)
            return
        if self._voz_prepare_thread and self._voz_prepare_thread.is_alive():
            return

        def load():
            try:
                self._start_voz()
            except Exception as exc:
                self.model_status.emit("voz", "error", f"Voz could not load: {exc}", -1)

        self._voz_prepare_thread = threading.Thread(target=load, name="voz-model-loader", daemon=True)
        self._voz_prepare_thread.start()

    def _wait_for_whistle(self):
        self.prepare_whistle()
        if not self._whistle_ready.is_set():
            self.partial.emit("Loading Whistle on CPU...")
        while not self._whistle_ready.wait(0.1):
            if self._closed:
                raise RuntimeError("Neyra is shutting down.")
        if self._whistle_load_error is not None:
            raise RuntimeError(f"Whistle failed to load: {self._whistle_load_error}")

    def run(self, chunks, keywords=(), model="whistle", meeting_options=None):
        if self._closed:
            raise RuntimeError("Neyra is shutting down.")
        if model not in ("whistle", "voz"):
            raise ValueError(f"Unknown transcription engine: {model}")
        if meeting_options is not None and model != "voz":
            raise ValueError("Meeting word timestamps require Voz and Align.")
        if self.thread and self.thread.is_alive():
            # A completion signal can reach the UI just before Python marks its
            # worker thread as exited. Join that completed worker before reuse.
            if self._worker_done.is_set():
                self.thread.join()
            else:
                raise RuntimeError("Transcription already running")

        self.meeting_result = None
        def worker():
            result = None
            failure = None
            try:
                if model == "voz":
                    result = self._run_voz(chunks, meeting_options=meeting_options)
                else:
                    self._wait_for_whistle()
                    result = self._run_whistle(chunks, keywords)
            except Exception as exc:
                failure = f"{type(exc).__name__}: {exc}"
            finally:
                self._worker_done.set()
            if failure is not None:
                self.model_status.emit(model, "error", failure, -1)
                self.failed.emit(failure)
            else:
                ready = self._voz_ready if model == "voz" else self._whistle_ready.is_set() and self._whistle_load_error is None
                if ready:
                    self.model_status.emit(model, "ready", f"{model.title()} is ready for another recording.", 100)
                self.finished.emit(result or "")

        worker_name = "voz-inference" if model == "voz" else "whistle-inference"
        self._worker_done.clear()
        self.thread = threading.Thread(target=worker, name=worker_name, daemon=True)
        self.thread.start()

    def _run_whistle(self, chunks, keywords=()):
        """Transcribe the recording as soon as each window is complete.

        Calling the model once per window instead of once per second of live
        audio is what keeps a long dictation faster than real time: the native
        streaming call re-encodes the audio it has kept on every pass.
        """
        import needle
        engine = needle.Whistle()
        committed = []
        buffer = np.zeros(0, np.float32)

        def commit(window):
            if float(np.mean(window ** 2)) < SILENCE:
                return
            text = str(engine.transcribe(window, language=LANGUAGE, keywords=keywords).get("text") or "").strip()
            if text:
                committed.append(text)
                self.partial.emit(" ".join(committed))

        while True:
            item = chunks.get()
            if item is None:
                break
            samples = np.asarray(item, dtype=np.float32)
            if len(samples):
                buffer = np.concatenate((buffer, samples))
            end = window_end(buffer)
            while end is not None:
                commit(buffer[:end])
                buffer = buffer[end:]
                end = window_end(buffer)
        if len(buffer):
            commit(buffer)
        return " ".join(committed).strip()

    def _run_voz(self, chunks, meeting_options=None):
        audio_directory = tempfile.TemporaryDirectory(prefix="neyra-audio-")
        audio_path = Path(audio_directory.name) / "recording.wav"
        try:
            with wave.open(str(audio_path), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(SAMPLE_RATE)
                has_audio = False
                while True:
                    item = chunks.get()
                    if item is None:
                        break
                    samples = np.asarray(item, dtype=np.float32)
                    if len(samples):
                        pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
                        wav.writeframes(pcm.tobytes())
                        has_audio = True
                    self.partial.emit("Voz will show the transcript after recording stops...")
            if not has_audio:
                return ""
            source_path = audio_path
            clean_path = audio_path.with_name(audio_path.stem + "-clean.wav")
            with wave.open(str(audio_path), "rb") as recorded:
                duration = recorded.getnframes() / recorded.getframerate()
            if meeting_options is not None:
                self.partial.emit("Checking local meeting models...")
                check = self.meeting_models.request({"operation": "check"}, timeout=15)
                required = {"align"}
                required.update(name for name, option in (("clear", "cleanup"), ("who", "speakers"), ("gist", "organize")) if meeting_options.get(option))
                if not required.issubset(set(check.get("capabilities", []))):
                    raise RuntimeError("Meeting runtime is missing required models. Run uv run python scripts/setup_meeting_models.py again.")
                if meeting_options.get("cleanup"):
                    self.partial.emit("Cleaning meeting audio with Clear...")
                    self.meeting_models.request({"operation": "enhance", "path": str(audio_path), "output_path": str(clean_path)}, self.partial.emit)
                    if not clean_path.is_file():
                        raise RuntimeError("Clear did not produce a cleaned recording.")
                    source_path = clean_path
            engine = self._start_voz()
            self.model_status.emit("voz", "transcribing", "Transcribing with Python Voz...", 0)
            def progress(fraction):
                percent = round(fraction * 100)
                self.model_status.emit("voz", "transcribing", f"Transcribing with Voz · {percent}%", percent)
                self.partial.emit(f"Transcribing with Voz... {percent}%")
            result = engine.transcribe(source_path, progress)
            for event in [dict(result, event="result")]:
                if event["event"] == "result":
                    text = str(event.get("text", "")).strip()
                    if meeting_options is not None and text:
                        words = validated_words(event.get("words"), duration)
                        if not words:
                            raise RuntimeError("Voz returned speech without word timestamps. Update the Voz runtime and retry.")
                        self.partial.emit("Refining word timestamps with Align...")
                        analysis = self.meeting_models.request({
                            "operation": "analyze", "path": str(source_path), "words": words,
                            "speakers": bool(meeting_options.get("speakers")),
                            "organize": bool(meeting_options.get("organize")), "language": meeting_options.get("language", "en"),
                        }, self.partial.emit)
                        aligned = validated_words(analysis.get("words"), duration)
                        if [word["text"] for word in aligned] != [word["text"] for word in words]:
                            raise RuntimeError("Align returned a different word sequence.")
                        if meeting_options.get("speakers"):
                            label_words(aligned, analysis.get("turns"))
                        topics = analysis.get("topics", [])
                        if not isinstance(topics, list) or any(not isinstance(topic, dict) or not isinstance(topic.get("name"), str) or not isinstance(topic.get("slug"), str) for topic in topics):
                            raise ValueError("Gist returned invalid topics.")
                        self.meeting_result = {
                            "text": text, "words": aligned, "topics": topics,
                            "title": suggested_title(text) if meeting_options.get("organize") else "",
                            "speaker_labels": bool(meeting_options.get("speakers")),
                            "audio_cleanup": bool(meeting_options.get("cleanup")),
                            "timestamp_model": "align", "language": meeting_options.get("language", "en"),
                        }
                    return text
                elif event["event"] in ("error", "fatal"):
                    raise RuntimeError(f"Voz failed: {event.get('message', 'Unknown model error')}")
        except Exception:
            self._discard_voz()
            raise
        finally:
            audio_directory.cleanup()

    def _start_voz(self):
        with self._voz_start_lock:
            if self._closed:
                raise RuntimeError("Neyra is shutting down.")
            if self._voz_engine is None:
                from .voz import VozEngine
                engine = VozEngine(lambda state, detail, progress: self.model_status.emit("voz", state, detail, progress), self._voz_closed)
                if self._closed:
                    engine.close()
                    raise RuntimeError("Neyra is shutting down.")
                self._voz_engine = engine
            self._voz_ready = True
            self.model_status.emit("voz", "ready", "Voz is ready in Python. Sessions stay loaded for your next recording.", 100)
            return self._voz_engine

    def _discard_voz(self):
        self._voz_ready = False
        engine, self._voz_engine = self._voz_engine, None
        if engine:
            engine.usage.close()

    def close(self):
        self._closed = True
        self._voz_closed.set()
        self.meeting_models.close()
        self._discard_voz()
