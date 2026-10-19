"""Dashboard icons, theme and the dated transcript feed."""
from datetime import datetime
from PySide6.QtCore import Qt, QSize, QByteArray, Signal
from PySide6.QtGui import QIcon, QPixmap, QPainter, QPen, QColor
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QApplication, QWidget, QScrollArea, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QMenu, QComboBox, QListView,
)

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
