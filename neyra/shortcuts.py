"""Portable shortcut preferences, validation, and human-readable labels."""
import json

DEFAULT_SHORTCUTS = {
    "dictation": "Ctrl+Win",
    "toggle": "Ctrl+Shift+Space",
    "reminder": "Ctrl+Alt+Space",
    "assistant": "Ctrl+Alt+A",
    "selection": "Ctrl+Alt+E",
}
SHORTCUT_LABELS = {
    "dictation": "Hold to dictate", "toggle": "Toggle dictation",
    "reminder": "Hold for a reminder", "assistant": "Hold for a command",
    "selection": "Capture selected text",
}
MODIFIERS = ("ctrl", "alt", "shift", "win")
ALIASES = {"control": "ctrl", "meta": "win", "cmd": "win", "super": "win",
           "windows": "win", "option": "alt"}
RESERVED = {frozenset(keys.split("+")) for keys in (
    "alt+f4", "ctrl+alt+delete", "win+l", "win+d", "ctrl+shift+escape",
    "ctrl+c", "ctrl+v", "ctrl+x", "ctrl+z", "ctrl+a", "ctrl+s", "ctrl+w",
    "ctrl+q", "alt+tab", "win+tab",
)}


def parse_shortcut(value):
    if not isinstance(value, str) or len(value) > 80:
        raise ValueError("Enter a shortcut such as Ctrl+Alt+R.")
    parts = [ALIASES.get(part.strip().lower(), part.strip().lower()) for part in value.split("+")]
    allowed = set(MODIFIERS) | set("abcdefghijklmnopqrstuvwxyz0123456789") | {"space"}
    allowed.update(f"f{i}" for i in range(1, 13))
    if any(part not in allowed for part in parts) or len(set(parts)) != len(parts):
        raise ValueError("Use Ctrl, Alt, Shift, Win, letters, digits, Space, or F1–F12 without repeating a key.")
    keys = frozenset(parts)
    if len(keys) < 2 or not keys.intersection(MODIFIERS) or len(keys.difference(MODIFIERS)) > 1:
        raise ValueError("Use at least one modifier and at most one letter, digit, function key, or Space.")
    return keys


def validate_bindings(bindings):
    if not isinstance(bindings, dict) or set(bindings) != set(DEFAULT_SHORTCUTS):
        raise ValueError("Provide all five Neyra shortcuts.")
    parsed = {action: parse_shortcut(value) for action, value in bindings.items()}
    pairs = list(parsed.items())
    for index, (action, keys) in enumerate(pairs):
        for other, other_keys in pairs[index+1:]:
            if keys.issubset(other_keys) or other_keys.issubset(keys):
                raise ValueError(f"{SHORTCUT_LABELS[action]} conflicts with {SHORTCUT_LABELS[other]}. Choose combinations that do not contain each other.")
    return {action: "+".join(key.title() for key in (*MODIFIERS, *sorted(keys.difference(MODIFIERS))) if key in keys)
            for action, keys in parsed.items()}


def shortcut_warnings(bindings):
    return [f"{SHORTCUT_LABELS[action]}: {value} is commonly used by your system or other apps."
            for action, value in bindings.items() if parse_shortcut(value) in RESERVED]


def load_bindings(settings):
    try:
        return validate_bindings(json.loads(settings.value("shortcuts", json.dumps(DEFAULT_SHORTCUTS))))
    except (TypeError, ValueError):
        return dict(DEFAULT_SHORTCUTS)


def shortcut_label(bindings, action):
    return bindings[action].replace("+", " + ")
