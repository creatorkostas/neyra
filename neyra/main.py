import sys
import math
import queue
import json
import time
import numpy as np
from datetime import datetime
from PySide6.QtCore import Qt, QTimer, QPoint, Signal, QSize, QSettings, QObject, Slot
from PySide6.QtGui import QColor, QPainter, QPen, QAction
from PySide6.QtWidgets import QApplication, QWidget, QSystemTrayIcon, QMenu, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QPushButton, QFrame, QStackedWidget, QLineEdit, QTableWidget, QTableWidgetItem, QProgressBar, QMessageBox, QAbstractItemView
from .audio import Microphone
from .stt import Transcriber
from .desktop import insert_text, is_wayland
from .text_tools import apply_style, expand_snippets
from .system_audio import SystemAudioRecorder
from .ui import THEME, TranscriptFeed, DashboardComboBox, NotetakerPanel, icon, icon_button
from .meeting import bridge_path, validated_words


def load_setting(settings, key, expected, default):
    try:
        value = json.loads(settings.value(key, json.dumps(default)))
        return value if isinstance(value, expected) else default
    except (TypeError, ValueError):
        return default


def load_records(settings, key):
    records = []
    for record in load_setting(settings, key, list, []):
        try:
            if not isinstance(record, dict) or not isinstance(record.get("text"), str):
                continue
            datetime.fromisoformat(record["time"])
            if key == "meetings":
                record = dict(record)
                record["title"] = record.get("title") if isinstance(record.get("title"), str) else ""
                record["topics"] = [topic for topic in record.get("topics", []) if isinstance(topic, dict) and isinstance(topic.get("name"), str) and isinstance(topic.get("slug"), str)] if isinstance(record.get("topics"), list) else []
                if "words" in record:
                    try:
                        words = validated_words(record["words"], 10_000_000)
                        for clean, original in zip(words, record["words"]):
                            clean["speakers"] = [speaker for speaker in original.get("speakers", []) if isinstance(speaker, int) and not isinstance(speaker, bool) and speaker >= 0] if isinstance(original.get("speakers"), list) else []
                        record["words"] = words
                    except (TypeError, ValueError):
                        record["words"] = []
                record["warnings"] = [message for message in record.get("warnings", []) if isinstance(message, str)] if isinstance(record.get("warnings"), list) else []
            records.append(record)
        except (TypeError, ValueError, KeyError):
            continue
    return records

class Overlay(QWidget):
    start_requested = Signal()
    stop_requested = Signal()
    toggle_requested = Signal()

    def __init__(self):
        super().__init__()
        self.setFixedSize(410, 128)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.move(90, 90)
        self.drag_offset = QPoint()
        self.level = 0.0
        self.phase = 0.0
        self.state = "Ready"
        self.text = "Hold Ctrl+Win to dictate"
        self.tick = QTimer(self)
        self.tick.timeout.connect(self.animate)
        self.tick.setInterval(33)

    def showEvent(self, event):
        self.tick.start()
        super().showEvent(event)

    def hideEvent(self, event):
        self.tick.stop()
        super().hideEvent(event)

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
        self.setObjectName("dashboard")
        self.setWindowTitle("Neyra")
        self.setWindowIcon(icon("wave"))
        self.resize(1340, 840)
        self.setMinimumSize(1000, 640)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setSizeGripEnabled(True)
        self.settings = QSettings(QSettings.defaultFormat(), QSettings.Scope.UserScope, "Neyra", "Neyra")
        self.records = load_records(self.settings, "history")[-500:]
        self.setStyleSheet(THEME)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 9, 9)
        root.setSpacing(0)
        bar = QWidget()
        bar.setObjectName("windowBar")
        bar.setFixedHeight(44)
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(14, 2, 8, 2)
        sidebar_toggle = icon_button("sidebar", "Toggle sidebar")
        bar_layout.addWidget(sidebar_toggle)
        bar_layout.addStretch()
        self.status_label = QLabel("Ready to dictate")
        self.status_label.setObjectName("muted")
        bar_layout.addWidget(self.status_label)
        bar_layout.addSpacing(20)
        for name, tip, callback in (
            ("minimize", "Minimize", self.showMinimized),
            ("maximize", "Maximize or restore", self.toggle_maximized),
            ("close", "Close dashboard", self.close),
        ):
            button = icon_button(name, tip)
            button.clicked.connect(callback)
            bar_layout.addWidget(button)
        bar.mousePressEvent = self.begin_window_drag
        root.addWidget(bar)
        main = QHBoxLayout()
        main.setSpacing(0)
        root.addLayout(main, 1)
        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(214)
        sidebar_toggle.clicked.connect(lambda: self.sidebar.setVisible(not self.sidebar.isVisible()))
        side = QVBoxLayout(self.sidebar)
        side.setContentsMargins(12, 18, 12, 8)
        side.setSpacing(4)
        brand_row = QHBoxLayout()
        mark = QLabel()
        mark.setPixmap(icon("wave", 28).pixmap(28, 28))
        brand_row.addWidget(mark)
        brand = QLabel("Neyra")
        brand.setObjectName("brand")
        brand_row.addWidget(brand)
        brand_row.addStretch()
        side.addLayout(brand_row)
        side.addSpacing(23)
        self.nav_buttons = []
        for index, name in enumerate(("Dictation", "Notetaker", "Insights", "Dictionary", "Snippets", "Style")):
            button = QPushButton(name)
            button.setObjectName("nav")
            button.setIcon(icon(name.lower()))
            button.setIconSize(QSize(20, 20))
            button.setCheckable(True)
            button.setFixedHeight(38)
            button.clicked.connect(lambda checked=False, page=index: self.show_page(page))
            side.addWidget(button)
            self.nav_buttons.append(button)
        self.nav_buttons[0].setChecked(True)
        side.addStretch(1)
        promo = QFrame()
        self.promo = promo
        promo.setObjectName("promoCard")
        promo_layout = QVBoxLayout(promo)
        promo_layout.setContentsMargins(12, 14, 12, 12)
        graphic = QLabel()
        graphic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        graphic.setPixmap(icon("notetaker", 52, "#8037af").pixmap(52, 52))
        graphic.setStyleSheet("background: #f4e6d7; border-radius: 9px; padding: 18px;")
        promo_layout.addWidget(graphic)
        promo_layout.addWidget(QLabel("Explore Notetaker"))
        description = QLabel("Keep a transcript, summary and next steps for your meetings.")
        description.setObjectName("muted")
        description.setWordWrap(True)
        promo_layout.addWidget(description)
        explore = QPushButton("Open Notetaker")
        explore.setObjectName("primary")
        explore.clicked.connect(lambda: self.show_page(1))
        promo_layout.addWidget(explore)
        side.addWidget(promo)
        side.addSpacing(14)
        for name, callback in (("Settings", lambda: self.show_page(5)), ("Help", self.show_help)):
            button = QPushButton(name)
            button.setObjectName("nav")
            button.setIcon(icon(name.lower()))
            button.clicked.connect(callback)
            side.addWidget(button)
        main.addWidget(self.sidebar)
        content = QFrame()
        content.setObjectName("surface")
        body = QVBoxLayout(content)
        body.setContentsMargins(40, 44, 32, 24)
        body.setSpacing(20)
        self.heading = QLabel("Welcome back")
        self.heading.setObjectName("heading")
        body.addWidget(self.heading)
        self.pages = QStackedWidget()
        body.addWidget(self.pages, 1)
        main.addWidget(content, 1)

        # Dictation history
        dictation = QWidget()
        columns = QHBoxLayout(dictation)
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(24)
        feed = QVBoxLayout()
        feed.setSpacing(0)
        search_row = QHBoxLayout()
        self.feed_date = QLabel()
        self.feed_date.setObjectName("dateLabel")
        search_row.addWidget(self.feed_date)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search your transcriptions")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setFixedHeight(36)
        self.search_input.hide()
        search_row.addWidget(self.search_input, 1)
        search_row.addStretch()
        search_button = icon_button("search", "Search transcriptions")
        search_button.clicked.connect(self.toggle_search)
        search_row.addWidget(search_button)
        feed.addLayout(search_row)
        self.items = TranscriptFeed()
        self.items.show_first_date = False
        self.items.delete_requested.connect(self.delete_transcript)
        self.search_input.textChanged.connect(self.search_history)
        feed.addWidget(self.items, 1)
        columns.addLayout(feed, 1)
        summary = QFrame()
        summary.setObjectName("summaryCard")
        summary.setFixedWidth(250)
        stats = QVBoxLayout(summary)
        stats.setContentsMargins(24, 24, 24, 25)
        stats.setSpacing(14)
        self.words_stat = QLabel()
        self.count_stat = QLabel()
        self.latest_stat = QLabel()
        for stat in (self.words_stat, self.count_stat, self.latest_stat):
            stat.setStyleSheet("font-size: 17px;")
            stats.addWidget(stat)
        stats.addSpacing(7)
        line = QFrame()
        line.setObjectName("divider")
        line.setFixedHeight(1)
        stats.addWidget(line)
        stats.addSpacing(8)
        title = QLabel("Your dictation activity")
        title.setStyleSheet("font-weight: 600;")
        stats.addWidget(title)
        note = QLabel("Words captured locally with Neyra")
        note.setObjectName("muted")
        stats.addWidget(note)
        self.words_progress = QProgressBar()
        self.words_progress.setRange(0, 5000)
        self.words_progress.setTextVisible(False)
        stats.addWidget(self.words_progress)
        self.words_goal = QLabel()
        self.words_goal.setObjectName("muted")
        stats.addWidget(self.words_goal)
        columns.addWidget(summary, 0, Qt.AlignmentFlag.AlignTop)
        self.pages.addWidget(dictation)

        # Meeting notes
        self.meeting_records = load_records(self.settings, "meetings")[-100:]
        show_intro = not self.settings.value("notetaker_intro_dismissed", False, type=bool)
        self.notetaker = NotetakerPanel(self.meeting_records, show_intro=show_intro)
        for toggle, key, default in ((self.notetaker.speaker_toggle, "speakers", False), (self.notetaker.cleanup_toggle, "cleanup", False), (self.notetaker.organize_toggle, "organize", True)):
            toggle.setChecked(self.settings.value(f"meeting_{key}", default, type=bool))
        language_index = self.notetaker.language_choice.findData(self.settings.value("meeting_language", "en"))
        self.notetaker.language_choice.setCurrentIndex(max(0, language_index))
        self.notetaker.options_changed.connect(self.save_meeting_options)
        self.notetaker.record_updated.connect(self.save_meetings)
        self.notetaker.start_requested.connect(self.notetaker_start.emit)
        self.notetaker.stop_requested.connect(self.notetaker_stop.emit)
        self.notetaker.settings_requested.connect(lambda: self.show_page(5))
        self.notetaker.delete_requested.connect(self.delete_meeting)
        self.notetaker.intro_dismissed.connect(lambda: self.settings.setValue("notetaker_intro_dismissed", True))
        self.notetaker_status = self.notetaker.status
        self.pages.addWidget(self.notetaker)

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
        dictionary_layout.addWidget(QLabel("Names and technical terms guide Whistle recognition. Voz does not support dictionary hints."))
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
        self.snippets_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.snippets_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
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
        self.style_choice = DashboardComboBox()
        self.style_choice.addItems(["Natural", "Clean up speech", "Formal"])
        self.style_choice.setCurrentText(self.settings.value("style", "Clean up speech"))
        self.style_choice.currentTextChanged.connect(lambda value: self.settings.setValue("style", value))
        style_layout.addWidget(self.style_choice)
        style_layout.addWidget(QLabel("Cleanup is local and rule-based. No cloud rewrite is used."))
        style_layout.addWidget(QLabel("Transcription engine"))
        self.engine_choice = DashboardComboBox()
        self.engine_choice.addItem("Whistle — live text every 3 seconds", "whistle")
        self.engine_choice.addItem("Voz — final text after release", "voz")
        saved_engine = self.settings.value("transcription_engine", "whistle")
        engine_index = self.engine_choice.findData(saved_engine)
        self.engine_choice.setCurrentIndex(engine_index if engine_index >= 0 else 0)
        self.engine_choice.currentIndexChanged.connect(
            lambda _: self.settings.setValue("transcription_engine", self.engine_choice.currentData()))
        style_layout.addWidget(self.engine_choice)
        style_layout.addWidget(QLabel("Voz needs Node.js 20+ and downloads its model on first use. Node inference uses the CPU; its loaded model uses about 1.2 GB of memory."))
        style_layout.addStretch()
        self.pages.addWidget(style)

        self.items.refresh(self.records)
        self.update_stats()
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
        for label in self.findChildren(QLabel):
            if len(label.text()) > 80:
                label.setWordWrap(True)

    def show_page(self, index):
        self.pages.setCurrentIndex(index)
        self.heading.setVisible(index != 1)
        self.heading.setText(("Welcome back", "Notetaker", "Insights", "Dictionary", "Snippets", "Style & settings")[index])
        for i, button in enumerate(self.nav_buttons):
            button.setChecked(i == index)

    def toggle_maximized(self):
        self.showNormal() if self.isMaximized() else self.showMaximized()

    def resizeEvent(self, event):
        if hasattr(self, "promo"):
            self.promo.setVisible(self.height() >= 770)
        super().resizeEvent(event)

    def search_history(self, text):
        self.feed_date.setVisible(not text.strip())
        self.items.refresh(query=text)

    def begin_window_drag(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.windowHandle():
            self.windowHandle().startSystemMove()

    def show_help(self):
        QMessageBox.information(self, "Using Neyra", "Hold Ctrl + Win to dictate, then release to paste.\nCtrl + Shift + Space toggles recording.\n\nDouble-click the tray icon to open this dashboard.\nChoose your transcription engine in Settings.\nAll transcripts are stored locally on this computer.")

    def toggle_search(self):
        self.search_input.setVisible(not self.search_input.isVisible())
        if self.search_input.isVisible():
            self.search_input.setFocus()
        else:
            self.search_input.clear()

    def delete_transcript(self, record):
        self.records.remove(record)
        self.settings.setValue("history", json.dumps(self.records))
        self.items.refresh(self.records)
        self.update_stats()

    def add_transcript(self, text, duration=0):
        record = {"text": text, "time": datetime.now().isoformat(timespec="seconds"), "duration": max(0, duration)}
        self.records.append(record)
        self.records = self.records[-500:]
        self.settings.setValue("history", json.dumps(self.records))
        self.items.refresh(self.records)
        self.update_stats()

    def save_meeting_options(self):
        for key, value in self.notetaker.processing_options().items():
            self.settings.setValue(f"meeting_{key}", value)

    def save_meetings(self):
        self.settings.setValue("meetings", json.dumps(self.meeting_records))

    def add_meeting(self, text, metadata=None):
        record = dict(metadata or {})
        record.update(text=text, time=datetime.now().isoformat(timespec="seconds"))
        self.meeting_records.append(record)
        self.meeting_records = self.meeting_records[-100:]
        self.settings.setValue("meetings", json.dumps(self.meeting_records))
        self.notetaker.records = self.meeting_records
        self.notetaker.refresh()

    def delete_meeting(self, record):
        self.meeting_records.remove(record)
        self.settings.setValue("meetings", json.dumps(self.meeting_records))
        self.notetaker.refresh()

    def set_meeting_state(self, state, message=None):
        self.notetaker.set_state(state, message)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#e8e5de"), 1))
        painter.setBrush(QColor("#f6f5f2"))
        radius = 0 if self.isMaximized() else 10
        painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), radius, radius)

    def update_stats(self):
        total_words = sum(len(record["text"].split()) for record in self.records)
        days = {datetime.fromisoformat(record["time"]).date() for record in self.records}
        streak, day = 0, datetime.now().date()
        if day not in days:
            day = day.fromordinal(day.toordinal() - 1)
        while day in days:
            streak += 1
            day = day.fromordinal(day.toordinal() - 1)
        date = datetime.fromisoformat(self.records[-1]["time"]) if self.records else datetime.now()
        self.feed_date.setText(date.strftime("%B %d, %Y").upper())
        def number(value, unit):
            return f'<span style="font-family: Georgia; font-size: 28px;">{value}</span> {unit}'
        self.words_stat.setText(number(f"{total_words:,}", "total words"))
        durations = [(r, r.get("duration", 0)) for r in self.records]
        timed = [(r, d) for r, d in durations if isinstance(d, (int, float)) and d > 0]
        seconds = sum(d for _, d in timed)
        wpm = round(sum(len(r["text"].split()) for r, _ in timed) * 60 / seconds) if seconds else 0
        self.count_stat.setText(number(wpm, "wpm"))
        self.count_stat.setToolTip("Average words per minute for timed recordings" if seconds else "Speed appears after your first new recording")
        self.latest_stat.setText(number(streak, "day streak"))
        self.words_progress.setValue(min(total_words, 5000))
        self.words_goal.setText(f"{total_words:,} / 5,000 words")
        self.insights_words.setText(f"{total_words:,} total words")
        self.insights_count.setText(f"{len(self.records)} dictations")
        self.insights_streak.setText(f"{streak} day streak")

    def dictionary_words(self):
        return [value for value in load_setting(self.settings, "dictionary", list, []) if isinstance(value, str)]

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
        return {key: value for key, value in load_setting(self.settings, "snippets", dict, {}).items()
                if isinstance(key, str) and isinstance(value, str)}

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
class Assistant(QObject):
    level_changed = Signal(float)

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.closing = False
        self.recording_duration = 0
        self.recording_started = 0
        self._pending_paste = ""
        self.paste_timer = QTimer(self)
        self.paste_timer.setInterval(50)
        self.paste_timer.timeout.connect(self.paste_when_released)
        self.overlay = Overlay()
        self.level_changed.connect(self.set_level)
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
        self._meeting_audio = None
        self._meeting_capture_warnings = []
        self.history = HistoryDashboard()
        self.app.aboutToQuit.connect(self.cleanup)
        self.history.notetaker_start.connect(self.start_notetaker)
        self.history.notetaker_stop.connect(self.stop_notetaker)
        self.history.notetaker.retry_requested.connect(self.process_meeting)
        self.history.notetaker.discard_requested.connect(self.discard_meeting)
        self.tray = QSystemTrayIcon(icon("wave"), app)
        menu = QMenu()
        for title, action in [("Toggle recording", self.toggle), ("Transcription history", self.show_history), ("Copy last transcript", self.copy_last), ("Show overlay", self.overlay.show), ("Quit", self.quit)]:
            item = QAction(title, menu)
            item.triggered.connect(action)
            menu.addAction(item)
        self.tray.setContextMenu(menu)
        self.tray.setToolTip("Neyra")
        self.tray.activated.connect(self.tray_activated)
        self.tray.show()
        self.history.engine_choice.currentIndexChanged.connect(self.prepare_selected_engine)
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
        self.prepare_selected_engine()

    def prepare_selected_engine(self, *_):
        if self.history.engine_choice.currentData() == "whistle":
            self.engine.prepare_whistle()

    @Slot(float)
    def set_level(self, value):
        self.overlay.level = value

    @Slot()
    def start(self):
        if self.closing or self.recording or self.notetaker_active:
            return
        if self.processing:
            self.overlay.state = "Transcribing"
            self.overlay.show()
            return
        self._pending_paste = ""
        self.paste_timer.stop()
        self.overlay.state = "Listening"
        self.overlay.text = "Speak now..."
        self.overlay.show()
        chunks = queue.Queue()
        self.recorder = Microphone(chunks, self.level_changed.emit)
        try:
            self.recorder.start()
            self.recording = True
            self.recording_started = time.monotonic()
            self.history.status_label.setText("Listening...")
            hints = self.history.dictionary_words() + list(self.history.snippets())
            self.engine.run(chunks, keywords=hints, model=self.history.engine_choice.currentData())
        except Exception as exc:
            self.error(str(exc))

    @Slot()
    def stop(self):
        self.overlay.hide()
        if not self.recording: return
        self.recording = False
        self.recording_duration = time.monotonic() - self.recording_started
        self.processing = True
        self.history.status_label.setText("Transcribing...")
        self.overlay.state = "Transcribing"
        self.overlay.hide()
        try:
            self.recorder.stop()
        except Exception as exc:
            self.error(str(exc))

    @Slot()
    def toggle(self):
        if self.recording: self.stop()
        else: self.start()

    @Slot(str)
    def preview(self, text):
        if self.closing:
            return
        self.history.status_label.setText(text[:95] or "Listening...")
        if self.active_mode == "notetaker":
            self.history.notetaker_status.setText(text or "Transcribing meeting audio...")
        else:
            self.overlay.text = text or "Listening..."

    @Slot(str)
    def complete(self, text):
        if self.closing:
            return
        self.processing = False
        self.history.status_label.setText("Ready to dictate" if text else "No speech detected")
        if self.active_mode == "notetaker":
            metadata = dict(self.engine.meeting_result or {})
            metadata["warnings"] = [*metadata.get("warnings", []), *self._meeting_capture_warnings]
            self.history.add_meeting(text or "No speech detected.", metadata)
            warnings = metadata.get("warnings", []) if metadata else []
            self.history.set_meeting_state("idle", "Meeting saved. " + " ".join(warnings) if warnings else "Meeting transcript saved." if text else "No speech detected.")
            self._meeting_audio = None
            self._meeting_capture_warnings = []
            self.history.notetaker.set_recovery(False)
            self.active_mode = "dictation"
            return
        text = expand_snippets(apply_style(text, self.history.style_choice.currentText()), self.history.snippets())
        self.last_text = text
        self.overlay.state = "Ready"
        self.overlay.text = text or "No speech detected"
        if text:
            self.history.add_transcript(text, self.recording_duration)
            QApplication.clipboard().setText(text)
            self._pending_paste = text
            self.paste_timer.start()

    @Slot()
    def paste_when_released(self):
        if self.hotkeys and self.hotkeys.modifiers_active():
            return
        self.paste_timer.stop()
        text, self._pending_paste = self._pending_paste, ""
        if text and not self.closing:
            try:
                insert_text(text)
            except Exception as exc:
                self.error(f"Transcript copied, but paste failed: {exc}")

    def start_notetaker(self):
        if self.closing or self.notetaker_active or self.recording or self.processing or self._meeting_audio is not None:
            return
        try:
            bridge_path()
            self.meeting_options = self.history.notetaker.processing_options()
            self._meeting_capture_warnings = []
            self.notetaker_chunks = queue.Queue()
            self.notetaker_mic = Microphone(self.notetaker_chunks, lambda value: None)
            self.system_audio = SystemAudioRecorder()
            self.system_audio.start()
            self.notetaker_mic.start()
            self.notetaker_active = True
            self.history.status_label.setText("Recording meeting...")
            self.history.set_meeting_state("recording", "Recording microphone and computer audio. Stop when your meeting ends.")
        except Exception as exc:
            self.stop_meeting_capture()
            self.history.set_meeting_state("idle", f"Could not start meeting capture: {exc}")

    def discard_meeting(self):
        if self.processing:
            return
        self._meeting_audio = None
        self._meeting_capture_warnings = []
        self.history.notetaker.set_recovery(False)
        self.history.set_meeting_state("idle", "Recording discarded.")

    def process_meeting(self):
        if self.closing or self.processing or self.recording or self._meeting_audio is None:
            return
        try:
            # Retry uses the current toggles so a failed optional model can be disabled.
            self.meeting_options = self.history.notetaker.processing_options()
            chunks = queue.Queue()
            for offset in range(0, len(self._meeting_audio), 3 * 16_000):
                chunks.put(self._meeting_audio[offset:offset + 3 * 16_000])
            chunks.put(None)
            self.processing = True
            self.active_mode = "notetaker"
            self.history.notetaker.set_recovery(False)
            self.history.set_meeting_state("transcribing", "Processing meeting audio locally...")
            self.history.status_label.setText("Transcribing meeting...")
            self.engine.run(chunks, model="voz", meeting_options=self.meeting_options)
        except Exception as exc:
            self.error(str(exc))

    def stop_meeting_capture(self):
        errors = []
        system = np.empty(0, dtype=np.float32)
        for recorder in (self.notetaker_mic, self.system_audio):
            if recorder:
                try:
                    result = recorder.stop()
                    if recorder is self.system_audio:
                        system = result
                except Exception as exc:
                    errors.append(str(exc))
        return system, errors

    def stop_notetaker(self):
        if not self.notetaker_active:
            return
        try:
            self.notetaker_active = False
            system, errors = self.stop_meeting_capture()
            mic_chunks = []
            while not self.notetaker_chunks.empty():
                chunk = self.notetaker_chunks.get_nowait()
                if chunk is None:
                    break
                mic_chunks.append(chunk)
            mic = np.concatenate(mic_chunks) if mic_chunks else np.empty(0, dtype=np.float32)
            length = max(len(mic), len(system))
            if not length:
                self.history.set_meeting_state("idle", "Capture failed: " + "; ".join(errors) if errors else "No meeting audio was captured.")
                return
            mixed = np.zeros(length, dtype=np.float32)
            if len(mic):
                mixed[:len(mic)] += mic * 0.5
            if len(system):
                mixed[:len(system)] += system * 0.5
            self._meeting_audio = mixed
            if errors:
                self._meeting_capture_warnings = ["Capture error: " + "; ".join(errors) + ". Some audio may be missing."]
                self.history.set_meeting_state("idle", self._meeting_capture_warnings[0] + " Available audio is kept for Retry processing.")
                self.history.notetaker.set_recovery(True)
            else:
                self.process_meeting()
        except Exception as exc:
            self.processing = False
            self.active_mode = "dictation"
            self.history.set_meeting_state("idle", f"Meeting transcription failed: {exc}")

    @Slot(str)
    def error(self, message):
        if self.closing:
            return
        if self.recorder and self.recorder.stream:
            try:
                self.recorder.stop()
            except Exception as exc:
                message += f"; microphone cleanup: {exc}"
        self.processing = False
        self.recording = False
        self.history.status_label.setText(message[:120])
        if self.active_mode == "notetaker":
            self.history.set_meeting_state("idle", f"Meeting transcription failed: {message}")
            self.history.notetaker.set_recovery(self._meeting_audio is not None)
            self.active_mode = "dictation"
            return
        self.overlay.state = "Error"
        self.overlay.text = message
        self.tray.showMessage("Neyra", message, QSystemTrayIcon.MessageIcon.Warning)

    def copy_last(self):
        if self.last_text:
            QApplication.clipboard().setText(self.last_text)

    def show_history(self):
        if self.history.isMinimized():
            self.history.showNormal()
        else:
            self.history.show()
        self.history.raise_()
        self.history.activateWindow()

    def tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_history()

    def quit(self):
        self.app.quit()

    @Slot()
    def cleanup(self):
        if self.closing:
            return
        self.closing = True
        self.history.notetaker.timer.stop()
        self.paste_timer.stop()
        if self.recorder:
            try:
                self.recorder.stop()
            except Exception:
                pass
        self.stop_meeting_capture()
        self._meeting_audio = None
        self.engine.close()
        if self.hotkeys:
            self.hotkeys.stop()
        self.tray.hide()
        self.overlay.hide()

def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    controller = Assistant(app)
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
