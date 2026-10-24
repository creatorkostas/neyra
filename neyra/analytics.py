"""Local saved-note statistics and account-scoped Neyra token counters."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import threading

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QScrollArea, QVBoxLayout, QWidget


_TOKEN_KEYS = ("input_tokens", "output_tokens", "total_tokens")
_COUNTERS = (*_TOKEN_KEYS, "cached_input_tokens", "requests")
_STORE_LOCKS = {}
_STORE_LOCKS_LOCK = threading.Lock()


def _count(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _empty():
    return {**dict.fromkeys(_COUNTERS, 0), "started_at": None, "updated_at": None}


class AnalyticsStore:
    """Thread-safe counters for requests made in Neyra, never account-wide usage.

    Persistence is atomic. A failed save leaves the in-memory counters unchanged
    and raises OSError, so the caller can report it without failing its request.
    """

    def __init__(self, path):
        self.path = Path(path)
        with _STORE_LOCKS_LOCK:
            self._lock = _STORE_LOCKS.setdefault(os.path.normcase(str(self.path.resolve())), threading.Lock())
        self._accounts = {}

    def _load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            self._accounts = {}
            return
        except (ValueError, UnicodeError) as exc:
            raise OSError("Neyra could not read its local usage counters.") from exc
        try:
            if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("accounts"), dict):
                raise ValueError("Invalid usage file.")
            accounts = {}
            for account_id, account in data["accounts"].items():
                self._validate_account_id(account_id)
                if not isinstance(account, dict):
                    raise ValueError("Invalid usage counters.")
                account = {**account, "cached_input_tokens": account.get("cached_input_tokens", 0)}
                if (any(not _count(account.get(key)) for key in _COUNTERS)
                        or account["cached_input_tokens"] > account["input_tokens"]):
                    raise ValueError("Invalid usage counters.")
                for key in ("started_at", "updated_at"):
                    if not isinstance(account.get(key), str):
                        raise ValueError("Invalid usage timestamp.")
                    datetime.fromisoformat(account[key])
                hashes = account.get("request_hashes")
                if (not isinstance(hashes, list) or len(hashes) > 1000
                        or any(not isinstance(item, str) or len(item) != 64
                               or any(c not in "0123456789abcdef" for c in item) for item in hashes)):
                    raise ValueError("Invalid request identifiers.")
                # Reconstruct the allowlist so unrelated file fields cannot persist.
                accounts[account_id] = {key: account[key] for key in (*_COUNTERS, "started_at", "updated_at")}
                accounts[account_id]["request_hashes"] = list(hashes)
        except (ValueError, TypeError) as exc:
            raise OSError("Neyra could not read its local usage counters.") from exc
        self._accounts = accounts

    @staticmethod
    def _validate_account_id(account_id):
        if not isinstance(account_id, str) or not account_id.strip():
            raise ValueError("Usage requires an opaque account ID.")

    def record(self, account_id, usage, request_id=None):
        """Record validated provider counters, returning False for a duplicate ID."""
        self._validate_account_id(account_id)
        if not isinstance(usage, dict) or any(not _count(usage.get(key)) for key in _TOKEN_KEYS):
            raise ValueError("Token usage must contain nonnegative integer input, output and total counts.")
        details = usage.get("input_tokens_details", {})
        if not isinstance(details, dict):
            raise ValueError("Input token details must contain valid cached token usage.")
        cached = details.get("cached_tokens", 0)
        if not _count(cached) or cached > usage["input_tokens"]:
            raise ValueError("Cached input tokens must be a nonnegative integer within input tokens.")
        if request_id is not None and (not isinstance(request_id, str) or not request_id):
            raise ValueError("The request ID must be a nonempty string.")
        request_hash = hashlib.sha256(request_id.encode()).hexdigest() if request_id is not None else None
        with self._lock:
            self._load()
            previous = self._accounts.get(account_id)
            if request_hash is not None and previous and request_hash in previous["request_hashes"]:
                return False
            accounts = deepcopy(self._accounts)
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            account = accounts.setdefault(account_id, {**_empty(), "request_hashes": []})
            for key in _TOKEN_KEYS:
                account[key] += usage[key]
            account["cached_input_tokens"] += cached
            account["requests"] += 1
            account["started_at"] = account["started_at"] or now
            account["updated_at"] = now
            if request_hash is not None:
                account["request_hashes"] = (account["request_hashes"] + [request_hash])[-1000:]
            self._save(accounts)
            self._accounts = accounts
            return True

    def _save(self, accounts):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                             prefix=f".{self.path.name}.", suffix=".tmp", delete=False) as handle:
                temporary = Path(handle.name)
                json.dump({"version": 1, "accounts": accounts}, handle, ensure_ascii=False, allow_nan=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def snapshot(self, account_id=None):
        """Return a detached account snapshot, or aggregate every local account."""
        if account_id is not None:
            self._validate_account_id(account_id)
        with self._lock:
            self._load()
            accounts = (list(self._accounts.values()) if account_id is None
                        else [self._accounts[account_id]] if account_id in self._accounts else [])
            result = _empty()
            for account in accounts:
                for key in _COUNTERS:
                    result[key] += account[key]
            if accounts:
                result["started_at"] = min(account["started_at"] for account in accounts)
                result["updated_at"] = max(account["updated_at"] for account in accounts)
            return result


def dictation_stats(records):
    """Saved dictation totals; historical records without timing do not affect WPM."""
    valid = [record for record in records if isinstance(record, dict) and isinstance(record.get("text"), str)]
    words = sum(len(record["text"].split()) for record in valid)
    seconds, timed_words, timed_count = 0, 0, 0
    for record in valid:
        duration = record.get("duration")
        if (isinstance(duration, (int, float)) and not isinstance(duration, bool)
                and math.isfinite(duration) and duration > 0):
            seconds += duration
            timed_words += len(record["text"].split())
            timed_count += 1
    return {"dictations": len(valid), "words": words, "duration": seconds,
            "timed_count": timed_count, "wpm": timed_words * 60 / seconds if seconds else None}


class AnalyticsPanel(QScrollArea):
    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        self.setWidget(content)
        box = QVBoxLayout(content)
        box.setContentsMargins(0, 0, 8, 0)
        box.setSpacing(16)
        heading = QLabel("Your activity")
        heading.setObjectName("workspaceTitle")
        heading.setWordWrap(True)
        box.addWidget(heading)
        self.values = {}
        self._section(box, "Saved voice notes", (
            ("dictations", "Saved dictations"), ("words", "Words in saved dictations"),
            ("duration", "Timed dictation duration"), ("wpm", "Average words per minute"),
            ("meetings", "Saved meetings"),
        ))
        self.timing_hint = self._hint(
            "Words per minute includes only saved dictations with timing. Counts follow your saved notes."
        )
        box.addWidget(self.timing_hint)
        self._section(box, "ChatGPT usage in Neyra", (
            ("input_tokens", "Input tokens"), ("cached_input_tokens", "Cached input tokens"),
            ("output_tokens", "Output tokens"),
            ("total_tokens", "Total tokens"), ("requests", "Requests with reported usage"),
        ))
        self.usage_hint = self._hint("")
        box.addWidget(self.usage_hint)
        box.addStretch()
        self.refresh([], [], _empty())

    @staticmethod
    def _hint(text):
        label = QLabel(text)
        label.setObjectName("muted")
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.PlainText)
        return label

    def _section(self, box, title, rows):
        card = QFrame()
        card.setObjectName("homeCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)
        heading = QLabel(title)
        heading.setObjectName("sectionTitle")
        heading.setWordWrap(True)
        layout.addWidget(heading)
        grid = QGridLayout()
        grid.setVerticalSpacing(8)
        grid.setHorizontalSpacing(18)
        grid.setColumnStretch(0, 1)
        for row, (key, text) in enumerate(rows):
            label = QLabel(text)
            label.setWordWrap(True)
            value = QLabel("0")
            value.setTextFormat(Qt.TextFormat.PlainText)
            value.setWordWrap(True)
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            value.setAccessibleName(text)
            self.values[key] = value
            grid.addWidget(label, row, 0)
            grid.addWidget(value, row, 1)
        layout.addLayout(grid)
        box.addWidget(card)

    def refresh(self, dictations, meetings, usage):
        stats = dictation_stats(dictations)
        for key in ("dictations", "words"):
            self.values[key].setText(f"{stats[key]:,}")
        seconds = round(stats["duration"])
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        self.values["duration"].setText(f"{hours:d}h {minutes:02d}m {seconds:02d}s" if hours
                                        else f"{minutes:d}m {seconds:02d}s")
        self.values["wpm"].setText(f"{stats['wpm']:,.0f}" if stats["wpm"] is not None else "No timed dictations")
        self.values["meetings"].setText(f"{len(meetings):,}")
        for key in _COUNTERS:
            count = usage.get(key, 0)
            self.values[key].setText(f"{count:,}" if _count(count) and not usage.get("error") else "Unavailable")
        since = usage.get("started_at")
        try:
            when = datetime.fromisoformat(since).strftime("%d %b %Y") if isinstance(since, str) else None
        except ValueError:
            when = None
        explanation = (
            (f"Locally tracked for the selected account since {when}. " if when
             else "Tracking starts with the first request that reports usage for the selected account. ")
            + "Neyra requests only. This is not account-wide usage or a remaining quota."
            + " Cached input tokens are provider-reported and already included in Input tokens."
        )
        error = usage.get("error")
        if isinstance(error, str) and error:
            explanation += "\n" + error
        elif not usage:
            explanation = "Connect a ChatGPT account to see its locally tracked Neyra usage. " + explanation
        self.usage_hint.setText(explanation)
