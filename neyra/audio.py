"""Microphone input; callback only copies samples, never performs inference."""
import queue
import sounddevice as sd
import numpy as np

RATE = 16000
BLOCK = 4000  # Capture short utterances too; inference batches these separately.


def input_devices():
    """Return names with host APIs so duplicate Windows device names are distinct."""
    apis = sd.query_hostapis()
    return [(index, f"{device['name']} ({apis[device['hostapi']]['name']})")
            for index, device in enumerate(sd.query_devices()) if device['max_input_channels'] > 0]


class Microphone:
    def __init__(self, chunks, level, device=None):
        self.chunks = chunks
        self.level = level
        self.stream = None
        self._ended = False
        self.device = device

    def start(self):
        def callback(indata, frames, time_info, status):
            if status:
                pass  # Device under/overruns can be diagnosed separately
            audio = np.array(indata[:, 0], dtype=np.float32, copy=True)
            self.level(float(np.sqrt(np.mean(audio * audio))) if len(audio) else 0)
            if self.chunks is not None:
                self.chunks.put(audio)
        self.stream = sd.InputStream(device=self.device, samplerate=RATE, channels=1, dtype="float32", blocksize=BLOCK, callback=callback)
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
                if self.chunks is not None:
                    self.chunks.put(None)
