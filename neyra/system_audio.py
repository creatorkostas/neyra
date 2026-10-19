"""Capture the current default output mix through the platform loopback API."""
import threading

import numpy as np
import soundcard as sc


class SystemAudioRecorder:
    def __init__(self, samplerate=16_000):
        self.samplerate = samplerate
        self.stop_event = threading.Event()
        self.chunks = []
        self.error = None
        self.thread = None

    def start(self):
        speaker = sc.default_speaker()
        loopback = sc.get_microphone(speaker.name, include_loopback=True)
        if not loopback.isloopback:
            raise RuntimeError("Could not open loopback capture for the default speaker")

        def capture():
            try:
                with loopback.recorder(samplerate=self.samplerate) as recorder:
                    while not self.stop_event.is_set():
                        frames = recorder.record(numframes=4_800)
                        if len(frames):
                            self.chunks.append(np.asarray(frames, dtype=np.float32).mean(axis=1))
            except Exception as exc:
                self.error = exc
                self.stop_event.set()

        self.thread = threading.Thread(target=capture, name="system-audio-loopback", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=3)
            if self.thread.is_alive():
                raise RuntimeError("System audio capture did not stop cleanly")
        if self.error:
            raise RuntimeError(f"System audio capture failed: {self.error}") from self.error
        return np.concatenate(self.chunks) if self.chunks else np.empty(0, dtype=np.float32)
