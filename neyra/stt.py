"""Whistle streaming and optional Voz inference workers."""
import json
import shutil
import subprocess
import tempfile
import threading
import wave
from pathlib import Path
import numpy as np
from PySide6.QtCore import QObject, Signal

LANGUAGE = "en"
SAMPLE_RATE = 16_000
UPDATE_SECONDS = 3

class Transcriber(QObject):
    partial = Signal(str)
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self):
        super().__init__()
        self.thread = None
        self._worker_done = threading.Event()
        self._worker_done.set()
        self._voz_process = None
        self._voz_lock = threading.Lock()
        self._closed = False

    def run(self, chunks, keywords=(), model="whistle"):
        if self.thread and self.thread.is_alive():
            # A completion signal can reach the UI just before Python marks its
            # worker thread as exited. Join that completed worker before reuse.
            if self._worker_done.is_set():
                self.thread.join()
            else:
                raise RuntimeError("Transcription already running")

        def worker():
            result = None
            failure = None
            try:
                if model == "voz":
                    result = self._run_voz(chunks)
                else:
                    from neyra.bundled import configure_bundled_runtime
                    configure_bundled_runtime()
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
                self.failed.emit(failure)
            else:
                self.finished.emit(result or "")

        worker_name = "voz-inference" if model == "voz" else "whistle-inference"
        self._worker_done.clear()
        self.thread = threading.Thread(target=worker, name=worker_name, daemon=True)
        self.thread.start()

    def _run_voz(self, chunks):
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp:
            audio_path = Path(temp.name)
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

            process = self._start_voz()
            with self._voz_lock:
                if self._closed or process.poll() is not None:
                    raise RuntimeError("Voz stopped before transcription started.")
                process.stdin.write(json.dumps({"path": str(audio_path)}) + "\n")
                process.stdin.flush()
            while True:
                event = self._read_voz_event(process)
                if event["event"] == "transcribing":
                    percent = round(float(event.get("fraction", 0)) * 100)
                    self.partial.emit(f"Transcribing with Voz... {percent}%")
                elif event["event"] == "result":
                    return str(event.get("text", "")).strip()
                elif event["event"] in ("error", "fatal"):
                    raise RuntimeError(f"Voz failed: {event.get('message', 'Unknown model error')}")
        finally:
            audio_path.unlink(missing_ok=True)

    def _start_voz(self):
        with self._voz_lock:
            if self._closed:
                raise RuntimeError("Neyra is shutting down.")
            if self._voz_process and self._voz_process.poll() is None:
                return self._voz_process

            node = shutil.which("node")
            if not node:
                raise RuntimeError("Voz needs Node.js 20 or newer. Install Node.js and run npm install in the Neyra project folder.")
            project_root = Path(__file__).resolve().parent.parent
            script = Path(__file__).resolve().parent / "voz_transcribe.mjs"
            if not script.is_file():
                raise RuntimeError(f"Voz runner not found: {script}")
            process = subprocess.Popen(
                [node, str(script)], cwd=project_root,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self._voz_process = process

        self.partial.emit("Starting Voz and loading its local model...")
        while True:
            event = self._read_voz_event(process)
            if event["event"] == "loading":
                fraction = float(event.get("fraction", 0))
                if fraction >= 1:
                    self.partial.emit("Download complete; loading Voz into memory...")
                else:
                    percent = round(fraction * 100)
                    self.partial.emit(f"Downloading Voz model... {percent}%")
            elif event["event"] == "ready":
                return process
            elif event["event"] in ("error", "fatal"):
                raise RuntimeError(f"Voz failed to load: {event.get('message', 'Unknown model error')}")

    @staticmethod
    def _read_voz_event(process):
        line = process.stdout.readline()
        if not line:
            detail = process.stderr.read().strip()
            raise RuntimeError(detail or f"Voz runtime stopped (exit code {process.poll()}).")
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Voz returned an invalid response: {line[:300]}") from exc
        if not isinstance(event, dict) or "event" not in event:
            raise RuntimeError(f"Voz returned an invalid response: {line[:300]}")
        return event

    def close(self):
        with self._voz_lock:
            self._closed = True
            process = self._voz_process
        if process and process.poll() is None:
            process.stdin.close()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
