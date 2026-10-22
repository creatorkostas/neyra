"""Dashboard icons, theme and the dated transcript feed."""
from datetime import datetime
import time
from PySide6.QtCore import Qt, QSize, QByteArray, Signal, QTimer
from PySide6.QtGui import QIcon, QPixmap, QPainter, QPen, QColor
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QApplication, QWidget, QScrollArea, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QMenu, QComboBox, QListView, QLineEdit,
    QDialog, QMessageBox, QTextEdit, QTabWidget, QCheckBox, QTableWidget,
    QTableWidgetItem, QAbstractItemView, QHeaderView,
)
from .text_tools import meeting_brief
from .meeting import meeting_transcript, timestamp, speaker_label

PATHS = {
    "dictation": '<rect x="9" y="2" width="6" height="13" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3M9 22h6"/>',
    "notetaker": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="4"/>',
    "insights": '<path d="M4 3v18h17M8 16v-5M13 16V6M18 16v-8"/>',
    "dictionary": '<path d="M6 3h9l4 4v14H6zM15 3v5h4M10 12v5h4v-5z"/>',
    "snippets": '<circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="m8 8 13 13M8 16 21 3"/>',
    "style": '<path d="M3 5h12M9 5v16M16 11h6M19 11v10"/>',
    "settings": '<path d="m9 3-1 3-3 1v4l2 1-2 2 2 4h3l2 3 3-2 3 1 3-4-2-2 1-3-3-2V5l-4-2-2 2z"/><circle cx="12" cy="12" r="3"/>',
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
}


def icon(name, size=20, color="#302c34"):
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24"><g fill="none" stroke="{color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">{PATHS[name]}</g></svg>'
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    QSvgRenderer(QByteArray(svg.encode())).render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(2)
    return QIcon(pixmap)


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
QDialog { background: #f6f5f2; color: #191819; font-family: 'Segoe UI'; font-size: 14px; }
QDialog#dashboard { background: transparent; }
QWidget { color: #191819; font-family: 'Segoe UI'; font-size: 14px; }
QLabel { background: transparent; border: none; }
QFrame#surface { background: #fdfdfc; border: 1px solid #eae7e1; border-radius: 24px; }
QFrame#sidebar, QWidget#windowBar { background: transparent; border: none; }
QLabel#heading { font-size: 25px; font-weight: 600; }
QLabel#brand { font-size: 25px; font-weight: 700; color: #302c34; }
QLabel#muted { color: #79736c; font-size: 12px; }
QLabel#dateLabel { color: #777168; font-size: 12px; letter-spacing: 1px; padding: 14px 0; }
QPushButton { color: #191819; background: #eeece6; border: 0; border-radius: 8px; padding: 9px 14px; }
QPushButton:hover { background: #e6e3dc; }
QPushButton:disabled { color: #979087; background: #f0eee9; }
QPushButton#nav { background: transparent; text-align: left; padding: 8px 10px; }
QPushButton#nav:checked, QPushButton#nav:hover { background: #eeece5; }
QPushButton#primary { background: #1e1d1c; color: white; }
QPushButton#primary:hover { background: #3c3835; }
QPushButton#iconButton { background: transparent; padding: 4px; border-radius: 5px; }
QPushButton#iconButton:hover { background: #ebe8e2; }
QPushButton::menu-indicator { image: none; width: 0; }
QFrame#summaryCard, QFrame#promoCard { background: #f6f5f1; border: 1px solid #ece8e0; border-radius: 17px; }
QFrame#promoCard { background: #fffdf9; border-radius: 12px; }
QFrame#transcriptRow { background: transparent; border: none; border-bottom: 1px solid #ece9e2; }
QFrame#transcriptRow:hover { background: #f6f4ef; }
QFrame#divider { background: #e9e6df; border: none; }
QFrame#meetingOverview, QFrame#meetingCard, QFrame#meetingEmpty { background: #f6f5f1; border: none; border-radius: 16px; }
QFrame#meetingIntro { background: #fff8ef; border: 1px solid #f3bf87; border-radius: 12px; }
QPushButton#meetingStart { background: #ffecd4; color: #211c17; padding: 9px 14px; }
QPushButton#meetingStart:hover { background: #ffe0b8; }
QPushButton#meetingStart:disabled { background: #ede9e2; color: #888078; }
QPushButton#textButton { background: transparent; padding: 7px; }
QTabWidget::pane { border: 1px solid #e5e0d7; border-radius: 8px; background: white; }
QTabBar::tab { background: transparent; padding: 10px 16px; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { border-bottom-color: #8037af; }
QScrollArea, QScrollArea > QWidget > QWidget, QStackedWidget { background: transparent; border: none; }
QScrollBar:vertical { width: 7px; background: transparent; margin: 2px; }
QScrollBar::handle:vertical { background: #d8d3cb; border-radius: 3px; min-height: 35px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QLineEdit, QTextEdit, QComboBox { background: white; color: #191819; border: 1px solid #ded9cf; border-radius: 8px; padding: 10px; selection-background-color: #e7dcef; selection-color: #191819; }
QComboBox { padding-right: 38px; min-height: 22px; }
QComboBox:hover { border-color: #b9b1a6; }
QComboBox:focus, QComboBox:on { border-color: #9a78b2; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: top right; width: 34px; border: none; background: transparent; }
QComboBox::down-arrow { image: none; width: 0; height: 0; border: none; }
QComboBox QAbstractItemView { background: white; color: #191819; border: 1px solid #ded9cf; border-radius: 8px; padding: 5px; outline: 0; selection-background-color: #eee7f3; selection-color: #191819; }
QComboBox QAbstractItemView::item { min-height: 30px; padding: 3px 8px; border: none; border-radius: 4px; }
QListWidget, QTableWidget { background: #fdfdfc; color: #191819; border: 1px solid #eae6de; border-radius: 9px; outline: 0; }
QListWidget::item { padding: 14px; border-bottom: 1px solid #eeeae3; }
QListWidget::item:selected { background: #f0ece4; color: #191819; }
QHeaderView::section { color: #686057; background: #f3f0e9; border: 0; padding: 10px; }
QProgressBar { background: #dfdcd5; border: 0; border-radius: 3px; max-height: 6px; min-height: 6px; }
QProgressBar::chunk { background: #8037af; border-radius: 3px; }
QMenu { background: white; color: #191819; border: 1px solid #e5e0d7; padding: 5px; }
QMenu::item { padding: 7px 18px; }
QMenu::item:selected { background: #eeeae2; }
"""


class DashboardComboBox(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setView(QListView(self))
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#706875"), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        x, y = self.width() - 19, self.height() // 2
        painter.drawLine(x - 4, y - 2, x, y + 2)
        painter.drawLine(x, y + 2, x + 4, y - 2)


class NotetakerPanel(QWidget):
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
        title = QLabel("Notetaker")
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
            mic.setPixmap(icon("dictation", 46, "#8037af").pixmap(46, 46))
            box.addWidget(mic, 0, Qt.AlignmentFlag.AlignHCenter)
            title = QLabel("No matching transcriptions" if self.query else "Your voice, put into words")
            title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            title.setStyleSheet("font-size: 21px; font-weight: 600;")
            box.addWidget(title)
            hint = QLabel("Try a different search." if self.query else "Hold Ctrl + Win and start speaking.\nRelease the keys to paste your words into the focused app.")
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
