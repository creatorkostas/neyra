"""Whistle streaming and optional Voz inference workers."""
import json
import queue
import shutil
import subprocess
import tempfile
import threading
import wave
import time
from collections import deque
from pathlib import Path
import numpy as np
from PySide6.QtCore import QObject, Signal
from .meeting import MeetingModels, validated_words, label_words, suggested_title

LANGUAGE = "en"
SAMPLE_RATE = 16_000
UPDATE_SECONDS = 1

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
        self._voz_process = None
        self._voz_lock = threading.Lock()
        self._voz_start_lock = threading.Lock()
        self._voz_prepare_thread = None
        self._closed = False
        self._voz_ready = False
        self._voz_events = queue.Queue()
        self._voz_diagnostics = deque(maxlen=30)
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
        if self._voz_ready and self._voz_process and self._voz_process.poll() is None:
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
                    import needle
                    committed = []
                    def update_chunks():
                        pending = []
                        sample_count = 0
                        while True:
                            item = chunks.get()
                            if item is None:
                                break
                            pending.append(item)
                            sample_count += len(item)
                            if sample_count >= SAMPLE_RATE * UPDATE_SECONDS:
                                yield np.concatenate(pending)
                                pending = []
                                sample_count = 0
                        if pending:
                            yield np.concatenate(pending)

                    pending_text = ""
                    for step in needle.stream(update_chunks(), language=LANGUAGE, keywords=keywords):
                        fragment = str(step.get("text") or "").strip()
                        if fragment:
                            committed.append(fragment)
                        pending_text = str(step.get("pending") or "").strip()
                        self.partial.emit(" ".join([*committed, pending_text]).strip())
                    result = " ".join(committed).strip()
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
            process = self._start_voz()
            with self._voz_lock:
                if self._closed or process.poll() is not None:
                    raise RuntimeError("Voz stopped before transcription started.")
                process.stdin.write(json.dumps({"path": str(source_path)}) + "\n")
                process.stdin.flush()
            self.model_status.emit("voz", "transcribing", "Transcribing your recording with Voz...", 0)
            while True:
                event = self._read_voz_event(process)
                if event["event"] == "transcribing":
                    percent = round(float(event.get("fraction", 0)) * 100)
                    self.model_status.emit("voz", "transcribing", f"Transcribing with Voz · {percent}%", max(0, min(100, percent)))
                    self.partial.emit(f"Transcribing with Voz... {percent}%")
                elif event["event"] == "result":
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
        # Preloading and a recording can ask for the same subprocess at once.
        with self._voz_start_lock:
            try:
                return self._load_voz()
            except Exception:
                self._discard_voz()
                raise

    def _load_voz(self):
        with self._voz_lock:
            if self._closed:
                raise RuntimeError("Neyra is shutting down.")
            if self._voz_ready and self._voz_process and self._voz_process.poll() is None:
                return self._voz_process

            node = shutil.which("node")
            if not node:
                raise RuntimeError("Voz needs Node.js 20 or newer. Install Node.js, then retry loading the model.")
            project_root = Path(__file__).resolve().parent.parent
            script_dir = project_root / "assets" / "voz" if "__compiled__" in globals() else Path(__file__).resolve().parent
            script = script_dir / "voz_transcribe.mjs"
            if not script.is_file():
                raise RuntimeError(f"Voz runner not found: {script}")
            process = subprocess.Popen(
                [node, str(script)], cwd=project_root,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self._voz_process = process
            self._voz_ready = False
            events = self._voz_events = queue.Queue()
            diagnostics = self._voz_diagnostics = deque(maxlen=30)

        def read_events():
            try:
                for line in process.stdout:
                    try:
                        event = json.loads(line)
                    except ValueError:
                        diagnostics.append(line.strip())
                        continue
                    if isinstance(event, dict) and "event" in event:
                        events.put(event)
            finally:
                events.put({"event": "exited"})
                process.stdout.close()

        def read_errors():
            try:
                for line in process.stderr:
                    diagnostics.append(line.strip())
            finally:
                process.stderr.close()

        # ONNX diagnostics must be drained while stdout carries the protocol.
        threading.Thread(target=read_events, name="voz-output", daemon=True).start()
        threading.Thread(target=read_errors, name="voz-errors", daemon=True).start()

        self.model_status.emit("voz", "loading", "Starting Voz and loading its local model...", -1)
        self.partial.emit("Starting Voz and loading its local model...")
        deadline = time.monotonic() + 900
        while True:
            if time.monotonic() > deadline:
                raise RuntimeError("Voz model setup timed out. Check your connection and retry.")
            event = self._read_voz_event(process)
            if event["event"] == "loading":
                self.model_status.emit("voz", "loading", "Loading Voz assets and preparing its local model...", -1)
                self.partial.emit("Loading Voz assets and preparing its local model...")
            elif event["event"] == "download":
                loaded = float(event.get("loaded", 0)) / 1048576
                total = float(event.get("total", 0)) / 1048576
                progress = f"{loaded:.1f} / {total:.1f} MB" if total else f"{loaded:.1f} MB"
                filename = str(event.get("file", "model"))
                self.model_status.emit("voz", "downloading", f"Downloading {filename} · {progress}",
                                       min(100, max(0, round(loaded / total * 100))) if total > 0 else -1)
                self.partial.emit(f"Downloading Voz: {progress}")
            elif event["event"] == "ready":
                self._voz_ready = True
                self.model_status.emit("voz", "ready", "Voz is ready. The loaded model stays in memory for your next recording.", 100)
                return process
            elif event["event"] in ("error", "fatal"):
                raise RuntimeError(f"Voz failed to load: {event.get('message', 'Unknown model error')}")

    def _read_voz_event(self, process):
        deadline = time.monotonic() + 180
        while not self._closed:
            try:
                event = self._voz_events.get(timeout=0.25)
                if event["event"] == "exited":
                    detail = "\n".join(self._voz_diagnostics)
                    raise RuntimeError(detail or f"Voz runtime stopped (exit code {process.poll()}).")
                return event
            except queue.Empty:
                if time.monotonic() > deadline:
                    raise RuntimeError("Voz stopped responding. Please retry the transcription.")
        raise RuntimeError("Neyra is shutting down.")

    def _discard_voz(self):
        with self._voz_lock:
            process = self._voz_process
            self._voz_process = None
            self._voz_ready = False
        if process:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
            if process.stdin and not process.stdin.closed:
                process.stdin.close()

    def close(self):
        self._closed = True
        self.meeting_models.close()
        self._discard_voz()
