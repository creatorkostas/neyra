"""Dedicated Whistle inference worker. One model is used by one worker thread."""
import threading
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

    def run(self, chunks, keywords=()):
        if self.thread and self.thread.is_alive():
            raise RuntimeError("Transcription already running")

        def worker():
            try:
                from neyra.bundled import configure_bundled_runtime
                configure_bundled_runtime()
                import needle
                committed = []
                def five_second_chunks():
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
                for step in needle.stream(five_second_chunks(), language=LANGUAGE, keywords=keywords):
                    fragment = str(step.get("text") or "").strip()
                    if fragment:
                        committed.append(fragment)
                    pending_text = str(step.get("pending") or "").strip()
                    self.partial.emit(" ".join([*committed, pending_text]).strip())
                self.finished.emit(" ".join(committed).strip())
            except Exception as exc:
                self.failed.emit(f"{type(exc).__name__}: {exc}")

        self.thread = threading.Thread(target=worker, name="whistle-inference", daemon=True)
        self.thread.start()
