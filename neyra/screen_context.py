"""Explicit screen-reference detection and one-monitor, memory-only capture."""
import base64
import re

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QThread, Qt
from PySide6.QtGui import QCursor, QGuiApplication


MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_IMAGE_EDGE = 1920
_CAPTURE_ERROR = (
    "Screen capture is unavailable. Check screen-recording permissions. "
    "Wayland and macOS support depends on desktop permissions and the capture session."
)
_SCREEN_REQUEST = re.compile(
    r"\b(?:on (?:my|the|this|your) screen|this screen|screenshots?|screen shots?|"
    r"what (?:i|we|you) (?:can )?see|what (?:am i|are we|are you) looking at|"
    r"(?:look at|looking at|based on) (?:my|the|this|your) screen|"
    r"(?:shown|displayed|visible) on screen)\b",
    re.IGNORECASE,
)


def screen_requested(text):
    """Only explicit references authorize capture; generic screen tasks do not."""
    if not isinstance(text, str):
        return False
    text = " ".join(text.replace("’", "'").split())
    if re.search(r"\b(?:don't|do not|never|without) (?:take|taking|capture|capturing|share|sharing|send|sending|use|using|look at|looking at)\b", text, re.IGNORECASE):
        return False
    if re.search(r"\bno (?:screenshots?|screen shots?)\b", text, re.IGNORECASE):
        return False
    return bool(_SCREEN_REQUEST.search(text))


def capture_screen():
    """Capture the cursor's screen on the Qt GUI thread, returning a JPEG data URL.

    The caller hides recording overlays first. Pixels are never written to disk.
    Unsupported capture sessions fail clearly rather than capturing another screen.
    """
    app = QGuiApplication.instance()
    if app is None or QThread.currentThread() != app.thread():
        raise RuntimeError("Screen capture must run on the Qt GUI thread.")
    screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
    if screen is None:
        raise RuntimeError(_CAPTURE_ERROR)
    try:
        pixmap = screen.grabWindow(0)
        if pixmap.isNull():
            raise RuntimeError(_CAPTURE_ERROR)
        image = pixmap.toImage()
        if max(image.width(), image.height()) > MAX_IMAGE_EDGE:
            image = image.scaled(MAX_IMAGE_EDGE, MAX_IMAGE_EDGE, Qt.AspectRatioMode.KeepAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
        encoded = QByteArray()
        buffer = QBuffer(encoded)
        if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
            raise RuntimeError("Could not prepare the screenshot in memory.")
        try:
            if not image.save(buffer, "JPEG", 80):
                raise RuntimeError("Could not encode the screenshot as JPEG.")
        finally:
            buffer.close()
        if not encoded or encoded.size() > MAX_IMAGE_BYTES:
            raise RuntimeError("The screenshot exceeds the 4 MB image limit.")
        return "data:image/jpeg;base64," + base64.b64encode(bytes(encoded)).decode("ascii")
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(_CAPTURE_ERROR) from exc
