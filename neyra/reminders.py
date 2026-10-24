"""Deterministic relative reminder commands and durable reminder records."""

from datetime import datetime, time as wall_time, timedelta
import json
import math
import re
import time
import uuid


_EXAMPLE = 'Try "remind me in an hour to throw out the garbage".'
_UNITS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400, "week": 604800}
_SMALL = dict(zip(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split(),
    range(20),
))
_TENS = dict(zip("twenty thirty forty fifty sixty seventy eighty ninety".split(), range(20, 100, 10)))
_MAX_DELAY = 365 * 86400


def _number(text):
    text = text.strip()
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        return float(text)
    if text in ("a", "an"):
        return 1
    words = text.replace("-", " ").split()
    hundreds = 0
    if len(words) >= 2 and words[0] in _SMALL and 1 <= _SMALL[words[0]] <= 9 and words[1] == "hundred":
        hundreds = _SMALL[words[0]] * 100
        words = words[2:]
        if words and words[0] == "and":
            words = words[1:]
            if not words:
                raise ValueError("Incomplete number.")
    if not words and hundreds:
        return hundreds
    if len(words) == 1 and words[0] in _SMALL:
        return hundreds + _SMALL[words[0]]
    if words and words[0] in _TENS:
        if len(words) == 1:
            return hundreds + _TENS[words[0]]
        if len(words) == 2 and words[1] in _SMALL and 1 <= _SMALL[words[1]] <= 9:
            return hundreds + _TENS[words[0]] + _SMALL[words[1]]
    raise ValueError("Use a number and a time unit.")


def _duration(text):
    text = text.lower().strip()
    text = re.sub(r"\bhalf (?:an?|of an?) hour\b", "30 minutes", text)
    text = re.sub(r"\b(?:a )?quarter (?:of an?|an?) hour\b", "15 minutes", text)
    matches = list(re.finditer(r"\b(seconds?|minutes?|hours?|days?|weeks?)\b", text))
    total = 0
    previous = 0
    used = set()
    for index, match in enumerate(matches):
        number = text[previous:match.start()].strip()
        if index:
            number = re.sub(r"^(?:,\s*(?:and\s+)?|and\s+)", "", number)
        unit = match[0].rstrip("s")
        amount = _number(number)
        if amount <= 0 or unit in used:
            raise ValueError("Use a positive, unambiguous duration.")
        used.add(unit)
        total += amount * _UNITS[unit]
        previous = match.end()
    if not matches or text[previous:].strip() or not math.isfinite(total) or not 0 < total <= _MAX_DELAY:
        raise ValueError("Use a delay greater than zero and no longer than 365 days.")
    return total


def _timestamp(value):
    try:
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
            return False
        datetime.fromtimestamp(value)
        return True
    except (OverflowError, OSError, ValueError):
        return False


def parse_reminder(command: str, now: float | None = None) -> tuple[str, float]:
    """Return the task and UTC epoch deadline, or raise a useful ValueError."""
    try:
        if not isinstance(command, str):
            raise ValueError("Use a reminder command.")
        command = command.strip().rstrip(".!? ")
        prefix = re.fullmatch(r"remind\s+me\s*,?\s+in\s+(.+?)\s*,?\s+to\s+(.+)", command, re.IGNORECASE)
        if prefix:
            duration, task = prefix.groups()
        else:
            suffix = re.fullmatch(r"remind\s+me\s+to\s+(.+)\s+in\s+(.+)", command, re.IGNORECASE)
            if not suffix:
                raise ValueError("Include a relative delay and a task.")
            task, duration = suffix.groups()
            # A second timing clause could belong to the task or the reminder.
            for match in re.finditer(r"\bin\s+(.+)", task, re.IGNORECASE):
                try:
                    _duration(match[1])
                except ValueError:
                    continue
                raise ValueError("Use only one reminder delay.")
        task = task.strip().rstrip(".!? ")
        if not task or not any(char.isalnum() for char in task):
            raise ValueError("Include the task to remember.")
        delay = _duration(duration)
        current = time.time() if now is None else now
        if not _timestamp(current):
            raise ValueError("The current time is invalid.")
        due_at = current + delay
        if not _timestamp(due_at) or due_at <= current:
            raise ValueError("The reminder must be in the future.")
        return task, due_at
    except (ValueError, OverflowError) as error:
        raise ValueError(f"{error} {_EXAMPLE}") from None


def snooze_deadline(preset, now=None):
    """Return a future epoch deadline using the local calendar for tomorrow."""
    current = time.time() if now is None else now
    if not _timestamp(current):
        raise ValueError("The current time is invalid.")
    try:
        if preset == "10min":
            due_at = current + 600
        elif preset == "tomorrow":
            tomorrow = datetime.fromtimestamp(current).date() + timedelta(days=1)
            due_at = datetime.combine(tomorrow, wall_time(9)).timestamp()
        else:
            raise ValueError("Choose a supported snooze time.")
        if not _timestamp(due_at) or due_at <= current:
            raise ValueError("Choose a reminder time in the future.")
        return due_at
    except (OverflowError, OSError):
        raise ValueError("Choose a reminder time in the future.") from None


class ReminderStore:
    """Persist pending reminders and the most recent 100 nonpending reminders."""

    def __init__(self, settings):
        self.settings = settings
        self.records = []
        try:
            records = json.loads(settings.value("reminders", "[]"))
        except (TypeError, ValueError):
            return
        if not isinstance(records, list):
            return
        seen = set()
        for record in records:
            if not isinstance(record, dict):
                continue
            identifier = record.get("id")
            text = record.get("text")
            due_at = record.get("due_at")
            created_at = record.get("created_at")
            status = record.get("status")
            if (not isinstance(identifier, str) or not re.fullmatch(r"[0-9a-f]{32}", identifier)
                    or identifier in seen or not isinstance(text, str) or not text.strip()
                    or not _timestamp(due_at) or not _timestamp(created_at)
                    or due_at <= created_at or status not in ("pending", "fired", "done")):
                continue
            seen.add(identifier)
            self.records.append({"id": identifier, "text": text, "due_at": due_at,
                                 "created_at": created_at, "status": status})
            if isinstance(record.get("source_key"), str) and re.fullmatch(r"meeting:[0-9a-f]{64}", record["source_key"]):
                self.records[-1]["source_key"] = record["source_key"]
        self._trim()

    def _trim(self):
        recent = sorted((record for record in self.records if record["status"] != "pending"),
                       key=lambda record: record["due_at"], reverse=True)
        keep = {record["id"] for record in recent[:100]}
        self.records[:] = [record for record in self.records
                           if record["status"] == "pending" or record["id"] in keep]

    def _save(self):
        self._trim()
        self.settings.setValue("reminders", json.dumps(self.records, allow_nan=False))
        sync = getattr(self.settings, "sync", None)
        if callable(sync):
            sync()

    def add(self, command, now=None):
        current = time.time() if now is None else now
        text, due_at = parse_reminder(command, current)
        return self.add_at(text, due_at, now=current)

    def add_at(self, text, due_at, now=None, source_key=None):
        current = time.time() if now is None else now
        if not isinstance(text, str) or not text.strip() or len(text.strip()) > 2000:
            raise ValueError("Enter a reminder task of up to 2,000 characters.")
        if not _timestamp(current) or not _timestamp(due_at) or due_at <= current:
            raise ValueError("Choose a reminder time in the future.")
        if source_key is not None:
            if not isinstance(source_key, str) or not re.fullmatch(r"meeting:[0-9a-f]{64}", source_key):
                raise ValueError("Invalid reminder source.")
            existing = next((record for record in self.records if record.get("source_key") == source_key), None)
            if existing:
                return existing
        text = text.strip()
        record = {"id": uuid.uuid4().hex, "text": text, "due_at": due_at,
                  "created_at": current, "status": "pending"}
        if source_key is not None:
            record["source_key"] = source_key
        self.records.append(record)
        self._save()
        return record

    def snooze(self, identity, due_at, now=None):
        """Requeue a pending or delivered reminder without changing its identity."""
        current = time.time() if now is None else now
        if not _timestamp(current) or not _timestamp(due_at) or due_at <= current:
            raise ValueError("Choose a reminder time in the future.")
        for record in self.records:
            if record["id"] == identity and record["status"] in ("pending", "fired"):
                if due_at <= record["created_at"]:
                    raise ValueError("Choose a reminder time after its creation.")
                record["due_at"] = due_at
                record["status"] = "pending"
                self._save()
                return True
        return False

    def complete(self, identity):
        """Mark a task done separately from acknowledging notification delivery."""
        for record in self.records:
            if record["id"] == identity and record["status"] != "done":
                record["status"] = "done"
                self._save()
                return True
        return False

    def remove(self, record_id):
        for index, record in enumerate(self.records):
            if record["id"] == record_id:
                del self.records[index]
                self._save()
                return True
        return False

    def pending_due(self, now=None):
        """Read due reminders without acknowledging their delivery."""
        current = time.time() if now is None else now
        if not _timestamp(current):
            raise ValueError("The current time is invalid.")
        return sorted((record for record in self.records
                       if record["status"] == "pending" and record["due_at"] <= current),
                      key=lambda record: record["due_at"])

    def mark_fired(self, record_ids):
        """Acknowledge delivered reminders; cancelled records remain absent."""
        identifiers = set(record_ids)
        changed = []
        for record in self.records:
            if record["status"] == "pending" and record["id"] in identifiers:
                record["status"] = "fired"
                changed.append(record)
        if changed:
            self._save()
        return changed

    def take_due(self, now=None):
        due = self.pending_due(now)
        self.mark_fired(record["id"] for record in due)
        return due
