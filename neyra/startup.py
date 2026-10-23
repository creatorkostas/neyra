"""Manage Neyra's own per-user login entry on Windows and Linux."""
import os
from pathlib import Path
import subprocess
import sys


def application_command():
    if "__compiled__" in globals() or getattr(sys, "frozen", False):
        return [str(Path(sys.argv[0]).resolve()), "--background"]
    return [sys.executable, str(Path(__file__).resolve().parent.parent / "run_neyra.py"), "--background"]


def desktop_exec(command):
    if "=" in command[0]:
        raise RuntimeError("Login startup needs an executable path without an equals sign.")
    arguments = []
    for arg in command:
        quoted = arg.replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$")
        # Desktop values decode string escapes before parsing Exec quoting.
        quoted = quoted.replace("\\", "\\\\").replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
        arguments.append('"' + quoted.replace("%", "%%") + '"')
    return " ".join(arguments)


def autostart_path():
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "autostart" / "neyra.desktop"


def is_enabled():
    if sys.platform == "win32":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
                return bool(winreg.QueryValueEx(key, "Neyra")[0])
        except FileNotFoundError:
            return False
    if sys.platform.startswith("linux"):
        return autostart_path().is_file()
    return False


def set_enabled(enabled):
    if sys.platform == "win32":
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
            if enabled:
                winreg.SetValueEx(key, "Neyra", 0, winreg.REG_SZ, subprocess.list2cmdline(application_command()))
            else:
                try:
                    winreg.DeleteValue(key, "Neyra")
                except FileNotFoundError:
                    pass
    elif sys.platform.startswith("linux"):
        path = autostart_path()
        if enabled:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("[Desktop Entry]\nType=Application\nName=Neyra\n"
                            f"Exec={desktop_exec(application_command())}\nTerminal=false\n", encoding="utf-8")
        else:
            path.unlink(missing_ok=True)
    else:
        raise RuntimeError("Login startup is supported on Windows and Linux.")
