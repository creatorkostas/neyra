"""Meeting model bridge and timestamped transcript formatting."""
import json
import math
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
from collections import deque


def bridge_path():
    configured = os.environ.get("NEYRA_MEETING_MODELS")
    if configured:
        candidate = Path(configured).expanduser().resolve()
    else:
        name = "neyra-meeting-models.exe" if os.name == "nt" else "neyra-meeting-models"
        roots = [Path(__file__).resolve().parent.parent, Path(sys.executable).parent]
        candidates = [root / "assets" / "meeting-models" / name for root in roots]
        candidate = next((path for path in candidates if path.is_file()), candidates[0])
    if not candidate.is_file():
        raise RuntimeError("Meeting models are not installed. Run uv run python scripts/setup_meeting_models.py from the Neyra project folder, then retry.")
    return candidate


class MeetingModels:
    def __init__(self):
        self._lock = threading.Lock()
        self._process = None
        self._closed = False

    def request(self, request, progress=lambda message: None, timeout=900):
        executable = bridge_path()
        events = queue.Queue()
        diagnostics = deque(maxlen=20)
        with self._lock:
            if self._closed:
                raise RuntimeError("Neyra is shutting down.")
            process = subprocess.Popen(
                [str(executable)], cwd=executable.parent,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self._process = process

        def read_output():
            try:
                for line in process.stdout:
                    try:
                        event = json.loads(line)
                    except ValueError:
                        diagnostics.append(line.strip())
                        continue
                    if isinstance(event, dict):
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

        threading.Thread(target=read_output, name="meeting-model-output", daemon=True).start()
        threading.Thread(target=read_errors, name="meeting-model-errors", daemon=True).start()
        deadline = time.monotonic() + timeout
        try:
            process.stdin.write(json.dumps(request, allow_nan=False) + "\n")
            process.stdin.close()
            while True:
                if self._closed:
                    raise RuntimeError("Neyra is shutting down.")
                if time.monotonic() > deadline:
                    raise RuntimeError("Meeting model processing timed out. Retry after checking the model downloads.")
                try:
                    event = events.get(timeout=0.2)
                except queue.Empty:
                    continue
                kind = event.get("event")
                if kind == "progress":
                    progress(str(event.get("message", "Processing meeting models...")))
                elif kind == "result":
                    return event
                elif kind in ("error", "fatal"):
                    raise RuntimeError(str(event.get("message", "Meeting model failed.")))
                elif kind == "exited":
                    raise RuntimeError("Meeting model runtime stopped. " + "\n".join(diagnostics))
        finally:
            self._stop(process)
            with self._lock:
                if self._process is process:
                    self._process = None

    @staticmethod
    def _stop(process):
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
        with self._lock:
            self._closed = True
            process = self._process
        if process:
            self._stop(process)


def validated_words(words, duration):
    if not isinstance(words, list):
        raise ValueError("The transcription engine returned no word timings.")
    result = []
    previous = 0.0
    for word in words:
        if not isinstance(word, dict) or not isinstance(word.get("text"), str):
            raise ValueError("Invalid timestamped word.")
        start, end = word.get("start"), word.get("end")
        if any(isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) for value in (start, end)):
            raise ValueError("Word timestamps must be finite numbers.")
        if start < 0 or end < start or start < previous or end > duration + 1.2:
            raise ValueError("Word timestamps fall outside the recording or are out of order.")
        result.append({"text": word["text"], "start": float(start), "end": float(end), "refined": word.get("refined") is True})
        previous = start
    return result


def label_words(words, turns):
    """Keep overlapping speakers visible instead of inventing a single owner."""
    if not isinstance(turns, list):
        raise ValueError("Invalid speaker turns.")
    valid = []
    for turn in turns:
        if not isinstance(turn, dict):
            raise ValueError("Invalid speaker turn.")
        speaker, start, end = turn.get("speaker"), turn.get("start"), turn.get("end")
        if (isinstance(speaker, bool) or not isinstance(speaker, int) or speaker < 0
                or any(isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t) for t in (start, end))
                or start < 0 or end < start):
            raise ValueError("Invalid speaker turn.")
        valid.append((start, end, speaker))
    valid.sort()
    cursor, active = 0, []
    for word in words:
        start, end = word["start"], word["end"]
        while cursor < len(valid) and valid[cursor][0] <= end:
            active.append(valid[cursor])
            cursor += 1
        active = [turn for turn in active if turn[1] >= start]
        overlaps = {}
        for left, right, speaker in active:
            overlap = max(0, min(end, right) - max(start, left))
            if overlap:
                overlaps[speaker] = overlaps.get(speaker, 0) + overlap
        if overlaps:
            best = max(overlaps.values())
            word["speakers"] = sorted(speaker for speaker, amount in overlaps.items() if amount >= best * 0.5)
        else:
            word["speakers"] = []
    return words


def speaker_label(word):
    speakers = word.get("speakers", [])
    return " + ".join(f"Speaker {speaker + 1}" for speaker in speakers) or "Speaker unknown"


def timestamp(seconds):
    millis = round(max(0, seconds) * 1000)
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def meeting_transcript(record):
    words = record.get("words")
    if not isinstance(words, list) or not words:
        return record["text"]
    lines, group = [], []
    previous = None
    for word in words:
        label = speaker_label(word) if record.get("speaker_labels") else ""
        if group and (label != previous or word["start"] - group[-1]["end"] > 1.5 or len(group) >= 35):
            lines.append(f'[{timestamp(group[0]["start"])}] {previous + ": " if previous else ""}' + " ".join(item["text"] for item in group))
            group = []
        group.append(word)
        previous = label
    if group:
        lines.append(f'[{timestamp(group[0]["start"])}] {previous + ": " if previous else ""}' + " ".join(item["text"] for item in group))
    return "\n\n".join(lines)


def suggested_title(text):
    sentence = text.splitlines()[0] if text.strip() else "Meeting notes"
    words = sentence.split()[:9]
    return " ".join(words).rstrip(".,!?;:") or "Meeting notes"
