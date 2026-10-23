"""Reminder command entry, saved reminders and a notification fallback."""
from datetime import datetime
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)
from .ui import THEME, icon


def due_label(timestamp):
    return datetime.fromtimestamp(timestamp).strftime("%a, %d %b %Y at %H:%M")


class RemindersPanel(QWidget):
    speak_requested = Signal()
    command_submitted = Signal(str)
    remove_requested = Signal(str)

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        card = QFrame()
        card.setObjectName("settingsCard")
        box = QVBoxLayout(card)
        box.setContentsMargins(22, 18, 22, 18)
        box.setSpacing(12)
        header = QHBoxLayout()
        title = QLabel("A reminder, in your own words")
        title.setObjectName("sectionTitle")
        header.addWidget(title, 1)
        self.speak_button = QPushButton("Speak a reminder")
        self.speak_button.setObjectName("primary")
        self.speak_button.setIcon(icon("reminders", color="#ffffff"))
        self.speak_button.clicked.connect(self.speak_requested.emit)
        header.addWidget(self.speak_button)
        box.addLayout(header)
        hint = QLabel('Hold Ctrl + Alt + Space and say "remind me in an hour to take out the garbage". Release to save it.')
        hint.setWordWrap(True)
        box.addWidget(hint)
        command_row = QHBoxLayout()
        self.command = QLineEdit()
        self.command.setPlaceholderText("Remind me in twenty-five minutes to check the oven")
        self.command.setAccessibleName("Reminder command")
        self.command.setClearButtonEnabled(True)
        self.command.setMaxLength(2500)
        self.add_button = QPushButton("Add reminder")
        self.add_button.clicked.connect(self.submit)
        self.command.returnPressed.connect(self.submit)
        command_row.addWidget(self.command, 1)
        command_row.addWidget(self.add_button)
        box.addLayout(command_row)
        self.status = QLabel("You can also type a command above. Each reminder stays on this computer.")
        self.status.setObjectName("settingStatus")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        box.addWidget(self.status)
        note = QLabel("Keep Neyra running in the tray for on-time notifications. If it was closed, overdue reminders appear when you reopen it.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        box.addWidget(note)
        layout.addWidget(card)
        self.count = QLabel("No upcoming reminders")
        self.count.setObjectName("sectionTitle")
        layout.addWidget(self.count)
        self.feed = QScrollArea()
        self.feed.setWidgetResizable(True)
        self.feed.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self.feed, 1)
        self.refresh([])

    def submit(self):
        self.command_submitted.emit(self.command.text())

    def set_capture_state(self, recording, busy):
        self.speak_button.setText("Stop and set reminder" if recording else "Speak a reminder")
        self.speak_button.setEnabled(recording or not busy)
        self.command.setEnabled(not busy)
        self.add_button.setEnabled(not busy)

    def refresh(self, records):
        pending = sorted((r for r in records if r["status"] == "pending"), key=lambda r: r["due_at"])
        fired = sorted((r for r in records if r["status"] == "fired"), key=lambda r: r["due_at"], reverse=True)
        self.count.setText(f"{len(pending)} upcoming reminder{'s' if len(pending) != 1 else ''}")
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        if not records:
            empty = QLabel("Your reminders will appear here, with their scheduled times.")
            empty.setObjectName("muted")
            empty.setWordWrap(True)
            layout.addWidget(empty)
        for title, group in (("Upcoming", pending), ("Recent reminders", fired)):
            if not group:
                continue
            section = QLabel(title)
            section.setObjectName("muted")
            layout.addWidget(section)
            for record in group:
                row = QFrame()
                row.setObjectName("settingsCard")
                cells = QHBoxLayout(row)
                cells.setContentsMargins(18, 14, 14, 14)
                text = QVBoxLayout()
                task = QLabel(record["text"])
                task.setTextFormat(Qt.TextFormat.PlainText)
                task.setWordWrap(True)
                task.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                text.addWidget(task)
                when = QLabel(("Due " if record["status"] == "fired" else "Scheduled for ") + due_label(record["due_at"]))
                when.setObjectName("muted")
                text.addWidget(when)
                cells.addLayout(text, 1)
                remove = QPushButton("Cancel" if record["status"] == "pending" else "Dismiss")
                remove.setAccessibleName(f"{remove.text()} reminder: {record['text']}")
                remove.setAutoDefault(False)
                remove.clicked.connect(lambda _checked=False, identity=record["id"]: self.remove_requested.emit(identity))
                cells.addWidget(remove)
                layout.addWidget(row)
        layout.addStretch()
        scroll = self.feed.verticalScrollBar().value()
        old = self.feed.takeWidget()
        self.feed.setWidget(content)
        if old:
            old.deleteLater()
        self.feed.verticalScrollBar().setValue(scroll)


class ReminderAlert(QDialog):
    """A nonblocking alert when the desktop has no notification backend."""
    def __init__(self, title, message):
        super().__init__()
        self.setWindowTitle(title)
        self.setWindowIcon(icon("reminders"))
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setStyleSheet(THEME)
        self.setMinimumWidth(360)
        self.setMaximumWidth(560)
        box = QVBoxLayout(self)
        box.setContentsMargins(24, 24, 24, 24)
        heading = QLabel(title)
        heading.setObjectName("sectionTitle")
        box.addWidget(heading)
        text = QLabel(message)
        text.setTextFormat(Qt.TextFormat.PlainText)
        text.setWordWrap(True)
        text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        box.addWidget(text)
        dismiss = QPushButton("Dismiss")
        dismiss.clicked.connect(self.accept)
        box.addWidget(dismiss)
