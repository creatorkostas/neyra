"""Best-effort text insertion into the previously focused application."""
import os
import shutil
import subprocess
import pyperclip
from pynput.keyboard import Controller, Key


def is_wayland():
    return bool(os.environ.get("WAYLAND_DISPLAY")) and os.environ.get("XDG_SESSION_TYPE") == "wayland"


def insert_text(text):
    if not text.strip():
        return "Nothing to insert"
    if is_wayland():
        # Wayland blocks synthetic keystrokes from ordinary apps by design.
        if not (shutil.which("wl-copy") and shutil.which("wtype")):
            raise RuntimeError("Wayland insertion requires wl-clipboard and wtype (and compositor support). Text remains in the widget for copying.")
        subprocess.run(["wl-copy"], input=text, text=True, check=True)
        subprocess.run(["wtype", "-M", "ctrl", "v", "-m", "ctrl"], check=True)
        return "Pasted via Wayland tools (clipboard now contains transcription)"
    pyperclip.copy(text)
    kb = Controller()
    with kb.pressed(Key.ctrl):
        kb.press("v")
        kb.release("v")
    return "Pasted (clipboard now contains transcription)"
