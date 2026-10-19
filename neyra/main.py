import sys
import math
import queue
import json
import numpy as np
from datetime import datetime
from PySide6.QtCore import Qt, QTimer, QPoint, Signal, QSize, QSettings
from PySide6.QtGui import QColor, QPainter, QPen, QAction
from PySide6.QtWidgets import QApplication, QWidget, QSystemTrayIcon, QMenu, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QFrame, QStackedWidget, QLineEdit, QTextEdit, QComboBox, QTableWidget, QTableWidgetItem
from .audio import Microphone
from .stt import Transcriber
from .desktop import insert_text, is_wayland
from .text_tools import apply_style, expand_snippets, meeting_brief
from .system_audio import SystemAudioRecorder

class Overlay(QWidget):
    start_requested = Signal()
    stop_requested = Signal()
    toggle_requested = Signal()

    def __init__(self):
        super().__init__()
        self.setFixedSize(410, 128)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.move(90, 90)
        self.drag_offset = QPoint()
        self.level = 0.0
        self.phase = 0.0
        self.state = "Ready"
        self.text = "Hold Ctrl+Win to dictate"
        self.tick = QTimer(self)
        self.tick.timeout.connect(self.animate)
        self.tick.start(33)

    def animate(self):
        self.phase += 0.14
        self.level *= 0.89
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(32, 24, 49, 245))
        p.drawRoundedRect(self.rect().adjusted(4, 4, -4, -4), 20, 20)
        p.setPen(QColor("#c9b8ec"))
        p.drawText(20, 26, f"NEYRA   •   {self.state}")
        for i in range(72):
            x = 20 + i * 5.15
            amp = min(1.0, self.level * 9.0)
            h = 4 + amp * (8 + abs(math.sin(i * 0.46 + self.phase) * math.cos(i * .16)) * 28)
            p.setPen(QPen(QColor("#8be0c8" if i < 25 else "#b68aff"), 2.6))
            p.drawLine(int(x), int(66-h/2), int(x), int(66+h/2))
        p.setPen(QColor("#d5c4f3"))
        fm = p.fontMetrics()
        p.drawText(20, 105, fm.elidedText(self.text, Qt.TextElideMode.ElideLeft, 370))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_offset = event.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_offset)

class HistoryDashboard(QDialog):
    notetaker_start = Signal()
    notetaker_stop = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Neyra - Dictation")
        self.resize(1120, 700)
        self.settings = QSettings("Neyra", "Neyra")
        try:
            self.records = json.loads(self.settings.value("history", "[]"))
        except (TypeError, ValueError):
            self.records = []
        self.setStyleSheet("""
            QDialog { background: #f5f4f1; color: #191817; }
            QLabel { color: #191817; }
            QListWidget, QTableWidget { color: #191817; background: #ffffff; border: 0; outline: 0; }
            QListWidget::item { padding: 14px 12px; border-bottom: 1px solid #e9e7e2; }
            QListWidget::item:selected { background: #f4f2ed; color: #191817; }
            QPushButton { color: #191817; text-align: left; background: #eeece6; border: 0; border-radius: 8px; padding: 9px 12px; }
            QPushButton:hover { background: #e5e2da; }
            QLineEdit, QComboBox, QTextEdit, QPlainTextEdit { color: #191817; background: white; selection-color: #191817; selection-background-color: #dedbd3; border: 1px solid #e5e2da; border-radius: 7px; padding: 8px; }
            QComboBox QAbstractItemView { color: #191817; background: white; selection-color: #191817; selection-background-color: #dedbd3; }
        """)
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        sidebar = QFrame()
        sidebar.setFixedWidth(190)
        sidebar.setStyleSheet("QFrame { background: #f1f0ec; }")
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(16, 22, 16, 18)
        side.setSpacing(8)
        brand = QLabel("Neyra")
        brand.setStyleSheet("font-size: 22px; font-weight: 700; margin-bottom: 18px;")
        side.addWidget(brand)
        self.nav_buttons = []
        for index, name in enumerate(("Dictation", "Notetaker", "Insights", "Dictionary", "Snippets", "Style")):
            button = QPushButton(name)
            button.setCheckable(True)
            button.setStyleSheet("QPushButton { color: #191817; text-align: left; background: transparent; } QPushButton:checked { background: #e8e6df; font-weight: 600; }")
            button.clicked.connect(lambda checked=False, page=index: self.show_page(page))
            side.addWidget(button)
            self.nav_buttons.append(button)
        self.nav_buttons[0].setChecked(True)
        side.addStretch()
        side.addWidget(QLabel("Settings"))
        root.addWidget(sidebar)

        content = QWidget()
        content.setStyleSheet("QWidget { background: #ffffff; }")
        body = QVBoxLayout(content)
        body.setContentsMargins(30, 28, 24, 24)
        self.heading = QLabel("Your dictation")
        self.heading.setStyleSheet("font-size: 24px; font-weight: 600;")
        body.addWidget(self.heading)
        self.pages = QStackedWidget()
        body.addWidget(self.pages, 1)
        root.addWidget(content, 1)

        # Dictation history
        dictation = QWidget()
        columns = QHBoxLayout(dictation)
        columns.setContentsMargins(0, 16, 0, 0)
        feed = QVBoxLayout()
        feed.addWidget(QLabel("RECENT TRANSCRIPTIONS"))
        self.items = QListWidget()
        self.items.setWordWrap(True)
        self.items.itemDoubleClicked.connect(self.copy_selected)
        feed.addWidget(self.items, 1)
        copy_button = QPushButton("Copy selected transcript")
        copy_button.clicked.connect(self.copy_selected)
        feed.addWidget(copy_button, 0, Qt.AlignmentFlag.AlignRight)
        columns.addLayout(feed, 1)
        summary = QFrame()
        summary.setFixedWidth(215)
        summary.setStyleSheet("QFrame { background: #f5f4f1; border: 1px solid #ebe9e4; border-radius: 14px; }")
        stats = QVBoxLayout(summary)
        stats.setContentsMargins(20, 22, 20, 18)
        stats.setSpacing(17)
        stats.addWidget(QLabel("SESSION SUMMARY"))
        self.words_stat = QLabel("0 total words")
        self.count_stat = QLabel("0 dictations")
        self.latest_stat = QLabel("No dictations yet")
        for stat in (self.words_stat, self.count_stat, self.latest_stat):
            stat.setStyleSheet("font-size: 17px;")
            stats.addWidget(stat)
        stats.addWidget(QLabel("Language: English"))
        stats.addStretch()
        columns.addWidget(summary, 0, Qt.AlignmentFlag.AlignTop)
        self.pages.addWidget(dictation)

        # Meeting notes
        notetaker = QWidget()
        note_layout = QVBoxLayout(notetaker)
        note_layout.addWidget(QLabel("Capture a meeting and keep its transcript with your dictations."))
        note_layout.addWidget(QLabel("Audio is mixed from the microphone and default speaker output; individual speakers are not identified."))
        self.notetaker_status = QLabel("Ready to record microphone and computer audio.")
        note_layout.addWidget(self.notetaker_status)
        controls = QHBoxLayout()
        start_note = QPushButton("Start meeting recording")
        stop_note = QPushButton("Stop and transcribe")
        start_note.clicked.connect(self.notetaker_start.emit)
        stop_note.clicked.connect(self.notetaker_stop.emit)
        controls.addWidget(start_note)
        controls.addWidget(stop_note)
        controls.addStretch()
        note_layout.addLayout(controls)
        self.notes_text = QListWidget()
        self.meeting_records = json.loads(self.settings.value("meetings", "[]"))
        for record in reversed(self.meeting_records):
            self._add_meeting_row(record)
        note_layout.addWidget(self.notes_text, 1)
        self.pages.addWidget(notetaker)

        # Usage insights
        insights = QWidget()
        insights_layout = QVBoxLayout(insights)
        self.insights_words = QLabel()
        self.insights_count = QLabel()
        self.insights_streak = QLabel()
        for label in (self.insights_words, self.insights_count, self.insights_streak):
            label.setStyleSheet("font-size: 22px; padding: 14px;")
            insights_layout.addWidget(label)
        insights_layout.addStretch()
        self.pages.addWidget(insights)

        # Personal dictionary
        dictionary = QWidget()
        dictionary_layout = QVBoxLayout(dictionary)
        dictionary_layout.addWidget(QLabel("Names and technical terms are sent as recognition hints."))
        word_row = QHBoxLayout()
        self.dictionary_input = QLineEdit()
        self.dictionary_input.setPlaceholderText("Word or phrase")
        add_word = QPushButton("Add word")
        add_word.clicked.connect(self.add_dictionary_word)
        self.dictionary_input.returnPressed.connect(self.add_dictionary_word)
        word_row.addWidget(self.dictionary_input, 1)
        word_row.addWidget(add_word)
        dictionary_layout.addLayout(word_row)
        self.dictionary_items = QListWidget()
        self.dictionary_items.addItems(self.dictionary_words())
        dictionary_layout.addWidget(self.dictionary_items, 1)
        remove_word = QPushButton("Remove selected")
        remove_word.clicked.connect(self.remove_dictionary_word)
        dictionary_layout.addWidget(remove_word, 0, Qt.AlignmentFlag.AlignRight)
        self.pages.addWidget(dictionary)

        # Spoken snippets
        snippets_page = QWidget()
        snippets_layout = QVBoxLayout(snippets_page)
        snippets_layout.addWidget(QLabel("Say a trigger phrase and Neyra expands it after transcription."))
        self.snippets_table = QTableWidget(0, 2)
        self.snippets_table.setHorizontalHeaderLabels(["Spoken trigger", "Expanded text"])
        self.snippets_table.horizontalHeader().setStretchLastSection(True)
        snippets_layout.addWidget(self.snippets_table, 1)
        snippet_row = QHBoxLayout()
        self.snippet_trigger = QLineEdit()
        self.snippet_trigger.setPlaceholderText("Trigger phrase")
        self.snippet_text = QLineEdit()
        self.snippet_text.setPlaceholderText("Text to insert")
        add_snippet = QPushButton("Add snippet")
        add_snippet.clicked.connect(self.add_snippet)
        snippet_row.addWidget(self.snippet_trigger)
        snippet_row.addWidget(self.snippet_text, 1)
        snippet_row.addWidget(add_snippet)
        snippets_layout.addLayout(snippet_row)
        remove_snippet = QPushButton("Remove selected")
        remove_snippet.clicked.connect(self.remove_snippet)
        snippets_layout.addWidget(remove_snippet, 0, Qt.AlignmentFlag.AlignRight)
        self.refresh_snippets()
        self.pages.addWidget(snippets_page)

        # Output style
        style = QWidget()
        style_layout = QVBoxLayout(style)
        style_layout.addWidget(QLabel("Choose how dictated text is formatted."))
        self.style_choice = QComboBox()
        self.style_choice.addItems(["Natural", "Clean up speech", "Formal"])
        self.style_choice.setCurrentText(self.settings.value("style", "Clean up speech"))
        self.style_choice.currentTextChanged.connect(lambda value: self.settings.setValue("style", value))
        style_layout.addWidget(self.style_choice)
        style_layout.addWidget(QLabel("Cleanup is local and rule-based. No cloud rewrite is used."))
        style_layout.addStretch()
        self.pages.addWidget(style)

        for record in self.records:
            self._add_record_row(record)
        self.update_stats()

    def show_page(self, index):
        self.pages.setCurrentIndex(index)
        self.heading.setText(("Your dictation", "Notetaker", "Insights", "Dictionary", "Snippets", "Style")[index])
        for i, button in enumerate(self.nav_buttons):
            button.setChecked(i == index)

    def _add_record_row(self, record):
        stamp = datetime.fromisoformat(record["time"]).strftime("%I:%M %p").lstrip("0")
        text = record["text"]
        item = QListWidgetItem(f"{stamp}\n{text}")
        item.setToolTip(text)
        item.setData(Qt.ItemDataRole.UserRole, text)
        item.setSizeHint(QSize(0, max(58, 42 + (len(text) // 75) * 20)))
        self.items.insertItem(0, item)
        self.latest_stat.setText(f"{stamp} latest")

    def add_transcript(self, text):
        record = {"text": text, "time": datetime.now().isoformat(timespec="seconds")}
        self.records.append(record)
        self.records = self.records[-500:]
        self.settings.setValue("history", json.dumps(self.records))
        self._add_record_row(record)
        self.update_stats()

    def add_meeting(self, text):
        record = {"text": text, "time": datetime.now().strftime("%Y-%m-%d %H:%M")}
        self.meeting_records.append(record)
        self.meeting_records = self.meeting_records[-100:]
        self.settings.setValue("meetings", json.dumps(self.meeting_records))
        self._add_meeting_row(record)

    def _add_meeting_row(self, record):
        text = record["text"]
        summary, actions = meeting_brief(text)
        followups = "\n".join(f"• {action}" for action in actions) if actions else "No follow-up phrases detected."
        item = QListWidgetItem(f"Meeting - {record['time']}\nSummary: {summary}\nNext steps: {followups}")
        item.setToolTip(text)
        item.setData(Qt.ItemDataRole.UserRole, text)
        self.notes_text.insertItem(0, item)

    def update_stats(self):
        total_words = sum(len(record["text"].split()) for record in self.records)
        days = {datetime.fromisoformat(record["time"]).date() for record in self.records}
        streak, day = 0, datetime.now().date()
        if day not in days:
            day = day.fromordinal(day.toordinal() - 1)
        while day in days:
            streak += 1
            day = day.fromordinal(day.toordinal() - 1)
        self.words_stat.setText(f"{total_words:,} total words")
        self.count_stat.setText(f"{len(self.records)} dictations")
        self.insights_words.setText(f"{total_words:,} total words")
        self.insights_count.setText(f"{len(self.records)} dictations")
        self.insights_streak.setText(f"{streak} day streak")

    def copy_selected(self, *_):
        item = self.items.currentItem()
        if item:
            QApplication.clipboard().setText(item.data(Qt.ItemDataRole.UserRole))

    def dictionary_words(self):
        try:
            return json.loads(self.settings.value("dictionary", "[]"))
        except (TypeError, ValueError):
            return []

    def add_dictionary_word(self):
        word = self.dictionary_input.text().strip()
        words = self.dictionary_words()
        if word and word.casefold() not in {value.casefold() for value in words}:
            words.append(word)
            self.settings.setValue("dictionary", json.dumps(words))
            self.dictionary_items.addItem(word)
        self.dictionary_input.clear()

    def remove_dictionary_word(self):
        row = self.dictionary_items.currentRow()
        if row >= 0:
            self.dictionary_items.takeItem(row)
            self.settings.setValue("dictionary", json.dumps([self.dictionary_items.item(i).text() for i in range(self.dictionary_items.count())]))

    def snippets(self):
        try:
            return json.loads(self.settings.value("snippets", "{}"))
        except (TypeError, ValueError):
            return {}

    def refresh_snippets(self):
        self.snippets_table.setRowCount(0)
        for trigger, replacement in self.snippets().items():
            row = self.snippets_table.rowCount()
            self.snippets_table.insertRow(row)
            self.snippets_table.setItem(row, 0, QTableWidgetItem(trigger))
            self.snippets_table.setItem(row, 1, QTableWidgetItem(replacement))

    def add_snippet(self):
        trigger, replacement = self.snippet_trigger.text().strip(), self.snippet_text.text().strip()
        if trigger and replacement:
            snippets = self.snippets()
            snippets[trigger] = replacement
            self.settings.setValue("snippets", json.dumps(snippets))
            self.refresh_snippets()
        self.snippet_trigger.clear()
        self.snippet_text.clear()

    def remove_snippet(self):
        row = self.snippets_table.currentRow()
        if row >= 0:
            trigger = self.snippets_table.item(row, 0).text()
            snippets = self.snippets()
            snippets.pop(trigger, None)
            self.settings.setValue("snippets", json.dumps(snippets))
            self.refresh_snippets()
class Assistant:
    def __init__(self, app):
        self.app = app
        self.overlay = Overlay()
        self.recorder = None
        self.engine = Transcriber()
        self.engine.partial.connect(self.preview)
        self.engine.finished.connect(self.complete)
        self.engine.failed.connect(self.error)
        self.recording = False
        self.processing = False
        self.notetaker_active = False
        self.active_mode = "dictation"
        self.last_text = ""
        self.notetaker_mic = None
        self.system_audio = None
        self.history = HistoryDashboard()
        self.history.notetaker_start.connect(self.start_notetaker)
        self.history.notetaker_stop.connect(self.stop_notetaker)
        self.tray = QSystemTrayIcon(self.app.style().standardIcon(self.app.style().StandardPixmap.SP_MediaVolume), app)
        menu = QMenu()
        for title, action in [("Toggle recording", self.toggle), ("Transcription history", self.show_history), ("Copy last transcript", self.copy_last), ("Show overlay", self.overlay.show), ("Quit", self.quit)]:
            item = QAction(title, menu)
            item.triggered.connect(action)
            menu.addAction(item)
        self.tray.setContextMenu(menu)
        self.tray.setToolTip("Neyra")
        self.tray.show()
        self.hotkeys = None
        if not is_wayland():
            try:
                from .hotkeys import Hotkeys
                self.hotkeys = Hotkeys()
                self.hotkeys.hold_start.connect(self.start)
                self.hotkeys.hold_stop.connect(self.stop)
                self.hotkeys.toggle.connect(self.toggle)
                self.hotkeys.start()
            except Exception as exc:
                self.overlay.text = f"Hotkeys unavailable: {exc}. Use tray menu."
        else:
            self.overlay.text = "Wayland: use tray menu; compositor shortcuts can be configured externally"

    def start(self):
        if self.recording or self.processing or self.notetaker_active:
            return
        self.overlay.state = "Listening"
        self.overlay.text = "Speak now..."
        self.overlay.show()
        chunks = queue.Queue()
        self.recorder = Microphone(chunks, lambda value: setattr(self.overlay, "level", value))
        try:
            self.recorder.start()
            self.recording = True
            hints = self.history.dictionary_words() + list(self.history.snippets())
            self.engine.run(chunks, keywords=hints)
        except Exception as exc:
            self.recording = False
            self.overlay.state = "Error"
            self.overlay.text = str(exc)
            if self.recorder and self.recorder.stream:
                self.recorder.stop()

    def stop(self):
        if not self.recording: return
        self.recording = False
        self.processing = True
        self.overlay.state = "Transcribing"
        self.overlay.hide()
        try:
            self.recorder.stop()
        except Exception as exc:
            self.error(str(exc))

    def toggle(self):
        if self.recording: self.stop()
        else: self.start()

    def preview(self, text):
        if self.active_mode == "notetaker":
            self.history.notetaker_status.setText(text or "Transcribing meeting audio...")
        else:
            self.overlay.text = text or "Listening..."

    def complete(self, text):
        self.processing = False
        text = expand_snippets(apply_style(text, self.history.style_choice.currentText()), self.history.snippets())
        if self.active_mode == "notetaker":
            self.history.add_meeting(text or "No speech detected.")
            self.history.notetaker_status.setText("Meeting transcript saved." if text else "No speech detected.")
            self.active_mode = "dictation"
            return
        self.last_text = text
        self.overlay.state = "Ready"
        self.overlay.text = text or "No speech detected"
        if text:
            self.history.add_transcript(text)
            QApplication.clipboard().setText(text)
            try:
                insert_text(text)
            except Exception as exc:
                self.error(f"Transcript copied, but paste failed: {exc}")

    def start_notetaker(self):
        if self.notetaker_active or self.recording or self.processing:
            return
        try:
            self.notetaker_chunks = queue.Queue()
            self.notetaker_mic = Microphone(self.notetaker_chunks, lambda value: None)
            self.system_audio = SystemAudioRecorder()
            self.system_audio.start()
            self.notetaker_mic.start()
            self.notetaker_active = True
            self.history.notetaker_status.setText("Recording microphone and default speaker audio...")
        except Exception as exc:
            if self.notetaker_mic and self.notetaker_mic.stream:
                self.notetaker_mic.stop()
            if self.system_audio:
                try:
                    self.system_audio.stop()
                except Exception:
                    pass
            self.history.notetaker_status.setText(f"Could not start meeting capture: {exc}")

    def stop_notetaker(self):
        if not self.notetaker_active:
            return
        try:
            self.notetaker_active = False
            self.notetaker_mic.stop()
            system = self.system_audio.stop()
            mic_chunks = []
            while True:
                chunk = self.notetaker_chunks.get()
                if chunk is None:
                    break
                mic_chunks.append(chunk)
            mic = np.concatenate(mic_chunks) if mic_chunks else np.empty(0, dtype=np.float32)
            length = max(len(mic), len(system))
            if not length:
                self.history.notetaker_status.setText("No meeting audio was captured.")
                return
            mixed = np.zeros(length, dtype=np.float32)
            if len(mic):
                mixed[:len(mic)] += mic * 0.5
            if len(system):
                mixed[:len(system)] += system * 0.5
            chunks = queue.Queue()
            for offset in range(0, length, 3 * 16_000):
                chunks.put(mixed[offset:offset + 3 * 16_000])
            chunks.put(None)
            self.processing = True
            self.active_mode = "notetaker"
            self.history.notetaker_status.setText("Transcribing meeting audio...")
            hints = self.history.dictionary_words() + list(self.history.snippets())
            self.engine.run(chunks, keywords=hints)
        except Exception as exc:
            self.processing = False
            self.active_mode = "dictation"
            self.history.notetaker_status.setText(f"Meeting transcription failed: {exc}")

    def error(self, message):
        self.processing = False
        self.recording = False
        self.overlay.state = "Error"
        self.overlay.text = message
        self.overlay.show()

    def copy_last(self):
        if self.last_text:
            QApplication.clipboard().setText(self.last_text)

    def show_history(self):
        self.history.show()
        self.history.raise_()
        self.history.activateWindow()

    def quit(self):
        if self.recording: self.stop()
        if self.hotkeys: self.hotkeys.stop()
        self.tray.hide()
        self.app.quit()

def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    controller = Assistant(app)
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
