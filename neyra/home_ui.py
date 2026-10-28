"""The personal workspace overview. Recording and navigation stay with the owner."""
from datetime import datetime
import textwrap
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QScrollArea, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton


class HomePanel(QScrollArea):
    navigate = Signal(int)
    remind = Signal()
    meeting = Signal()
    ask_notes = Signal()
    companion = Signal()

    def __init__(self, capture):
        super().__init__()
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        self.setWidget(content)
        box = QVBoxLayout(content)
        box.setContentsMargins(0, 0, 8, 0)
        box.setSpacing(18)
        intro = QLabel("Capture a thought. Remember what matters.")
        intro.setObjectName("workspaceTitle")
        intro.setWordWrap(True)
        box.addWidget(intro)
        box.addWidget(capture)
        actions = QHBoxLayout()
        for title, signal in (("Speak a reminder", self.remind), ("Ask my notes", self.ask_notes),
                              ("Start a meeting", self.meeting), ("Android companion", self.companion)):
            button = QPushButton(title)
            button.clicked.connect(signal.emit)
            actions.addWidget(button)
        box.addLayout(actions)
        columns = QHBoxLayout()
        columns.setSpacing(18)
        self.note_labels = []
        self.reminder_labels = []
        for title, destination, labels in (("Recent notes", 0, self.note_labels),
                                           ("Coming up", 7, self.reminder_labels)):
            card = QFrame()
            card.setObjectName("homeCard")
            layout = QVBoxLayout(card)
            layout.setContentsMargins(20, 18, 20, 18)
            header = QHBoxLayout()
            heading = QLabel(title)
            heading.setObjectName("sectionTitle")
            header.addWidget(heading, 1)
            button = QPushButton("View all")
            button.setObjectName("textButton")
            button.setAccessibleName(f"View all {title.lower()}")
            button.clicked.connect(lambda _=False, page=destination: self.navigate.emit(page))
            header.addWidget(button)
            layout.addLayout(header)
            for _ in range(3):
                label = QLabel()
                label.setTextFormat(Qt.TextFormat.PlainText)
                label.setWordWrap(True)
                label.setObjectName("homeEntry")
                layout.addWidget(label)
                labels.append(label)
            layout.addStretch()
            columns.addWidget(card, 1)
        box.addLayout(columns)
        local = QLabel("Your voice stays on this PC. You choose what to share with ChatGPT.")
        local.setObjectName("muted")
        local.setWordWrap(True)
        box.addWidget(local)
        box.addStretch()

    def refresh(self, records, meetings, reminders):
        recent = sorted(records + meetings, key=lambda r: r["time"], reverse=True)[:3]
        upcoming = sorted((r for r in reminders if r["status"] == "pending"),
                          key=lambda r: r["due_at"])[:3]
        for labels, entries, empty, reminder in (
            (self.note_labels, recent, "A thought worth keeping? Capture your first note.", False),
            (self.reminder_labels, upcoming, 'Try saying "remind me in an hour to stretch".', True),
        ):
            for index, label in enumerate(labels):
                label.setVisible(index < len(entries) or index == 0)
                if index >= len(entries):
                    label.setText(empty if index == 0 else "")
                    label.setToolTip("")
                    continue
                entry = entries[index]
                when = (datetime.fromtimestamp(entry["due_at"]) if reminder
                        else datetime.fromisoformat(entry["time"]))
                title = entry.get("title") or entry["text"]
                label.setText(when.strftime("%d %b · %H:%M") + "\n" + textwrap.shorten(title, 100, placeholder="…"))
                label.setToolTip(title[:1000])
