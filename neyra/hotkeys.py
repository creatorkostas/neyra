"""Configurable global hotkeys using pynput (Windows/X11; not generally Wayland)."""
import threading
from pynput import keyboard
from PySide6.QtCore import QObject, Signal
from .shortcuts import DEFAULT_SHORTCUTS, parse_shortcut, validate_bindings


class Hotkeys(QObject):
    hold_start = Signal()
    hold_stop = Signal()
    toggle = Signal()
    reminder_start = Signal()
    reminder_stop = Signal()
    assistant_start = Signal()
    assistant_stop = Signal()
    selection_requested = Signal()

    def __init__(self, bindings=None):
        super().__init__()
        self._lock = threading.RLock()
        self.pressed = set()
        self._keys = set()
        self.holding = False
        self.toggle_latched = False
        self.reminder_holding = False
        self.assistant_holding = False
        self.selection_latched = False
        self.listener = None
        self._generation = 0
        self.set_bindings(bindings or DEFAULT_SHORTCUTS)

    def set_bindings(self, bindings, persist=None):
        canonical = validate_bindings(bindings)
        with self._lock:
            if self._keys:
                raise ValueError("Release all shortcut keys before changing shortcuts.")
            if persist is not None:
                persist()
            self.bindings = {action: parse_shortcut(value) for action, value in canonical.items()}

    @staticmethod
    def normalize(key):
        if key in (keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r): return "ctrl"
        if key in (keyboard.Key.cmd, keyboard.Key.cmd_l, keyboard.Key.cmd_r): return "win"
        if key in (keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r): return "shift"
        if key in (keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r): return "alt"
        if key == keyboard.Key.space: return "space"
        name = getattr(key, "name", "")
        if name in {f"f{i}" for i in range(1, 13)}:
            return name
        char = getattr(key, "char", None)
        if char:
            char = char.lower()
            if len(char) == 1 and 1 <= ord(char) <= 26:
                return chr(ord(char) + 96)
            if len(char) == 1 and char in "abcdefghijklmnopqrstuvwxyz0123456789":
                return char
        vk = getattr(key, "vk", None)
        if isinstance(vk, int) and (65 <= vk <= 90 or 48 <= vk <= 57):
            return chr(vk).lower()
        return None

    def start(self):
        generation = self._generation

        def down(key):
            with self._lock:
                if generation != self._generation or self.normalize(key) is None or key in self._keys:
                    return
                self._keys.add(key)
                self.pressed = {self.normalize(value) for value in self._keys}
                if any((self.holding, self.reminder_holding, self.assistant_holding,
                        self.toggle_latched, self.selection_latched)):
                    return
                for action, flag, signal in (
                    ("dictation", "holding", self.hold_start),
                    ("reminder", "reminder_holding", self.reminder_start),
                    ("assistant", "assistant_holding", self.assistant_start),
                    ("toggle", "toggle_latched", self.toggle),
                    ("selection", "selection_latched", self.selection_requested),
                ):
                    if self.pressed == self.bindings[action]:
                        setattr(self, flag, True)
                        signal.emit()
                        break

        def up(key):
            with self._lock:
                if generation != self._generation or self.normalize(key) is None:
                    return
                self._keys.discard(key)
                name = self.normalize(key)
                if name not in {"ctrl", "alt", "shift", "win"}:
                    self._keys = {value for value in self._keys if self.normalize(value) != name}
                self.pressed = {self.normalize(value) for value in self._keys}
                for action, flag, signal in (
                    ("dictation", "holding", self.hold_stop),
                    ("reminder", "reminder_holding", self.reminder_stop),
                    ("assistant", "assistant_holding", self.assistant_stop),
                ):
                    if getattr(self, flag) and not self.bindings[action].issubset(self.pressed):
                        setattr(self, flag, False)
                        signal.emit()
                for action, flag in (("toggle", "toggle_latched"), ("selection", "selection_latched")):
                    if not self.bindings[action].issubset(self.pressed):
                        setattr(self, flag, False)
        self.listener = keyboard.Listener(on_press=down, on_release=up)
        self.listener.start()

    def stop(self):
        with self._lock:
            self._generation += 1
            if self.listener:
                self.listener.stop()
            self.pressed = set()
            self._keys.clear()
            self.holding = self.reminder_holding = self.assistant_holding = False
            self.toggle_latched = self.selection_latched = False

    def modifiers_active(self):
        with self._lock:
            return bool(self.pressed & {"ctrl", "win", "shift", "alt"})
