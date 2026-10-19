"""Microphone input; callback only copies samples, never performs inference."""
import queue
import sounddevice as sd
import numpy as np

RATE = 16000
BLOCK = 16000  # One second of audio per streaming inference pass

class Microphone:
    def __init__(self, chunks, level):
        self.chunks = chunks
        self.level = level
        self.stream = None

    def start(self):
        def callback(indata, frames, time_info, status):
            if status:
                pass  # Device under/overruns can be diagnosed separately
            audio = np.array(indata[:, 0], dtype=np.float32, copy=True)
            self.level(float(np.sqrt(np.mean(audio * audio))) if len(audio) else 0)
            self.chunks.put(audio)
        self.stream = sd.InputStream(samplerate=RATE, channels=1, dtype="float32", blocksize=BLOCK, callback=callback)
        self.stream.start()

    def stop(self):
        if self.stream is not None:
            self.stream.stop()
            self.stream.close()
            self.stream = None
        self.chunks.put(None)
