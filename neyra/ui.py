"""Dashboard icons, theme and the dated transcript feed."""
from datetime import datetime
import math
import time
from PySide6.QtCore import Qt, QSize, QByteArray, Signal, QTimer
from PySide6.QtGui import QIcon, QPixmap, QPainter, QPen, QColor
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QApplication, QWidget, QScrollArea, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QMenu, QComboBox, QListView, QLineEdit,
    QDialog, QMessageBox, QTextEdit, QTabWidget, QCheckBox, QTableWidget,
    QTableWidgetItem, QAbstractItemView, QHeaderView, QProgressBar,
)
from .text_tools import meeting_brief
from .meeting import meeting_transcript, timestamp, speaker_label

PATHS = {
    "home": '<path d="m3 10 9-7 9 7v11H3zM9 21v-8h6v8"/>',
    "notes": '<path d="M5 3h14v18H5zM9 8h6M9 12h6M9 16h4"/>',
    "brand": '<path d="M3 9v6M7.5 4v16M12 7v10M16.5 2v20M21 10v4"/>',
    "assistant": '<path d="m12 2 2.8 7.2L22 12l-7.2 2.8L12 22l-2.8-7.2L2 12l7.2-2.8z"/>',
    "dictation": '<rect x="9" y="2" width="6" height="13" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3M9 22h6"/>',
    "notetaker": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="4"/>',
    "reminders": '<path d="M5 17h14l-2-3V9a5 5 0 0 0-10 0v5zM10 20a2 2 0 0 0 4 0M12 2v2"/>',
    "insights": '<path d="M4 3v18h17M8 16v-5M13 16V6M18 16v-8"/>',
    "dictionary": '<path d="M6 3h9l4 4v14H6zM15 3v5h4M10 12v5h4v-5z"/>',
    "snippets": '<circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="m8 8 13 13M8 16 21 3"/>',
    "style": '<path d="M3 5h12M9 5v16M16 11h6M19 11v10"/>',
    "settings": '<path d="M9.17 5.16 L10.59 4.74 L10.09 2.18 L13.91 2.18 L13.41 4.74 L14.83 5.16 L14.83 5.16 L16.14 5.87 L17.59 3.71 L20.29 6.41 L18.13 7.86 L18.84 9.17 L18.84 9.17 L19.26 10.59 L21.82 10.09 L21.82 13.91 L19.26 13.41 L18.84 14.83 L18.84 14.83 L18.13 16.14 L20.29 17.59 L17.59 20.29 L16.14 18.13 L14.83 18.84 L14.83 18.84 L13.41 19.26 L13.91 21.82 L10.09 21.82 L10.59 19.26 L9.17 18.84 L9.17 18.84 L7.86 18.13 L6.41 20.29 L3.71 17.59 L5.87 16.14 L5.16 14.83 L5.16 14.83 L4.74 13.41 L2.18 13.91 L2.18 10.09 L4.74 10.59 L5.16 9.17 L5.16 9.17 L5.87 7.86 L3.71 6.41 L6.41 3.71 L7.86 5.87 L9.17 5.16 Z"/><circle cx="12" cy="12" r="3.1"/>',
    "help": '<circle cx="12" cy="12" r="9"/><path d="M9 8a3 3 0 0 1 6 1c0 2-3 2-3 5M12 17h.01"/>',
    "search": '<circle cx="10" cy="10" r="6"/><path d="m15 15 6 6"/>',
    "copy": '<rect x="8" y="8" width="12" height="13" rx="2"/><path d="M15 5V3H3v13h2"/>',
    "more": '<circle cx="12" cy="5" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="12" cy="19" r="1"/>',
    "sidebar": '<rect x="3" y="4" width="18" height="16" rx="1"/><path d="M9 4v16"/>',
    "close": '<path d="m6 6 12 12M6 18 18 6"/>',
    "minimize": '<path d="M5 12h14"/>',
    "maximize": '<rect x="5" y="5" width="14" height="14"/>',
    "wave": '<path d="M3 7v10M7 3v18M11 9v6M15 5v14M19 2v20M23 7v10"/>',
    "calendar": '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 2v6M17 2v6M3 11h18M7 15h1M12 15h1M17 15h1"/>',
    "refresh": '<path d="M20 7v5h-5M4 17v-5h5M6 7a7 7 0 0 1 12-2l2 2M4 17l2 2a7 7 0 0 0 12-2"/>',
}


def icon(name, size=20, color="#1b233c"):
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"><g fill="none" stroke="{color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">{PATHS[name]}</g></svg>'
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    QSvgRenderer(QByteArray(svg.encode())).render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(2)
    return QIcon(pixmap)


def app_icon():
    """Opaque blue tile keeps the white waveform visible on any desktop theme."""
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
           '<rect x="1" y="1" width="30" height="30" rx="7" fill="#365bd6"/>'
           '<g transform="translate(5 5) scale(.9167)" fill="none" stroke="white" '
           'stroke-width="2.4" stroke-linecap="round">' + PATHS["brand"] + '</g></svg>')
    renderer = QSvgRenderer(QByteArray(svg.encode()))
    result = QIcon()
    for size in (16, 20, 24, 32, 48, 64, 128, 256):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        result.addPixmap(pixmap)
    return result


def icon_button(name, tooltip, parent=None):
    button = QPushButton(parent)
    button.setObjectName("iconButton")
    button.setIcon(icon(name))
    button.setIconSize(QSize(18, 18))
    button.setFixedSize(30, 30)
    button.setToolTip(tooltip)
    button.setAccessibleName(tooltip)
    button.setAutoDefault(False)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


THEME = """
QDialog { background: #f5f6f9; color: #171c2d; font-family: 'Segoe UI'; font-size: 14px; }
QDialog#dashboard { background: transparent; }
QWidget { color: #171c2d; font-family: 'Segoe UI'; font-size: 14px; }
QLabel { background: transparent; border: none; }
QFrame#surface { background: #ffffff; border: 1px solid #dde0e7; border-radius: 10px; }
QFrame#sidebar, QWidget#windowBar { background: transparent; border: none; }
QLabel#heading { font-size: 22px; font-weight: 600; }
QLabel#brand { font-size: 25px; font-weight: 700; color: #1b233c; }
QLabel#muted { color: #565a6a; font-size: 13px; }
QLabel#dateLabel { color: #565a6a; font-size: 12px; letter-spacing: 1px; padding: 14px 0; }
QPushButton { color: #171c2d; background: #ebecf0; border: 1px solid transparent; border-radius: 8px; padding: 8px 13px; }
QPushButton:hover { background: #dde0e8; }
QPushButton:pressed { background: #ced3e1; }
QPushButton:disabled { color: #979087; background: #eeeff2; }
QPushButton:focus { border-color: #365bd6; }
QPushButton#nav { background: transparent; text-align: center; padding: 8px 10px; }
QPushButton#nav:checked, QPushButton#nav:hover { background: #dee2ed; }
QPushButton#primary { background: #365bd6; color: white; }
QPushButton#primary:hover { background: #2949ba; }
QPushButton#primary:pressed { background: #203b97; }
QPushButton#primary:disabled { color: #646878; background: #e3e5eb; }
QPushButton#iconButton { background: transparent; padding: 4px; border-radius: 5px; }
QPushButton#iconButton:hover { background: #e7e9ee; }
QPushButton::menu-indicator { image: none; width: 0; }
QFrame#summaryCard, QFrame#promoCard { background: #f3f4f7; border: 1px solid #dde0e7; border-radius: 10px; }
QFrame#promoCard { background: #fffdf9; border-radius: 12px; }
QFrame#transcriptRow { background: transparent; border: none; border-bottom: 1px solid #dde0e7; }
QFrame#transcriptRow:hover { background: #f1f2f6; }
QFrame#divider { background: #dde0e7; border: none; }
QFrame#meetingOverview, QFrame#meetingCard, QFrame#meetingEmpty { background: #f3f4f7; border: none; border-radius: 16px; }
QFrame#meetingIntro { background: #f0f2f7; border: 1px solid #bcc4d9; border-radius: 12px; }
QPushButton#meetingStart { background: #dee2ed; color: #19223d; padding: 9px 14px; }
QPushButton#meetingStart:hover { background: #c5cbde; }
QPushButton#meetingStart:disabled { background: #ede9e2; color: #888078; }
QPushButton#textButton { background: transparent; padding: 7px; }
QTabWidget::pane { border: 1px solid #dde0e7; border-radius: 8px; background: white; }
QTabBar::tab { background: transparent; padding: 10px 16px; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { border-bottom-color: #365bd6; }
QTabBar::tab:focus { background: #dee2ed; }
QScrollArea, QScrollArea > QWidget > QWidget, QStackedWidget { background: transparent; border: none; }
QScrollBar:vertical { width: 7px; background: transparent; margin: 2px; }
QScrollBar::handle:vertical { background: #d8d3cb; border-radius: 3px; min-height: 35px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QLineEdit, QTextEdit, QComboBox { background: white; color: #171c2d; border: 1px solid #d3d6e0; border-radius: 8px; padding: 10px; selection-background-color: #ccd2e4; selection-color: #171c2d; }
QLineEdit:focus, QTextEdit:focus { border-color: #365bd6; }
QTextEdit:read-only { background: #f6f7f9; }
QDateTimeEdit { background: white; color: #171c2d; border: 1px solid #d3d6e0; border-radius: 8px; padding: 8px; min-height: 22px; }
QDateTimeEdit:focus { border-color: #365bd6; }
QDateTimeEdit { padding-right: 38px; }
QDateTimeEdit::drop-down { subcontrol-origin: padding; subcontrol-position: top right; width: 34px; border: none; background: transparent; }
QDateTimeEdit::down-arrow { image: none; width: 0; height: 0; border: none; }
QComboBox { padding-right: 38px; min-height: 22px; }
QComboBox:hover { border-color: #b9b1a6; }
QComboBox:focus, QComboBox:on { border-color: #365bd6; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: top right; width: 34px; border: none; background: transparent; }
QComboBox::down-arrow { image: none; width: 0; height: 0; border: none; }
QComboBox QAbstractItemView { background: white; color: #171c2d; border: 1px solid #d3d6e0; border-radius: 8px; padding: 5px; outline: 0; selection-background-color: #dee2ed; selection-color: #171c2d; }
QComboBox QAbstractItemView::item { min-height: 30px; padding: 3px 8px; border: none; border-radius: 4px; }
QListWidget, QTableWidget { background: #ffffff; color: #171c2d; border: 1px solid #eae6de; border-radius: 9px; outline: 0; }
QListWidget::item { padding: 14px; border-bottom: 1px solid #eeeae3; }
QListWidget::item:selected { background: #f0ece4; color: #171c2d; }
QHeaderView::section { color: #686057; background: #eff0f4; border: 0; padding: 10px; }
QProgressBar { background: #dbdee7; border: 0; border-radius: 3px; max-height: 6px; min-height: 6px; }
QProgressBar::chunk { background: #365bd6; border-radius: 3px; }
QMenu { background: white; color: #171c2d; border: 1px solid #dde0e7; padding: 5px; }
QMenu::item { padding: 7px 18px; }
QMenu::item:selected { background: #eeeae2; }
QFrame#captureCard { background: #202a46; border: none; border-radius: 18px; }
QLabel#captureTitle { color: #ffffff; font-size: 19px; font-weight: 600; }
QLabel#captureDetail { color: #c4cce0; font-size: 12px; }
QLabel#engineBadge { color: #263256; background: #dbdfea; border-radius: 9px; padding: 5px 10px; font-size: 12px; }
QLabel#engineBadge[state="ready"] { color: #b9c5e9; background: #2c3248; }
QLabel#engineBadge[state="error"] { color: #ffc3c7; background: #62363e; }
QPushButton#recordButton { background: #365bd6; color: #ffffff; font-weight: 600; padding: 12px 22px; border-radius: 12px; }
QPushButton#recordButton:hover { background: #2949ba; }
QPushButton#recordButton[recording="true"] { background: #ffd0ca; color: #652b29; }
QPushButton#recordButton:disabled { background: #4c435a; color: #b6a9c4; }
QProgressBar#modelProgress { background: #dde0ea; min-height: 4px; max-height: 4px; }
QProgressBar#modelProgress::chunk { background: #365bd6; }
QFrame#settingsCard { background: #f3f4f7; border: 1px solid #dde0e7; border-radius: 14px; }
QLabel#sectionTitle { font-size: 16px; font-weight: 600; }
QLabel#settingStatus { color: #394464; font-size: 12px; }
QPushButton#danger { color: #a23940; background: #faeaea; }
QPushButton#danger:hover { background: #f5d9db; }
QLabel#workspaceTitle { font-size: 30px; font-weight: 600; color: #19223c; }
QFrame#homeCard { background: white; border: 1px solid #dde0e7; border-radius: 10px; }
QLabel#homeEntry { color: #454c60; padding: 14px 0; border-bottom: 1px solid #e9eaee; }
QCheckBox { spacing: 9px; padding: 6px 0; }
QCheckBox::indicator { width: 17px; height: 17px; }
"""


class InputMeter(QWidget):
    """RMS input level in dBFS, with a short decay between audio callbacks."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(100, 24)
        self.setMaximumHeight(30)
        self.setAccessibleName("Microphone input level")
        self.level = 0.0
        self.timer = QTimer(self)
        self.timer.setInterval(60)
        self.timer.timeout.connect(self.decay)

    def set_level(self, rms):
        db = 20 * math.log10(max(float(rms), 0.00001)) if math.isfinite(rms) else -100
        self.level = max(0, min(1, (db + 60) / 60))
        self.setAccessibleDescription(f"{db:.0f} dBFS")
        self.timer.start()
        self.update()

    def decay(self):
        self.level = max(0, self.level - 0.025)
        if self.level == 0:
            self.timer.stop()
        self.update()

    def reset(self):
        self.timer.stop()
        self.level = 0
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setPen(Qt.PenStyle.NoPen)
        count = 36
        width = self.width() / count
        for i in range(count):
            color = "#4a5165" if self.property("onDark") else "#dadde4"
            if i < round(self.level * count):
                color = "#e6ab69" if i > 29 else "#6679b2"
            painter.setBrush(QColor(color))
            painter.drawRoundedRect(int(i * width), 4, max(2, int(width - 3)), self.height() - 8, 2, 2)


class DictationPanel(QFrame):
    toggle_requested = Signal()
    settings_requested = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("captureCard")
        self.shortcut_hint = "Record here, or dictate into another app."
        self.session_state = "idle"
        box = QVBoxLayout(self)
        box.setContentsMargins(24, 20, 24, 18)
        box.setSpacing(12)
        top = QHBoxLayout()
        self.title = QLabel("Ready when you are")
        self.title.setObjectName("captureTitle")
        top.addWidget(self.title, 1)
        self.model_badge = QLabel("Whistle · Loading")
        self.model_badge.setObjectName("engineBadge")
        top.addWidget(self.model_badge)
        box.addLayout(top)
        self.detail = QLabel(self.shortcut_hint)
        self.detail.setObjectName("captureDetail")
        self.detail.setTextFormat(Qt.TextFormat.PlainText)
        self.detail.setWordWrap(True)
        box.addWidget(self.detail)
        row = QHBoxLayout()
        self.record_button = QPushButton("Start dictation")
        self.record_button.setObjectName("recordButton")
        self.record_button.clicked.connect(self.toggle_requested.emit)
        row.addWidget(self.record_button)
        self.meter = InputMeter()
        self.meter.setProperty("onDark", True)
        row.addWidget(self.meter, 1)
        self.microphone_button = QPushButton("Microphone settings")
        self.microphone_button.setObjectName("textButton")
        self.microphone_button.setStyleSheet("color: #c4d0f5;")
        self.microphone_button.clicked.connect(self.settings_requested.emit)
        row.addWidget(self.microphone_button)
        box.addLayout(row)
        self.model_detail = QLabel("Loading the local model...")
        self.model_detail.setObjectName("captureDetail")
        self.model_detail.setTextFormat(Qt.TextFormat.PlainText)
        self.model_detail.setWordWrap(True)
        box.addWidget(self.model_detail)
        self.progress = QProgressBar()
        self.progress.setObjectName("modelProgress")
        self.progress.setTextVisible(False)
        self.progress.setAccessibleName("Model progress")
        box.addWidget(self.progress)

    def set_session(self, state, message=None):
        self.session_state = state
        self.title.setText({"idle": "Ready when you are", "recording": "Listening to you",
                            "processing": "Putting your words together", "error": "Something needs attention",
                            "meeting": "Notetaker is active"}[state])
        self.record_button.setText("Stop and transcribe" if state == "recording" else "Start dictation")
        self.record_button.setEnabled(state not in ("processing", "meeting"))
        self.record_button.setProperty("recording", state == "recording")
        self.record_button.style().unpolish(self.record_button)
        self.record_button.style().polish(self.record_button)
        detail = message or {"idle": self.shortcut_hint,
                                       "recording": "Speak naturally. Stop recording when you finish.",
                                       "processing": "Your recording is being transcribed locally.",
                                       "meeting": "Finish your meeting before starting a dictation.",
                                       "error": "Check your microphone and model settings, then try again."}[state]
        self.detail.setText(detail[:400])
        self.detail.setToolTip(detail)
        if state != "recording":
            self.meter.reset()

    def set_model_status(self, model, state, detail, percent=-1):
        names = {"idle": "Not loaded", "loading": "Loading", "downloading": "Downloading",
                 "ready": "Ready", "transcribing": "Transcribing", "error": "Needs attention"}
        self.model_badge.setText(f"{model.title()} · {names.get(state, state.title())}")
        self.model_badge.setProperty("state", state)
        self.model_badge.style().unpolish(self.model_badge)
        self.model_badge.style().polish(self.model_badge)
        self.model_detail.setText(detail[:240])
        self.model_detail.setToolTip(detail)
        self.progress.setVisible(state in ("loading", "downloading", "transcribing"))
        self.progress.setRange(0, 0 if percent < 0 else 100)
        self.progress.setValue(max(0, percent))


class DashboardComboBox(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setView(QListView(self))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(10)
        self.currentTextChanged.connect(self.setToolTip)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#706875"), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        x, y = self.width() - 19, self.height() // 2
        painter.drawLine(x - 4, y - 2, x, y + 2)
        painter.drawLine(x, y + 2, x + 4, y - 2)


class NotetakerPanel(QWidget):
    followups_requested = Signal(object)
    start_requested = Signal()
    stop_requested = Signal()
    delete_requested = Signal(object)
    intro_dismissed = Signal()
    settings_requested = Signal()
    record_updated = Signal()
    options_changed = Signal()
    retry_requested = Signal()
    discard_requested = Signal()

    def __init__(self, records, show_intro=True):
        super().__init__()
        self.records = records
        self.state = "idle"
        self._show_intro = show_intro
        self.started_at = 0
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.update_elapsed)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(24)
        header = QHBoxLayout()
        title = QLabel("Meeting notes")
        title.setObjectName("heading")
        header.addWidget(title)
        header.addStretch()
        settings = icon_button("settings", "Transcription settings")
        settings.clicked.connect(self.settings_requested.emit)
        header.addWidget(settings)
        self.start_button = QPushButton("Start Notetaker")
        self.start_button.setObjectName("meetingStart")
        self.start_button.setIcon(icon("notetaker", 17))
        self.start_button.clicked.connect(self.toggle_recording)
        header.addWidget(self.start_button)
        root.addLayout(header)

        overview = QFrame()
        overview.setObjectName("meetingOverview")
        overview_box = QVBoxLayout(overview)
        overview_box.setContentsMargins(20, 16, 20, 24)
        overview_box.setSpacing(12)
        today = QLabel("TODAY")
        today.setStyleSheet("font-size: 12px; letter-spacing: 1px;")
        overview_box.addWidget(today)
        self.intro = QFrame()
        self.intro.setObjectName("meetingIntro")
        intro_box = QHBoxLayout(self.intro)
        intro_box.setContentsMargins(16, 15, 16, 15)
        mark = QLabel()
        mark.setPixmap(icon("dictation", 28, "#93613b").pixmap(28, 28))
        intro_box.addWidget(mark)
        intro_text = QVBoxLayout()
        intro_text.addWidget(QLabel("Meet your new meeting notes"))
        hint = QLabel("Record your mic and computer audio, then keep the transcript.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        intro_text.addWidget(hint)
        intro_box.addLayout(intro_text, 1)
        skip = QPushButton("Skip")
        skip.setObjectName("textButton")
        skip.clicked.connect(self.dismiss_intro)
        intro_box.addWidget(skip)
        learn = QPushButton("How it works")
        learn.setObjectName("primary")
        learn.clicked.connect(self.show_capture_info)
        intro_box.addWidget(learn)
        self.intro.setVisible(show_intro)
        overview_box.addWidget(self.intro)
        self.capture_icon = QLabel()
        self.capture_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.capture_icon.setPixmap(icon("calendar", 25, "#827c73").pixmap(25, 25))
        overview_box.addSpacing(10)
        overview_box.addWidget(self.capture_icon)
        self.capture_title = QLabel("Ready for your next meeting")
        self.capture_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.capture_title.setStyleSheet("font-size: 18px; color: #68635d;")
        overview_box.addWidget(self.capture_title)
        self.status = QLabel("Start Notetaker to capture microphone and computer audio.")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        overview_box.addWidget(self.status)
        recovery = QHBoxLayout()
        self.retry_button = QPushButton("Retry processing")
        self.discard_button = QPushButton("Discard recording")
        self.retry_button.clicked.connect(self.retry_requested.emit)
        self.discard_button.clicked.connect(self.discard_requested.emit)
        recovery.addWidget(self.retry_button)
        recovery.addWidget(self.discard_button)
        recovery.addStretch()
        overview_box.addLayout(recovery)
        self.set_recovery(False)
        options = QHBoxLayout()
        self.speaker_toggle = QCheckBox("Speaker labels")
        self.cleanup_toggle = QCheckBox("Clean audio")
        self.organize_toggle = QCheckBox("Organize notes")
        self.speaker_toggle.setToolTip("Use Who to identify speakers. Overlapping voices can be uncertain.")
        self.cleanup_toggle.setToolTip("Use Clear before transcription. Speech cleanup also reduces music and other sounds.")
        self.organize_toggle.setToolTip("Suggest an editable title and use Gist for topic tags.")
        self.organize_toggle.setChecked(True)
        for toggle in (self.speaker_toggle, self.cleanup_toggle, self.organize_toggle):
            toggle.toggled.connect(lambda _checked: self.options_changed.emit())
            options.addWidget(toggle)
        options.addStretch()
        overview_box.addLayout(options)
        language_row = QHBoxLayout()
        language_row.addWidget(QLabel("Meeting language"))
        self.language_choice = DashboardComboBox()
        self.language_choice.setAccessibleName("Meeting language")
        for code, name in (("en", "English"), ("es", "Spanish"), ("fr", "French"), ("it", "Italian"), ("pt", "Portuguese"), ("de", "German"), ("ja", "Japanese"), ("ko", "Korean"), ("zh", "Chinese")):
            self.language_choice.addItem(name, code)
        self.language_choice.currentIndexChanged.connect(lambda _index: self.options_changed.emit())
        language_row.addWidget(self.language_choice)
        language_row.addStretch()
        overview_box.addLayout(language_row)
        timing_note = QLabel("Word timestamps use Voz + Align. Choose the spoken language for refinement.")
        timing_note.setObjectName("muted")
        timing_note.setWordWrap(True)
        overview_box.addWidget(timing_note)
        root.addWidget(overview)

        tabs = QHBoxLayout()
        tab = QLabel("Past notes")
        tab.setStyleSheet("padding: 10px 0; border-bottom: 2px solid #252323;")
        tabs.addWidget(tab)
        self.count = QLabel()
        self.count.setObjectName("muted")
        tabs.addWidget(self.count)
        tabs.addStretch()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search meeting notes")
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(280)
        self.search.hide()
        self.search.textChanged.connect(self.refresh)
        tabs.addWidget(self.search)
        search_button = icon_button("search", "Search meeting notes")
        search_button.clicked.connect(self.toggle_search)
        tabs.addWidget(search_button)
        root.addLayout(tabs)
        self.feed = QScrollArea()
        self.feed.setWidgetResizable(True)
        self.feed.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        root.addWidget(self.feed, 1)
        self.refresh()

    def dismiss_intro(self):
        self._show_intro = False
        self.intro.hide()
        self.intro_dismissed.emit()

    def resizeEvent(self, event):
        # The optional introduction must not squeeze the recording controls.
        if hasattr(self, "intro"):
            self.intro.setVisible(self._show_intro and self.height() >= 600)
        super().resizeEvent(event)

    def toggle_search(self):
        self.search.setVisible(not self.search.isVisible())
        if self.search.isVisible():
            self.search.setFocus()
        else:
            self.search.clear()

    def show_capture_info(self):
        QMessageBox.information(self, "Meeting capture", "Neyra records your default microphone and speaker output.\n\nMeetings use Voz for transcription and Align for word timestamps. Enable Speaker labels for Who, Clean audio for Clear, or Organize notes for suggested titles and Gist topic tags. These options apply to new recordings.\n\nOpen a saved meeting for its transcript, individual word times, an extractive summary and detected next steps. Model files download on first use; processing stays local.")

    def processing_options(self):
        return {"speakers": self.speaker_toggle.isChecked(), "cleanup": self.cleanup_toggle.isChecked(), "organize": self.organize_toggle.isChecked(), "language": self.language_choice.currentData()}

    def set_recovery(self, available):
        self.retry_button.setVisible(available)
        self.discard_button.setVisible(available)
        self.start_button.setEnabled(not available and self.state != "transcribing")

    def toggle_recording(self):
        if self.state == "recording":
            self.stop_requested.emit()
        elif self.state == "idle":
            self.start_requested.emit()

    def set_state(self, state, message=None):
        self.state = state
        for toggle in (self.speaker_toggle, self.cleanup_toggle, self.organize_toggle):
            toggle.setEnabled(state == "idle")
        self.language_choice.setEnabled(state == "idle")
        self.start_button.setEnabled(state != "transcribing")
        self.start_button.setText({"idle": "Start Notetaker", "recording": "Stop and transcribe", "transcribing": "Transcribing..."}[state])
        if state == "recording":
            self.started_at = time.monotonic()
            self.timer.start()
            self.update_elapsed()
        else:
            self.timer.stop()
            self.capture_title.setText("Preparing your notes" if state == "transcribing" else "Ready for your next meeting")
        if message:
            self.status.setText(message)

    def update_elapsed(self):
        seconds = int(time.monotonic() - self.started_at)
        self.capture_title.setText(f"Recording meeting  {seconds // 60:02d}:{seconds % 60:02d}")

    def refresh(self, *_):
        query = self.search.text().casefold().strip()
        content = QWidget()
        box = QVBoxLayout(content)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(10)
        matches = [record for record in reversed(self.records) if query in " ".join((record["text"], record.get("title", ""), " ".join(topic["name"] for topic in record.get("topics", [])))).casefold()]
        self.count.setText(f"{len(self.records)} saved" if self.records else "")
        for record in matches:
            card = QFrame()
            card.setObjectName("meetingCard")
            row = QHBoxLayout(card)
            row.setContentsMargins(18, 16, 16, 16)
            mark = QLabel()
            mark.setPixmap(icon("dictionary", 22, "#827c73").pixmap(22, 22))
            row.addWidget(mark)
            text = QVBoxLayout()
            stamp = datetime.fromisoformat(record["time"])
            title = QLabel(record.get("title") or stamp.strftime("Meeting · %B %d, %I:%M %p").replace(" 0", " "))
            title.setTextFormat(Qt.TextFormat.PlainText)
            title.setWordWrap(True)
            text.addWidget(title)
            if record.get("title"):
                date = QLabel(stamp.strftime("%B %d, %I:%M %p"))
                date.setObjectName("muted")
                text.addWidget(date)
            if record.get("topics"):
                tags = QLabel(" · ".join(topic["name"] for topic in record["topics"]))
                tags.setObjectName("muted")
                tags.setTextFormat(Qt.TextFormat.PlainText)
                tags.setWordWrap(True)
                text.addWidget(tags)
            summary, _ = meeting_brief(record["text"])
            preview = QLabel(summary[:155] + ("..." if len(summary) > 155 else ""))
            preview.setObjectName("muted")
            preview.setTextFormat(Qt.TextFormat.PlainText)
            preview.setWordWrap(True)
            text.addWidget(preview)
            row.addLayout(text, 1)
            open_button = QPushButton("Open notes")
            open_button.clicked.connect(lambda checked=False, value=record: self.open_meeting(value))
            row.addWidget(open_button)
            more = icon_button("more", "Meeting options")
            menu = QMenu(more)
            menu.addAction("Copy transcript", lambda value=record: QApplication.clipboard().setText(meeting_transcript(value)))
            menu.addAction("Copy plain text", lambda value=record["text"]: QApplication.clipboard().setText(value))
            menu.addAction("Delete meeting", lambda value=record: self.delete_requested.emit(value))
            more.setMenu(menu)
            row.addWidget(more)
            box.addWidget(card)
        if not matches:
            empty = QFrame()
            empty.setObjectName("meetingEmpty")
            row = QHBoxLayout(empty)
            row.setContentsMargins(18, 18, 18, 18)
            mark = QLabel()
            mark.setPixmap(icon("dictionary", 22, "#827c73").pixmap(22, 22))
            row.addWidget(mark)
            text = QLabel("No matching meetings" if query else "Your meetings will appear here")
            text.setStyleSheet("color: #6c665f;")
            row.addWidget(text, 1)
            box.addWidget(empty)
        box.addStretch()
        old = self.feed.takeWidget()
        self.feed.setWidget(content)
        if old:
            old.deleteLater()

    def open_meeting(self, record):
        dialog = QDialog(self)
        dialog.setWindowTitle("Meeting notes")
        dialog.resize(760, 560)
        dialog.setStyleSheet(THEME)
        box = QVBoxLayout(dialog)
        box.setContentsMargins(24, 24, 24, 24)
        title = QLineEdit(record.get("title") or "Meeting notes")
        title.setMaxLength(160)
        title.setAccessibleName("Meeting title")
        box.addWidget(title)
        topics = QLabel(" · ".join(topic["name"] for topic in record.get("topics", [])))
        topics.setTextFormat(Qt.TextFormat.PlainText)
        topics.setWordWrap(True)
        topics.setObjectName("muted")
        topics.setVisible(bool(record.get("topics")))
        box.addWidget(topics)
        if record.get("warnings"):
            warning = QLabel("\n".join(record["warnings"]))
            warning.setTextFormat(Qt.TextFormat.PlainText)
            warning.setWordWrap(True)
            box.addWidget(warning)
        tabs = QTabWidget()
        summary, actions = meeting_brief(record["text"])
        for name, value in (("Summary", summary), ("Next steps", "\n\n".join(actions) or "No follow-up phrases detected."), ("Transcript", meeting_transcript(record))):
            editor = QTextEdit()
            editor.setReadOnly(True)
            editor.setPlainText(value)
            tabs.addTab(editor, name)
        if record.get("words"):
            table = QTableWidget(len(record["words"]), 4)
            table.setHorizontalHeaderLabels(["Word", "Start", "End", "Speaker"])
            table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            for row, word in enumerate(record["words"]):
                for col, value in enumerate((word["text"], timestamp(word["start"]), timestamp(word["end"]), speaker_label(word) if record.get("speaker_labels") else "")):
                    cell = QTableWidgetItem(value)
                    if col in (1, 2):
                        cell.setToolTip("Refined by Align" if word.get("refined") else "Original Voz boundary kept")
                    table.setItem(row, col, cell)
            tabs.addTab(table, "Word timestamps")
        box.addWidget(tabs, 1)
        buttons = QHBoxLayout()
        save = QPushButton("Save title")
        def save_title():
            record["title"] = title.text().strip() or "Meeting notes"
            self.record_updated.emit()
            self.refresh()
        save.clicked.connect(save_title)
        buttons.addWidget(save)
        followups = QPushButton("Plan follow-ups with Luna")
        def open_followups():
            dialog.accept()
            self.followups_requested.emit(record)
        followups.clicked.connect(open_followups)
        buttons.addWidget(followups)
        buttons.addStretch()
        copy = QPushButton("Copy transcript")
        copy.clicked.connect(lambda: QApplication.clipboard().setText(meeting_transcript(record)))
        buttons.addWidget(copy)
        box.addLayout(buttons)
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()


class TranscriptFeed(QScrollArea):
    delete_requested = Signal(object)

    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.records = []
        self.query = ""
        self.show_first_date = True

    def refresh(self, records=None, query=None):
        if records is not None:
            self.records = records
        if query is not None:
            self.query = query.casefold().strip()
        scroll = self.verticalScrollBar().value()
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        previous_day = None
        found = 0
        for record in reversed(self.records):
            if self.query and self.query not in record["text"].casefold():
                continue
            found += 1
            stamp = datetime.fromisoformat(record["time"])
            if stamp.date() != previous_day:
                if previous_day is not None or self.show_first_date or self.query:
                    date = QLabel(stamp.strftime("%B %d, %Y").upper())
                    date.setObjectName("dateLabel")
                    layout.addWidget(date)
                previous_day = stamp.date()
            row = QFrame()
            row.setObjectName("transcriptRow")
            cells = QHBoxLayout(row)
            cells.setContentsMargins(16, 18, 8, 18)
            cells.setSpacing(15)
            time_label = QLabel(stamp.strftime("%I:%M%p").lstrip("0").lower())
            time_label.setObjectName("muted")
            time_label.setFixedWidth(76)
            cells.addWidget(time_label, 0, Qt.AlignmentFlag.AlignVCenter)
            text = QLabel(record["text"])
            text.setTextFormat(Qt.TextFormat.PlainText)
            text.setWordWrap(True)
            text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            text.setStyleSheet("font-size: 15px; line-height: 1.4;")
            cells.addWidget(text, 1)
            copy = icon_button("copy", "Copy transcript")
            copy.clicked.connect(lambda checked=False, value=record["text"]: QApplication.clipboard().setText(value))
            cells.addWidget(copy)
            more = icon_button("more", "Transcript options")
            menu = QMenu(more)
            menu.addAction("Copy text", lambda value=record["text"]: QApplication.clipboard().setText(value))
            menu.addAction("Delete transcript", lambda value=record: self.delete_requested.emit(value))
            more.setMenu(menu)
            cells.addWidget(more)
            layout.addWidget(row)
        if not found:
            empty = QWidget()
            box = QVBoxLayout(empty)
            box.setContentsMargins(30, 70, 30, 60)
            box.setSpacing(15)
            mic = QLabel()
            mic.setPixmap(icon("dictation", 46, "#365bd6").pixmap(46, 46))
            box.addWidget(mic, 0, Qt.AlignmentFlag.AlignHCenter)
            title = QLabel("No matching transcriptions" if self.query else "Your voice, put into words")
            title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            title.setStyleSheet("font-size: 21px; font-weight: 600;")
            box.addWidget(title)
            hint = QLabel("Try a different search." if self.query else "Start a recording from Home, or use Dictate to speak into another app.")
            hint.setObjectName("muted")
            hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
            hint.setWordWrap(True)
            box.addWidget(hint)
            layout.addWidget(empty)
        layout.addStretch()
        old = self.takeWidget()
        self.setWidget(content)
        if old:
            old.deleteLater()
        self.verticalScrollBar().setValue(scroll)
