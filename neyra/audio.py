"""Microphone input; callback only copies samples, never performs inference."""
import queue
import sounddevice as sd
import numpy as np

RATE = 16000
BLOCK = 4000  # Capture short utterances too; inference batches these separately.

class Microphone:
    def __init__(self, chunks, level):
        self.chunks = chunks
        self.level = level
        self.stream = None
        self._ended = False

    def start(self):
        def callback(indata, frames, time_info, status):
            if status:
                pass  # Device under/overruns can be diagnosed separately
            audio = np.array(indata[:, 0], dtype=np.float32, copy=True)
            self.level(float(np.sqrt(np.mean(audio * audio))) if len(audio) else 0)
            self.chunks.put(audio)
        self.stream = sd.InputStream(samplerate=RATE, channels=1, dtype="float32", blocksize=BLOCK, callback=callback)
        try:
            self.stream.start()
        except Exception:
            self.stop()
            raise

    def stop(self):
        stream, self.stream = self.stream, None
        try:
            if stream is not None:
                try:
                    stream.stop()
                finally:
                    stream.close()
        finally:
            if not self._ended:
                self._ended = True
                self.chunks.put(None)
