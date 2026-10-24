"""Bounded desktop actions and source material for the assistant."""
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path

from .reminders import parse_reminder, _timestamp


def parse_command(text):
    text = re.sub(r"[.!?]+$", "", text.strip()).casefold()
    text = re.sub(r"^(?:please |neyra[, ]+)", "", text).strip()
    if text in ("daily briefing", "my briefing", "read my briefing", "what is on my agenda today", "what's on my agenda today"):
        return "briefing", ""
    if text in ("explain selection", "explain selected text", "explain what i'm looking at"):
        return "selection", ""
    if text.startswith("ask my notes "):
        return "knowledge", text[len("ask my notes "):]
    if text.startswith("remind me "):
        parse_reminder(text)
        return "reminder", text
    timer = re.fullmatch(r"(?:set |start )?(?:a )?timer (?:for )?(.+)", text)
    if timer:
        command = "remind me in " + timer[1] + " to check the timer"
        parse_reminder(command)
        return "reminder", command
    if text in ("volume up", "turn up the volume", "increase volume"):
        return "media", "volume_up"
    if text in ("volume down", "turn down the volume", "decrease volume"):
        return "media", "volume_down"
    if text in ("mute", "mute volume", "toggle mute", "unmute"):
        return "media", "unmute" if text == "unmute" else "mute"
    if text in ("play", "pause", "play music", "pause music", "play pause", "play or pause"):
        return "media", "play_pause"
    if text in ("next track", "next song", "skip song"):
        return "media", "next"
    if text in ("previous track", "previous song"):
        return "media", "previous"
    opened = re.fullmatch(r"(?:open|launch|start) (.+)", text)
    if opened:
        return "open", opened[1]
    raise ValueError('Try "open calculator", "volume up", "pause music", "set a timer for five minutes", or "daily briefing".')


def open_application(name, apps):
    """Launch only a known app or an executable the user explicitly saved."""
    custom = apps.get(name)
    if custom:
        path = Path(custom)
        if not path.is_absolute() or not path.is_file() or (sys.platform == "win32" and path.suffix.lower() != ".exe"):
            raise ValueError("That saved executable is no longer available. Choose it again in Assistant apps.")
        subprocess.Popen([str(path)], close_fds=True)
        return f"Opened {name}."
    if name in ("browser", "web browser"):
        if not webbrowser.open("https://www.google.com"):
            raise RuntimeError("No default browser was found.")
        return "Opened your browser."
    if sys.platform == "win32":
        names = {"calculator": "calc.exe", "notepad": "notepad.exe", "text editor": "notepad.exe", "files": "explorer.exe", "file manager": "explorer.exe"}
        executable = names.get(name)
        if executable:
            # Resolve Windows utilities outside PATH to avoid launching a same-named local file.
            path = Path(os.environ.get("WINDIR", r"C:\Windows")) / ("" if executable == "explorer.exe" else "System32") / executable
            subprocess.Popen([str(path)], close_fds=True)
            return f"Opened {name}."
    else:
        choices = {"calculator": ("gnome-calculator", "kcalc", "galculator"), "text editor": ("gnome-text-editor", "gedit", "kate", "mousepad"), "files": ("nautilus", "dolphin", "thunar"), "file manager": ("nautilus", "dolphin", "thunar")}
        for executable in choices.get(name, ()):
            path = shutil.which(executable)
            if path:
                subprocess.Popen([path], close_fds=True)
                return f"Opened {name}."
    raise ValueError(f'Add "{name}" in Assistant apps and choose its executable first.')


def control_media(action):
    if sys.platform == "win32":
        from pynput.keyboard import Controller, Key
        keys = {"volume_up": Key.media_volume_up, "volume_down": Key.media_volume_down,
                "mute": Key.media_volume_mute, "play_pause": Key.media_play_pause,
                "next": Key.media_next, "previous": Key.media_previous}
        if action == "unmute":
            raise ValueError('Use "toggle mute" on Windows, which sends the system mute key.')
        Controller().tap(keys[action])
    else:
        if action in ("play_pause", "next", "previous"):
            args = ["playerctl", {"play_pause": "play-pause", "next": "next", "previous": "previous"}[action]]
        elif shutil.which("wpctl"):
            args = (["wpctl", "set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", "5%+" if action == "volume_up" else "5%-"]
                    if action in ("volume_up", "volume_down") else ["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "0" if action == "unmute" else "toggle"])
        else:
            args = (["pactl", "set-sink-volume", "@DEFAULT_SINK@", "+5%" if action == "volume_up" else "-5%"]
                    if action in ("volume_up", "volume_down") else ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0" if action == "unmute" else "toggle"])
        if not shutil.which(args[0]):
            raise RuntimeError(f"Install {args[0]} to use this media command on Linux.")
        result = subprocess.run(args, capture_output=True, text=True, timeout=5, check=False)
        if result.returncode:
            raise RuntimeError("The desktop could not apply that command. Check the audio device or active media player.")
    return "Sent " + action.replace("_", " ") + "."


STOP_WORDS = set("a an the i me my you it is was are were in on at of to for and or about what when where did do have has had can could please tell notes meeting".split())


def knowledge_sources(query, dictations, meetings, limit=6):
    terms = {word for word in re.findall(r"\w+", query.casefold()) if len(word) > 2 and word not in STOP_WORDS}
    if not terms:
        return []
    ranked = []
    for kind, records in (("Dictation", dictations), ("Meeting", meetings)):
        for record in records:
            text = record.get("text", "")
            title = record.get("title") or kind
            lower = (title + " " + text).casefold()
            score = sum(1 for term in terms if term in lower)
            if terms and not score:
                continue
            # Include the matching passage even when it occurs late in a long meeting.
            first = min((text.casefold().find(term) for term in terms if term in text.casefold()), default=0)
            start = max(0, first - 900)
            excerpt = text[start:start + 4500]
            ranked.append((score, record.get("time", ""), {"title": title, "time": record.get("time", ""), "text": excerpt, "kind": kind}))
    ranked.sort(key=lambda entry: (entry[0], entry[1]), reverse=True)
    return [entry[2] for entry in ranked[:limit]]


def source_context(sources):
    return "\n\n".join(f'[{i}] {item["kind"]}: {item["title"]} ({item["time"]})\n{item["text"]}' for i, item in enumerate(sources, 1))


def parse_followups(response, transcript):
    value = response.strip()
    if value.startswith("```") and value.endswith("```"):
        value = re.sub(r"^```(?:json)?\s*", "", value)[:-3].strip()
    try:
        items = json.loads(value)
    except (ValueError, TypeError) as exc:
        raise ValueError("The assistant did not return a valid action list. Try extracting again.") from exc
    if not isinstance(items, list) or len(items) > 30:
        raise ValueError("The assistant returned an invalid action list.")
    result = []
    for item in items:
        if (not isinstance(item, dict) or not isinstance(item.get("text"), str)
                or not isinstance(item.get("evidence"), str) or not item["text"].strip()
                or len(item["text"]) > 500 or len(item["evidence"]) < 5
                or item["evidence"] not in transcript):
            raise ValueError("An action could not be traced to the meeting transcript. Try extracting again.")
        result.append({"text": item["text"].strip(), "evidence": item["evidence"]})
    return result


class AgendaStore:
    def __init__(self, settings):
        self.settings = settings
        try:
            records = json.loads(settings.value("assistant_agenda", "[]"))
        except (ValueError, TypeError):
            records = []
        self.records = [r for r in records if isinstance(r, dict) and isinstance(r.get("id"), str)
                        and isinstance(r.get("text"), str) and r["text"].strip() and _timestamp(r.get("at"))] if isinstance(records, list) else []

    def save(self):
        self.settings.setValue("assistant_agenda", json.dumps(self.records, allow_nan=False))
        self.settings.sync()

    def add(self, text, at):
        if not text.strip() or len(text.strip()) > 500 or not _timestamp(at):
            raise ValueError("Enter an agenda item of up to 500 characters and a valid date.")
        if len(self.records) >= 500:
            raise ValueError("Remove old agenda items before adding more.")
        self.records.append({"id": uuid.uuid4().hex, "text": text.strip(), "at": at})
        self.save()

    def remove(self, identity):
        self.records[:] = [r for r in self.records if r["id"] != identity]
        self.save()


def daily_briefing(reminders, agenda, now=None):
    current = datetime.fromtimestamp(time.time() if now is None else now)
    end = (current.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)).timestamp()
    events = sorted((r for r in agenda if datetime.fromtimestamp(r["at"]).date() == current.date()), key=lambda r: r["at"])
    due = sorted((r for r in reminders if r["status"] == "pending" and r["due_at"] < end), key=lambda r: r["due_at"])
    lines = [f'Your briefing for {current.strftime("%A, %B %d")}.']
    lines.append(f"You have {len(events)} agenda items today and {len(due)} reminders due by tonight.")
    for event in events:
        lines.append(f'At {datetime.fromtimestamp(event["at"]).strftime("%H:%M")}: {event["text"]}.')
    for reminder in due:
        label = "Overdue" if reminder["due_at"] <= current.timestamp() else "At " + datetime.fromtimestamp(reminder["due_at"]).strftime("%H:%M")
        lines.append(f'{label}: {reminder["text"]}.')
    return "\n\n".join(lines)
