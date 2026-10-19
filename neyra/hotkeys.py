"""Global hotkeys using pynput (Windows/X11; not generally Wayland)."""
from pynput import keyboard
from PySide6.QtCore import QObject, Signal

class Hotkeys(QObject):
    hold_start = Signal()
    hold_stop = Signal()
    toggle = Signal()

    def __init__(self):
        super().__init__()
        self.pressed = set()
        self._keys = set()
        self.holding = False
        self.toggle_latched = False
        self.listener = None

    @staticmethod
    def normalize(key):
        if key in (keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r): return "ctrl"
        if key in (keyboard.Key.cmd, keyboard.Key.cmd_l, keyboard.Key.cmd_r): return "win"
        if key in (keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r): return "shift"
        if key in (keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r): return "alt"
        if key == keyboard.Key.space: return "space"
        return None

    def start(self):
        def down(key):
            name = self.normalize(key)
            if name is None: return
            if key in self._keys: return
            self._keys.add(key)
            self.pressed = {self.normalize(value) for value in self._keys}
            if {"ctrl", "win"}.issubset(self.pressed) and not self.holding:
                self.holding = True
                self.hold_start.emit()
            if {"ctrl", "shift", "space"}.issubset(self.pressed) and not self.toggle_latched:
                self.toggle_latched = True
                self.toggle.emit()
        def up(key):
            name = self.normalize(key)
            if name is None: return
            self._keys.discard(key)
            self.pressed = {self.normalize(value) for value in self._keys}
            if self.holding and not {"ctrl", "win"}.issubset(self.pressed):
                self.holding = False
                self.hold_stop.emit()
            if not {"ctrl", "shift", "space"}.issubset(self.pressed):
                self.toggle_latched = False
        self.listener = keyboard.Listener(on_press=down, on_release=up)
        self.listener.start()

    def stop(self):
        if self.listener:
            self.listener.stop()
        self.pressed = set()
        self._keys.clear()
        self.holding = False
        self.toggle_latched = False

    def modifiers_active(self):
        return bool(self.pressed & {"ctrl", "win", "shift", "alt"})
