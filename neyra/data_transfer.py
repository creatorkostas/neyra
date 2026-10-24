"""Portable local backups and readable exports, without account or device state."""

from copy import deepcopy
from datetime import datetime
import json
import math
import os
from pathlib import Path
import re
import tempfile

from .assistant_tools import AgendaStore
from .meeting import validated_words
from .reminders import ReminderStore
from .shortcuts import DEFAULT_SHORTCUTS, validate_bindings


_COLLECTION_DEFAULTS = {
    "history": [], "meetings": [], "reminders": [], "dictionary": [],
    "vocabulary_corrections": {}, "snippets": {}, "assistant_agenda": [],
    "shortcuts": DEFAULT_SHORTCUTS,
}
_VALUE_DEFAULTS = {
    "style": "Clean up speech", "transcription_engine": "whistle",
    "save_history": True, "close_to_tray": True, "meeting_speakers": False,
    "meeting_cleanup": False, "meeting_organize": True, "meeting_language": "en",
}
_CHOICES = {
    "style": {"Natural", "Clean up speech", "Formal"},
    "transcription_engine": {"whistle", "voz"},
    "meeting_language": {"en", "es", "fr", "it", "pt", "de", "ja", "ko", "zh"},
}
_MAX_BYTES = 64 * 1024 * 1024
_MAX_ITEMS = 10_000


def _json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def _check_json(value):
    """Bound recursive input and reject values JSON cannot represent faithfully."""
    pending = [(value, 0)]
    count = 0
    while pending:
        item, depth = pending.pop()
        count += 1
        if depth > 32 or count > 1_000_000:
            raise ValueError("The backup contains too much nested data.")
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                raise ValueError("Backup field names must be strings.")
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
        elif isinstance(item, float):
            if not math.isfinite(item):
                raise ValueError("Backup numbers must be finite.")
        elif item is not None and not isinstance(item, (str, int, bool)):
            raise ValueError("The backup contains an unsupported value.")
    try:
        if len(_json(value).encode("utf-8")) > _MAX_BYTES:
            raise ValueError("The backup exceeds 64 MiB.")
    except (OverflowError, RecursionError, UnicodeError) as error:
        raise ValueError("The backup contains invalid data.") from error


def _records(records, kind, limit):
    if not isinstance(records, list) or len(records) > limit:
        raise ValueError(f"Invalid {kind} collection or too many records.")
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("text"), str):
            raise ValueError(f"Each {kind} record needs text and an ISO date.")
        try:
            if not isinstance(record.get("time"), str):
                raise ValueError("Missing date")
            datetime.fromisoformat(record["time"])
        except ValueError:
            raise ValueError(f"Each {kind} record needs text and an ISO date.") from None
        if "title" in record and not isinstance(record["title"], str):
            raise ValueError("Note titles must be text.")
        if "duration" in record and (isinstance(record["duration"], bool)
                or not isinstance(record["duration"], (int, float)) or record["duration"] < 0):
            raise ValueError("Note durations must be nonnegative numbers.")
        if kind != "meetings":
            continue
        if "topics" in record and (not isinstance(record["topics"], list) or any(
                not isinstance(topic, dict) or not isinstance(topic.get("name"), str)
                or not isinstance(topic.get("slug"), str) for topic in record["topics"])):
            raise ValueError("Meeting topics need names and slugs.")
        if "warnings" in record and (not isinstance(record["warnings"], list)
                or any(not isinstance(message, str) for message in record["warnings"])):
            raise ValueError("Meeting warnings must be text.")
        if "words" in record:
            try:
                validated_words(record["words"], 10_000_000)
            except (TypeError, OverflowError):
                raise ValueError("Meeting word timestamps are invalid.") from None
            for word in record["words"]:
                if "speakers" in word and (not isinstance(word["speakers"], list) or any(
                        isinstance(speaker, bool) or not isinstance(speaker, int) or speaker < 0
                        for speaker in word["speakers"])):
                    raise ValueError("Meeting speaker identifiers must be nonnegative integers.")
    return records


class _MemorySettings:
    def __init__(self, key, records):
        self.key = key
        self.raw = _json(records)

    def value(self, key, default=None):
        return self.raw if key == self.key else default


def validate_backup(payload):
    """Validate a complete backup and return canonical QSettings key/value pairs."""
    _check_json(payload)
    if (not isinstance(payload, dict) or set(payload) != {"format", "version", "data"}
            or payload["format"] != "neyra-backup" or type(payload["version"]) is not int
            or payload["version"] != 1):
        raise ValueError("Choose a Neyra version 1 backup.")
    data = payload["data"]
    if not isinstance(data, dict) or set(data) != set(_COLLECTION_DEFAULTS) | set(_VALUE_DEFAULTS):
        raise ValueError("The backup must contain exactly the supported portable settings.")
    _records(data["history"], "history", 500)
    _records(data["meetings"], "meetings", 100)
    for key, store_type, limit in (("reminders", ReminderStore, _MAX_ITEMS),
                                   ("assistant_agenda", AgendaStore, 500)):
        records = data[key]
        if not isinstance(records, list) or len(records) > limit:
            raise ValueError(f"Invalid {key} collection or too many records.")
        loaded = store_type(_MemorySettings(key, records)).records
        if loaded != records or len({record["id"] for record in loaded}) != len(records):
            raise ValueError(f"The backup contains invalid or duplicate {key} records.")
    words = data["dictionary"]
    if not isinstance(words, list) or len(words) > _MAX_ITEMS or any(not isinstance(word, str) for word in words):
        raise ValueError("The dictionary must be a list of words or phrases.")
    for key in ("vocabulary_corrections", "snippets"):
        mapping = data[key]
        if not isinstance(mapping, dict) or len(mapping) > _MAX_ITEMS or any(
                not isinstance(value, str) for value in mapping.values()):
            raise ValueError(f"{key} must map text to text.")
        if key == "vocabulary_corrections" and any(not key.strip() or not value.strip()
                                                        for key, value in mapping.items()):
            raise ValueError("Vocabulary corrections need nonempty text.")
    shortcuts = validate_bindings(data["shortcuts"])
    for key, default in _VALUE_DEFAULTS.items():
        value = data[key]
        if type(value) is not type(default) or (key in _CHOICES and value not in _CHOICES[key]):
            raise ValueError(f"Invalid {key} setting.")
    result = {key: _json(shortcuts if key == "shortcuts" else data[key]) for key in _COLLECTION_DEFAULTS}
    result.update({key: data[key] for key in _VALUE_DEFAULTS})
    return result


def _sync(settings):
    settings.sync()
    status = getattr(settings, "status", None)
    if callable(status):
        result = status()
        if getattr(result, "value", result) != 0:
            raise OSError("Settings could not be saved. Check file access and available disk space.")


def create_backup(settings):
    """Snapshot portable settings with complete defaults, excluding account state."""
    _sync(settings)
    data = {}
    for key, default in _COLLECTION_DEFAULTS.items():
        try:
            data[key] = json.loads(settings.value(key, _json(default)))
        except (TypeError, ValueError):
            raise ValueError(f"The saved {key} setting is invalid.") from None
    for key, default in _VALUE_DEFAULTS.items():
        value = settings.value(key, default)
        # QSettings may read persisted INI booleans as strings in a new process.
        if isinstance(default, bool) and isinstance(value, str) and value.lower() in ("true", "false"):
            value = value.lower() == "true"
        data[key] = value
    payload = {"format": "neyra-backup", "version": 1, "data": data}
    canonical = validate_backup(payload)
    payload["data"]["shortcuts"] = json.loads(canonical["shortcuts"])
    return payload


def restore_backup(settings, payload):
    """Replace portable settings only after validation; roll back failed writes."""
    values = validate_backup(payload)
    previous = {key: (settings.contains(key), deepcopy(settings.value(key))) for key in values}
    try:
        for key, value in values.items():
            settings.setValue(key, value)
        _sync(settings)
    except Exception as error:
        rollback_failed = False
        for key, (existed, value) in previous.items():
            try:
                if existed:
                    settings.setValue(key, value)
                else:
                    settings.remove(key)
            except Exception:
                rollback_failed = True
        try:
            _sync(settings)
        except Exception:
            rollback_failed = True
        message = ("Restore failed and rollback could not be confirmed. Check your saved settings."
                   if rollback_failed else "Restore failed; previous settings were restored.")
        raise RuntimeError(message) from error


def export_notes(history, meetings, markdown=True):
    """Export all dictations and meetings in chronological order as Unicode text."""
    _check_json([history, meetings])
    _records(history, "history", 500)
    _records(meetings, "meetings", 100)
    entries = [(record, "Dictation") for record in history] + [(record, "Meeting notes") for record in meetings]
    entries.sort(key=lambda entry: datetime.fromisoformat(entry[0]["time"]).timestamp())
    sections = ["# Neyra notes" if markdown else "Neyra notes"]
    for record, fallback in entries:
        title = " ".join((record.get("title") or fallback).splitlines())
        if markdown:
            title = re.sub(r"([\\`*_{}\[\]<>#+.!|()-])", r"\\\1", title)
        date = datetime.fromisoformat(record["time"]).isoformat(sep=" ", timespec="seconds")
        sections.append(f"{'## ' if markdown else ''}{title}\n{date}\n\n{record['text']}")
    return "\n\n".join(sections) + "\n"


def write_text_atomic(path, text):
    """Replace a UTF-8 text file only after its same-directory temporary is saved."""
    destination = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                         dir=destination.parent, prefix=f".{destination.name}.",
                                         suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
