"""Temporary output muting, serialized away from the GUI thread."""
from contextlib import contextmanager
import ctypes
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import uuid


def _run(*args):
    return subprocess.run(
        args, check=True, capture_output=True, text=True, timeout=3,
        env={**os.environ, "LC_ALL": "C"},
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    ).stdout.strip()


class _LinuxOutput:
    def snapshot(self):
        failures = []
        for tool in ("pactl", "wpctl"):
            if not shutil.which(tool):
                continue
            try:
                if tool == "pactl":
                    sink = _run(tool, "get-default-sink")
                    if not sink or sink.startswith("@"):
                        raise RuntimeError("Cannot identify the default output sink.")
                    state = _run(tool, "get-sink-mute", sink)
                    if state not in ("Mute: yes", "Mute: no"):
                        raise RuntimeError("Cannot read the output mute state.")
                    return (tool, sink), state == "Mute: yes"
                info = _run(tool, "inspect", "@DEFAULT_AUDIO_SINK@")
                match = re.search(r"^id (\d+),", info, re.MULTILINE)
                if not match:
                    raise RuntimeError("Cannot identify the default output sink.")
                sink = match[1]
                state = _run(tool, "get-volume", sink)
                if not re.fullmatch(r"Volume:\s+\d+(?:\.\d+)?(?:\s+\[MUTED\])?", state):
                    raise RuntimeError("Cannot read the output mute state.")
                return (tool, sink), "[MUTED]" in state
            except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
                failures.append(str(exc))
        raise RuntimeError("Output muting requires a working pactl or wpctl. " + "; ".join(failures))

    def set_muted(self, target, muted):
        tool, sink = target
        _run(tool, "set-sink-mute" if tool == "pactl" else "set-mute", sink, str(int(muted)))


class _MacOutput:
    def snapshot(self):
        state = _run("osascript", "-e", "output muted of (get volume settings)")
        if state not in ("true", "false"):
            raise RuntimeError("Cannot read the output mute state.")
        return None, state == "true"

    def set_muted(self, target, muted):
        _run("osascript", "-e", f"set volume output muted {str(muted).lower()}")


class _GUID(ctypes.Structure):
    _fields_ = [("data", ctypes.c_ubyte * 16)]

    def __init__(self, value):
        super().__init__()
        self.data[:] = uuid.UUID(value).bytes_le


def _check(result):
    if result < 0:
        raise OSError(f"CoreAudio failed (HRESULT 0x{result & 0xffffffff:08x}).")


def _com_call(pointer, index, argtypes=(), args=()):
    table = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    method = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)(table[index])
    return method(pointer, *args)


class _WindowsOutput:
    @contextmanager
    def _endpoint(self, target=None):
        ole = ctypes.OleDLL("ole32")
        ole.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        ole.CoInitializeEx.restype = ctypes.c_long
        ole.CoCreateInstance.argtypes = [ctypes.POINTER(_GUID), ctypes.c_void_p,
                                        ctypes.c_uint32, ctypes.POINTER(_GUID),
                                        ctypes.POINTER(ctypes.c_void_p)]
        ole.CoCreateInstance.restype = ctypes.c_long
        ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
        ole.CoTaskMemFree.restype = None
        ole.CoUninitialize.argtypes = []
        ole.CoUninitialize.restype = None
        _check(ole.CoInitializeEx(None, 0))
        enumerator, device, volume = (ctypes.c_void_p() for _ in range(3))
        try:
            _check(ole.CoCreateInstance(
                ctypes.byref(_GUID("bcde0395-e52f-467c-8e3d-c4579291692e")), None, 23,
                ctypes.byref(_GUID("a95664d2-9614-4f35-a746-de8db63617e6")),
                ctypes.byref(enumerator),
            ))
            if target is None:
                # eRender, eMultimedia. Save the ID before changing anything.
                _check(_com_call(enumerator, 4, (ctypes.c_int, ctypes.c_int,
                                                ctypes.POINTER(ctypes.c_void_p)),
                                 (0, 1, ctypes.byref(device))))
            else:
                _check(_com_call(enumerator, 5, (ctypes.c_wchar_p,
                                                ctypes.POINTER(ctypes.c_void_p)),
                                 (target, ctypes.byref(device))))
            identifier = ctypes.c_void_p()
            _check(_com_call(device, 5, (ctypes.POINTER(ctypes.c_void_p),),
                             (ctypes.byref(identifier),)))
            try:
                target = ctypes.wstring_at(identifier)
            finally:
                ole.CoTaskMemFree(identifier)
            _check(_com_call(device, 3, (ctypes.POINTER(_GUID), ctypes.c_uint32,
                                        ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)),
                             (ctypes.byref(_GUID("5cdf2c82-841e-4546-9722-0cf74078229a")),
                              23, None, ctypes.byref(volume))))
            yield target, volume
        finally:
            for pointer in (volume, device, enumerator):
                if pointer:
                    _com_call(pointer, 2)
            ole.CoUninitialize()

    def snapshot(self):
        with self._endpoint() as (target, volume):
            muted = ctypes.c_int()
            _check(_com_call(volume, 15, (ctypes.POINTER(ctypes.c_int),), (ctypes.byref(muted),)))
            return target, bool(muted.value)

    def set_muted(self, target, muted):
        with self._endpoint(target) as (_, volume):
            _check(_com_call(volume, 14, (ctypes.c_int, ctypes.c_void_p), (int(muted), None)))


def _output():
    if sys.platform == "win32":
        return _WindowsOutput()
    if sys.platform == "darwin":
        return _MacOutput()
    if sys.platform.startswith("linux"):
        return _LinuxOutput()
    raise RuntimeError("Temporary output muting is unsupported on this platform.")


class SpeakerMute:
    """Idempotent begin/end with restoration on close; all methods return promptly.

    Errors are passed as strings to on_error on the worker thread. A Qt caller
    should pass a signal's emit method. Call close during application shutdown;
    its non-daemon worker finishes the queued restoration before process exit.
    """

    def __init__(self, on_error=None):
        self._on_error = on_error
        self._queue = queue.Queue()
        self._lock = threading.Lock()
        self._closed = False
        self._thread = None

    def _submit(self, action):
        with self._lock:
            if self._closed:
                return
            if action == "close":
                self._closed = True
            self._queue.put(action)
            if self._thread is None:
                self._thread = threading.Thread(target=self._work, name="speaker-mute", daemon=False)
                self._thread.start()

    def begin(self):
        self._submit("begin")

    def end(self):
        self._submit("end")

    def close(self):
        self._submit("close")

    def _error(self, exc):
        if self._on_error:
            try:
                self._on_error(f"Could not change speaker mute: {exc}")
            except Exception:
                pass

    def _work(self):
        output = None
        saved = None
        active = False

        def restore():
            nonlocal saved
            if saved is None:
                return True
            for _ in range(2):
                try:
                    output.set_muted(*saved)
                    saved = None
                    return True
                except Exception as exc:
                    self._error(exc)
            return False

        while True:
            action = self._queue.get()
            try:
                if action == "begin":
                    if active:
                        continue
                    if not restore():
                        continue
                    output = _output()
                    saved = output.snapshot()
                    if not saved[1]:
                        output.set_muted(saved[0], True)
                    active = True
                else:
                    active = False
                    restore()
                    if action == "close":
                        return
            except Exception as exc:
                self._error(exc)
                restore()
            finally:
                self._queue.task_done()
