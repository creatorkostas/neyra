import locale
import math
import sys
import queue
import json
import time
import shutil
from pathlib import Path
import numpy as np
from datetime import datetime
from PySide6.QtCore import Qt, QTimer, QPoint, Signal, QSize, QSettings, QObject, Slot, QProcess
from PySide6.QtGui import QColor, QPainter, QPen, QAction, QFont
from PySide6.QtWidgets import QApplication, QWidget, QSystemTrayIcon, QMenu, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QPushButton, QFrame, QStackedWidget, QLineEdit, QTableWidget, QTableWidgetItem, QMessageBox, QAbstractItemView, QCheckBox, QScrollArea, QFileDialog
from .audio import Microphone, input_devices
from .stt import Transcriber
from .desktop import insert_text, is_wayland
from .speaker_mute import SpeakerMute
from .speech import VOICE, VOICE_CATALOG
from .analytics import AnalyticsPanel
from .text_tools import apply_style, expand_snippets
from .system_audio import SystemAudioRecorder
from .ui import THEME, TranscriptFeed, DashboardComboBox, NotetakerPanel, DictationPanel, InputMeter, icon, icon_button, app_icon
from .meeting import bridge_path, validated_words
from . import startup
from .reminders import ReminderStore, snooze_deadline
from .reminders_ui import RemindersPanel, ReminderAlert, due_label
from .assistant_ui import AssistantPanel
from .assistant_features import AssistantFeatures
from .home_ui import HomePanel
from .preferences_ui import ShortcutsPanel, DataPanel
from .shortcuts import load_bindings, validate_bindings, shortcut_label


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
    cancel_requested = Signal()
    start_requested = Signal()
    stop_requested = Signal()
    toggle_requested = Signal()

    def __init__(self):
        super().__init__()
        self.setFixedSize(410, 128)
        self.setFont(QFont("Segoe UI", 10))
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
        self.assistant_mode = False
        self.action_button = QPushButton("Cancel", self)
        self.action_button.setGeometry(326, 12, 64, 28)
        self.action_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.action_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.action_button.setStyleSheet("QPushButton { color: #ffffff; background: #365bd6; border: none; border-radius: 7px; font-size: 12px; padding: 3px; } QPushButton:hover { background: #2949ba; }")
        self.action_button.clicked.connect(self.cancel_requested.emit)
        self.action_button.hide()

    def set_assistant_state(self, state, text=""):
        self.assistant_mode = True
        self.setAccessibleName("Neyra assistant " + state)
        self.setAccessibleDescription(text)
        self.state = state
        self.text = text
        self.action_button.setText("Stop" if state == "Speaking" else "Close" if state in ("Ready", "Error") else "Cancel")
        self.action_button.setAccessibleName(self.action_button.text() + " assistant")
        self.action_button.show()
        self.update()

    def set_plain_mode(self):
        self.assistant_mode = False
        self.action_button.hide()

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
        p.setBrush(QColor(24, 31, 55, 248))
        p.drawRoundedRect(self.rect().adjusted(4, 4, -4, -4), 20, 20)
        p.setPen(QColor("#c4d0f5"))
        p.drawText(20, 30 if self.assistant_mode else 26, f"NEYRA   •   {self.state}")
        for i in range(72):
            x = 20 + i * 5.15
            amp = min(1.0, self.level * 9.0)
            h = 4 + amp * (8 + abs(math.sin(i * 0.46 + self.phase) * math.cos(i * .16)) * 28)
            p.setPen(QPen(QColor("#93b6ff" if i < 25 else "#b5a4ef"), 2.6))
            p.drawLine(int(x), int(66-h/2), int(x), int(66+h/2))
        p.setPen(QColor("#d9dff2"))
        fm = p.fontMetrics()
        p.drawText(20, 105, fm.elidedText(self.text, Qt.TextElideMode.ElideRight if self.assistant_mode else Qt.TextElideMode.ElideLeft, 370))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_offset = event.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_offset)

class HistoryDashboard(QDialog):
    notetaker_start = Signal()
    notetaker_stop = Signal()
    closed = Signal()
    history_cleared = Signal()
    transcript_deleted = Signal(object)
    restore_data_requested = Signal(object)

    def __init__(self):
        super().__init__()
        self.setObjectName("dashboard")
        self.setWindowTitle("Neyra")
        self.setWindowIcon(app_icon())
        self.resize(1340, 840)
        self.setMinimumSize(1000, 640)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setSizeGripEnabled(True)
        self.settings = QSettings(QSettings.defaultFormat(), QSettings.Scope.UserScope, "Neyra", "Neyra")
        self.shortcuts = load_bindings(self.settings)
        self.capture_busy = False
        self.records = load_records(self.settings, "history")[-500:]
        self.model_states = {"whistle": ("idle", "Whistle loads in the background and recognizes English.", -1),
                             "voz": ("idle", "Voz downloads its model on first use. Select it to start loading.", -1)}
        from .themes import apply_theme
        apply_theme(self, self.settings.value("theme", "light"))
        root = QVBoxLayout(self)
        root.setContentsMargins(9, 0, 9, 9)
        root.setSpacing(0)
        bar = QWidget()
        bar.setObjectName("windowBar")
        bar.setFixedHeight(44)
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(14, 2, 8, 2)
        bar_layout.addStretch()
        self.status_label = QLabel("Ready to dictate")
        self.status_label.setObjectName("muted")
        self.status_label.setMaximumWidth(420)
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
        main = QVBoxLayout()
        main.setSpacing(0)
        root.addLayout(main, 1)
        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        side = QHBoxLayout(self.sidebar)
        side.setContentsMargins(16, 8, 16, 12)
        side.setSpacing(6)
        brand_row = QHBoxLayout()
        mark = QLabel()
        mark.setPixmap(icon("brand", 28, "#365bd6").pixmap(28, 28))
        brand_row.addWidget(mark)
        brand = QLabel("Neyra")
        brand.setObjectName("brand")
        brand_row.addWidget(brand)
        brand_row.addStretch()
        side.addLayout(brand_row)
        side.addSpacing(28)
        self.nav_buttons = {}
        for index, name in ((9, "Home"), (0, "Notes"), (7, "Reminders"), (8, "Assistant")):
            button = QPushButton(name)
            button.setObjectName("nav")
            button.setProperty("neyra_icon", name.lower())
            button.setIcon(icon(name.lower()))
            button.setIconSize(QSize(20, 20))
            button.setCheckable(True)
            button.setFixedHeight(38)
            button.clicked.connect(lambda checked=False, page=index: self.show_page(page))
            side.addWidget(button)
            self.nav_buttons[index] = button
        self.nav_buttons[9].setChecked(True)
        side.addStretch(1)
        for name, callback in (("Analytics", lambda: self.show_page(2)), ("Voice settings", lambda: self.show_page(6)), ("Help", self.show_help)):
            button = QPushButton(name)
            button.setObjectName("nav")
            button.setProperty("neyra_icon", {"Analytics": "insights", "Voice settings": "settings", "Help": "help"}[name])
            button.setIcon(icon(button.property("neyra_icon")))
            button.clicked.connect(callback)
            if name in ("Analytics", "Voice settings"):
                button.setCheckable(True)
                self.nav_buttons[2 if name == "Analytics" else 6] = button
            side.addWidget(button)
        main.addWidget(self.sidebar)
        shortcuts_bar = QWidget()
        shortcuts_layout = QHBoxLayout(shortcuts_bar)
        shortcuts_layout.setContentsMargins(24, 0, 24, 10)
        self.dictation_key_hint = QLabel()
        self.dictation_key_hint.setObjectName("muted")
        self.assistant_key_hint = QLabel()
        self.assistant_key_hint.setObjectName("muted")
        shortcuts_layout.addWidget(self.dictation_key_hint)
        shortcuts_layout.addSpacing(24)
        shortcuts_layout.addWidget(self.assistant_key_hint)
        shortcuts_layout.addStretch()
        main.addWidget(shortcuts_bar)
        content = QFrame()
        content.setObjectName("surface")
        body = QVBoxLayout(content)
        body.setContentsMargins(30, 26, 30, 24)
        body.setSpacing(20)
        self.heading = QLabel("Dictation")
        self.heading.setObjectName("heading")
        body.addWidget(self.heading)
        self.context_nav = QWidget()
        context = QHBoxLayout(self.context_nav)
        context.setContentsMargins(0, 0, 0, 0)
        self.context_buttons = {}
        for page, title in ((0, "Dictations"), (1, "Meetings"), (6, "Microphone / models"),
                            (10, "Shortcuts"), (3, "Dictionary"), (4, "Snippets"), (5, "Formatting"), (11, "Data")):
            button = QPushButton(title)
            button.setObjectName("nav")
            button.setCheckable(True)
            button.clicked.connect(lambda _=False, index=page: self.show_page(index))
            context.addWidget(button)
            self.context_buttons[page] = button
        context.addStretch()
        self.export_notes_button = QPushButton("Export notes")
        self.export_notes_button.clicked.connect(self.export_notes_file)
        context.addWidget(self.export_notes_button)
        body.addWidget(self.context_nav)
        self.pages = QStackedWidget()
        body.addWidget(self.pages, 1)
        main.addWidget(content, 1)

        # Dictation history
        dictation = QWidget()
        dictation_layout = QVBoxLayout(dictation)
        dictation_layout.setContentsMargins(0, 0, 0, 0)
        dictation_layout.setSpacing(20)
        self.capture = DictationPanel()
        self.capture.settings_requested.connect(lambda: self.show_page(6))
        dictation_layout.addWidget(self.capture)
        columns = QHBoxLayout()
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
        self.clear_history_button = QPushButton("Clear history")
        self.clear_history_button.setObjectName("textButton")
        self.clear_history_button.clicked.connect(self.clear_history)
        search_row.addWidget(self.clear_history_button)
        feed.addLayout(search_row)
        self.items = TranscriptFeed()
        self.items.show_first_date = False
        self.items.delete_requested.connect(self.delete_transcript)
        self.search_input.textChanged.connect(self.search_history)
        feed.addWidget(self.items, 1)
        columns.addLayout(feed, 1)
        dictation_layout.addLayout(columns, 1)
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
        self.notetaker.settings_requested.connect(lambda: self.show_page(6))
        self.notetaker.delete_requested.connect(self.delete_meeting)
        self.notetaker.intro_dismissed.connect(lambda: self.settings.setValue("notetaker_intro_dismissed", True))
        self.notetaker_status = self.notetaker.status
        self.pages.addWidget(self.notetaker)

        self.analytics_usage = {}
        self.analytics_panel = AnalyticsPanel()
        self.pages.addWidget(self.analytics_panel)

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
        dictionary_layout.addWidget(QLabel("Vocabulary corrections"))
        correction_hint = QLabel("Replace a misheard word or phrase in new dictations. Works with both engines; meeting timestamps stay unchanged.")
        correction_hint.setObjectName("muted")
        correction_hint.setWordWrap(True)
        dictionary_layout.addWidget(correction_hint)
        self.corrections_table = QTableWidget(0, 2)
        self.corrections_table.setAccessibleName("Vocabulary corrections")
        self.corrections_table.setHorizontalHeaderLabels(["Heard as", "Write as"])
        self.corrections_table.horizontalHeader().setStretchLastSection(True)
        self.corrections_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.corrections_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        dictionary_layout.addWidget(self.corrections_table, 1)
        correction_row = QHBoxLayout()
        self.correction_heard = QLineEdit()
        self.correction_heard.setPlaceholderText("Heard as, e.g. near a")
        self.correction_written = QLineEdit()
        self.correction_written.setPlaceholderText("Write as, e.g. Neyra")
        save_correction = QPushButton("Save correction")
        save_correction.clicked.connect(self.save_correction)
        self.correction_written.returnPressed.connect(self.save_correction)
        correction_row.addWidget(self.correction_heard, 1)
        correction_row.addWidget(self.correction_written, 1)
        correction_row.addWidget(save_correction)
        dictionary_layout.addLayout(correction_row)
        remove_correction = QPushButton("Remove correction")
        remove_correction.clicked.connect(self.remove_correction)
        dictionary_layout.addWidget(remove_correction, 0, Qt.AlignmentFlag.AlignRight)
        self.corrections_table.itemSelectionChanged.connect(self.select_correction)
        self.refresh_corrections()
        self.pages.addWidget(dictionary)

        # Spoken snippets
        snippets_page = QWidget()
        snippets_layout = QVBoxLayout(snippets_page)
        snippets_layout.addWidget(QLabel("Say a trigger phrase and Neyra expands it after transcription."))
        self.snippets_table = QTableWidget(0, 2)
        self.snippets_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.snippets_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.snippets_table.setHorizontalHeaderLabels(["Spoken trigger", "Expanded text"])
        trigger_width = self.snippets_table.fontMetrics().horizontalAdvance("Spoken trigger") + 48
        self.snippets_table.setColumnWidth(0, max(180, trigger_width))
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
        style_layout.addStretch()
        self.pages.addWidget(style)
        self.pages.addWidget(self.create_settings_page())
        self.reminders = RemindersPanel()
        self.pages.addWidget(self.reminders)
        self.assistant_panel = AssistantPanel()
        self.pages.addWidget(self.assistant_panel)
        self.home_reminders = []
        self.home = HomePanel(self.capture)
        self.pages.addWidget(self.home)
        self.home.navigate.connect(self.show_page)
        self.home.remind.connect(self.speak_home_reminder)
        self.home.meeting.connect(self.start_home_meeting)
        self.home.ask_notes.connect(self.open_note_question)
        self.reminders.records_changed.connect(self.refresh_home)
        self.shortcut_panel = ShortcutsPanel(self.settings)
        self.pages.addWidget(self.shortcut_panel)
        self.data_panel = DataPanel()
        self.pages.addWidget(self.data_panel)
        self.data_panel.export_requested.connect(self.export_notes_file)
        self.data_panel.backup_requested.connect(self.backup_file)
        self.data_panel.restore_requested.connect(self.restore_file)

        self.items.refresh(self.records)
        self.refresh_notes_state()
        self.set_shortcut_hints(self.shortcuts)
        self.show_page(9)
        self.capture.record_button.setFocus()
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
        for field in self.findChildren(QLineEdit):
            field.setAccessibleName(field.placeholderText())
        for label in self.findChildren(QLabel):
            if len(label.text()) > 80:
                label.setWordWrap(True)
        apply_theme(self, self.settings.value("theme", "light"))

    def create_settings_page(self):
        page = QScrollArea()
        page.setWidgetResizable(True)
        page.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        page.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(16)

        def card(title, description):
            frame = QFrame()
            frame.setObjectName("settingsCard")
            box = QVBoxLayout(frame)
            box.setContentsMargins(22, 18, 22, 18)
            box.setSpacing(10)
            heading = QLabel(title)
            heading.setObjectName("sectionTitle")
            box.addWidget(heading)
            note = QLabel(description)
            note.setObjectName("muted")
            note.setWordWrap(True)
            box.addWidget(note)
            layout.addWidget(frame)
            return box

        from .themes import apply_theme
        appearance = card("Appearance", "Choose a light or dark workspace. Your choice is saved.")
        self.theme_button = QPushButton("Use light theme" if self.settings.value("theme", "light") == "dark" else "Use dark theme")
        def toggle_theme():
            theme = "light" if self.settings.value("theme", "light") == "dark" else "dark"
            self.settings.setValue("theme", theme)
            apply_theme(self, theme)
            self.theme_button.setText("Use light theme" if theme == "dark" else "Use dark theme")
        self.theme_button.clicked.connect(toggle_theme)
        appearance.addWidget(self.theme_button)
        from .preferences_ui import ProviderPanel
        provider = card("Assistant provider", "Needle 3 handles local tool requests independently of the assistant.")
        self.provider_panel = ProviderPanel(self.settings)
        provider.addWidget(self.provider_panel)

        microphone = card("Microphone", "Choose the input used for dictation and meetings. Test it without saving any audio.")
        row = QHBoxLayout()
        self.mic_choice = DashboardComboBox()
        self.mic_choice.setAccessibleName("Microphone")
        row.addWidget(self.mic_choice, 1)
        self.refresh_mics_button = icon_button("refresh", "Refresh microphones")
        row.addWidget(self.refresh_mics_button)
        microphone.addLayout(row)
        meter_row = QHBoxLayout()
        self.test_mic_button = QPushButton("Test microphone")
        meter_row.addWidget(self.test_mic_button)
        self.input_meter = InputMeter()
        meter_row.addWidget(self.input_meter, 1)
        microphone.addLayout(meter_row)
        self.mic_status = QLabel("The meter lights up while testing or recording.")
        self.mic_status.setObjectName("settingStatus")
        self.mic_status.setTextFormat(Qt.TextFormat.PlainText)
        self.mic_status.setWordWrap(True)
        microphone.addWidget(self.mic_status)
        self.refresh_microphones()
        self.mic_choice.currentIndexChanged.connect(lambda _: self.settings.setValue("microphone", self.mic_choice.currentText() if self.mic_choice.currentData() is not None else ""))

        engine = card("Speech model", "Whistle gives live English text. Voz supports 25 languages and returns text when you stop recording.")
        self.engine_choice = DashboardComboBox()
        self.engine_choice.setAccessibleName("Transcription engine")
        self.engine_choice.addItem("Whistle · Lightweight, live English text", "whistle")
        self.engine_choice.addItem("Voz · Multilingual, final transcript", "voz")
        saved_engine = self.settings.value("transcription_engine", "whistle")
        engine_index = self.engine_choice.findData(saved_engine)
        self.engine_choice.setCurrentIndex(engine_index if engine_index >= 0 else 0)
        self.engine_choice.currentIndexChanged.connect(
            lambda _: self.settings.setValue("transcription_engine", self.engine_choice.currentData()))
        self.engine_choice.currentIndexChanged.connect(self.refresh_model_status)
        engine.addWidget(self.engine_choice)
        self.model_status_label = QLabel()
        self.model_status_label.setObjectName("settingStatus")
        self.model_status_label.setTextFormat(Qt.TextFormat.PlainText)
        self.model_status_label.setWordWrap(True)
        engine.addWidget(self.model_status_label)
        self.retry_model_button = QPushButton("Load / retry model")
        engine.addWidget(self.retry_model_button, 0, Qt.AlignmentFlag.AlignLeft)
        engine.addWidget(QLabel("Voz runs in Python and downloads its model on first use. Both engines use the CPU."))
        attribution = QLabel('Voz is powered by <a href="https://desertant.com">Desert Ant Labs</a>.')
        attribution.setOpenExternalLinks(True)
        engine.addWidget(attribution)
        self.refresh_model_status()

        desktop = card("Desktop", "Keep Neyra available in the system tray. Login startup uses your current app location.")
        self.autostart_toggle = QCheckBox("Start Neyra at login")
        try:
            self.autostart_toggle.setChecked(startup.is_enabled())
        except OSError:
            self.autostart_toggle.setEnabled(False)
        self.autostart_toggle.toggled.connect(self.change_autostart)
        desktop.addWidget(self.autostart_toggle)
        self.close_to_tray_toggle = QCheckBox("Keep running in the tray when I close the window")
        self.close_to_tray_toggle.setChecked(self.settings.value("close_to_tray", True, type=bool))
        self.close_to_tray_toggle.toggled.connect(lambda value: self.settings.setValue("close_to_tray", value))
        desktop.addWidget(self.close_to_tray_toggle)
        self.mute_while_speaking_toggle = QCheckBox("Mute PC audio while I speak")
        self.mute_while_speaking_toggle.setChecked(self.settings.value("mute_while_speaking", True, type=bool))
        self.mute_while_speaking_toggle.toggled.connect(lambda value: self.settings.setValue("mute_while_speaking", value))
        desktop.addWidget(self.mute_while_speaking_toggle)
        self.desktop_status = QLabel("Autostart opens in the tray when your desktop supports a tray icon.")
        self.desktop_status.setObjectName("settingStatus")
        self.desktop_status.setWordWrap(True)
        desktop.addWidget(self.desktop_status)

        spoken = card("Assistant voice", "Piper reads replies locally. Its English voice downloads once on first use.")
        self.spoken_answers_toggle = QCheckBox("Read assistant answers aloud")
        self.spoken_answers_toggle.setChecked(self.settings.value("spoken_assistant_answers", True, type=bool))
        self.spoken_answers_toggle.toggled.connect(lambda value: self.settings.setValue("spoken_assistant_answers", value))
        spoken.addWidget(self.spoken_answers_toggle)
        voice_row = QHBoxLayout()
        voice_row.addWidget(QLabel("Voice"))
        self.piper_voice_choice = DashboardComboBox()
        for identity, details in VOICE_CATALOG.items():
            self.piper_voice_choice.addItem(details["label"], identity)
        self.piper_voice_choice.setCurrentIndex(max(0, self.piper_voice_choice.findData(self.settings.value("piper_voice", VOICE))))
        self.piper_voice_choice.setAccessibleName("Piper voice")
        voice_row.addWidget(self.piper_voice_choice, 1)
        self.preview_voice_button = QPushButton("Preview voice")
        voice_row.addWidget(self.preview_voice_button)
        spoken.addLayout(voice_row)
        speed_row = QHBoxLayout()
        speed_row.addWidget(QLabel("Speaking speed"))
        self.piper_speed_choice = DashboardComboBox()
        for value in (0.75, 0.9, 1.0, 1.1, 1.25, 1.5):
            self.piper_speed_choice.addItem(f"{value:g}×" + (" · Normal" if value == 1 else ""), value)
        try:
            saved_speed = float(self.settings.value("piper_speed", 1.0))
        except (TypeError, ValueError):
            saved_speed = 1.0
        speed_index = self.piper_speed_choice.findData(saved_speed)
        self.piper_speed_choice.setCurrentIndex(speed_index if speed_index >= 0 else self.piper_speed_choice.findData(1.0))
        self.piper_speed_choice.setAccessibleName("Piper speaking speed")
        speed_row.addWidget(self.piper_speed_choice)
        speed_row.addStretch()
        spoken.addLayout(speed_row)
        self.translation_voice_toggle = QCheckBox("Use a matching voice for supported translations")
        self.translation_voice_toggle.setChecked(self.settings.value("translation_voice", True, type=bool))
        self.translation_voice_toggle.toggled.connect(lambda value: self.settings.setValue("translation_voice", value))
        spoken.addWidget(self.translation_voice_toggle)
        self.conversation_memory_toggle = QCheckBox("Remember recent conversation for 10 minutes")
        self.conversation_memory_toggle.setChecked(self.settings.value("conversation_memory", True, type=bool))
        self.conversation_memory_toggle.toggled.connect(lambda value: self.settings.setValue("conversation_memory", value))
        spoken.addWidget(self.conversation_memory_toggle)
        self.clear_conversation_button = QPushButton("Clear conversation")
        spoken.addWidget(self.clear_conversation_button, 0, Qt.AlignmentFlag.AlignLeft)

        account_usage = card("ChatGPT account", "Current plan limits are managed by ChatGPT.")
        self.account_five_hour_usage = QLabel("5-hour · Not connected")
        self.account_weekly_usage = QLabel("Weekly · Not connected")
        account_usage.addWidget(self.account_five_hour_usage)
        account_usage.addWidget(self.account_weekly_usage)
        account_link = QLabel('<a href="https://chatgpt.com/settings/usage">View account limits in ChatGPT ↗</a>')
        account_link.setOpenExternalLinks(True)
        account_usage.addWidget(account_link)

        privacy = card("Local history", "Keep up to 500 dictations on this computer. Meeting notes are saved separately in Notetaker.")
        self.save_history_toggle = QCheckBox("Save new dictations to history")
        self.save_history_toggle.setChecked(self.settings.value("save_history", True, type=bool))
        self.save_history_toggle.toggled.connect(lambda value: self.settings.setValue("save_history", value))
        privacy.addWidget(self.save_history_toggle)
        clear = QPushButton("Clear dictation history")
        clear.setObjectName("danger")
        clear.clicked.connect(self.clear_history)
        privacy.addWidget(clear, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addStretch()
        return page

    def refresh_microphones(self):
        saved = self.settings.value("microphone", "")
        self.mic_choice.blockSignals(True)
        self.mic_choice.clear()
        self.mic_choice.addItem("System default", None)
        try:
            for device, name in input_devices():
                self.mic_choice.addItem(name, device)
            index = self.mic_choice.findText(saved) if saved else 0
            if index < 0:
                self.mic_choice.addItem(saved, "missing")
                index = self.mic_choice.count() - 1
                self.mic_status.setText("Your saved microphone is unavailable. Reconnect it or choose another input.")
            else:
                self.mic_status.setText("The meter lights up while testing or recording.")
            self.mic_choice.setCurrentIndex(index)
        except Exception as exc:
            if saved:
                self.mic_choice.addItem(saved, "missing")
                self.mic_choice.setCurrentIndex(1)
            self.mic_status.setText(f"Could not list microphones: {exc}")
        finally:
            self.mic_choice.blockSignals(False)

    def selected_microphone(self):
        device = self.mic_choice.currentData()
        if device == "missing":
            raise RuntimeError("Your selected microphone is unavailable. Choose another input in Settings.")
        return device

    def change_autostart(self, enabled):
        try:
            startup.set_enabled(enabled)
            self.desktop_status.setText("Neyra will start at login." if enabled else "Login startup is off.")
        except (OSError, RuntimeError) as exc:
            self.autostart_toggle.blockSignals(True)
            self.autostart_toggle.setChecked(not enabled)
            self.autostart_toggle.blockSignals(False)
            self.desktop_status.setText(f"Could not change login startup: {exc}")

    @Slot(str, str, str, int)
    def set_model_status(self, model, state, detail, percent=-1):
        self.model_states[model] = (state, detail, percent)
        if self.engine_choice.currentData() == model:
            self.refresh_model_status()

    def refresh_model_status(self, *_):
        model = self.engine_choice.currentData()
        state, detail, percent = self.model_states[model]
        self.capture.set_model_status(model, state, detail, percent)
        self.model_status_label.setText(detail)
        self.retry_model_button.setEnabled(state not in ("loading", "downloading", "transcribing", "ready"))

    def set_capture_busy(self, busy):
        self.capture_busy = busy
        self.shortcut_panel.set_busy(busy)
        self.data_panel.set_busy(busy)
        self.export_notes_button.setEnabled(not busy)
        for control in (self.mic_choice, self.refresh_mics_button, self.test_mic_button, self.engine_choice):
            control.setEnabled(not busy)
        if busy:
            self.retry_model_button.setEnabled(False)
        else:
            self.refresh_model_status()

    def closeEvent(self, event):
        self.closed.emit()
        super().closeEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    def show_page(self, index):
        self.pages.setCurrentIndex(index)
        self.heading.setVisible(index != 1)
        self.heading.setText(("Notes", "Meeting notes", "Analytics", "Dictionary", "Snippets", "Formatting", "Voice settings", "Reminders", "Assistant", "Home", "Shortcuts", "Data & backup")[index])
        group = 0 if index in (0, 1) else 6 if index in (3, 4, 5, 6, 10, 11) else index
        for i, button in self.nav_buttons.items():
            button.setChecked(i == group)
        self.context_nav.setVisible(group in (0, 6))
        self.export_notes_button.setVisible(group == 0)
        for page, button in self.context_buttons.items():
            button.setVisible((page in (0, 1)) if group == 0 else page in (3, 4, 5, 6, 10, 11))
            button.setChecked(page == index)
        if index == 9:
            self.refresh_home()
        elif index == 2:
            self.refresh_analytics()

    def open_note_question(self):
        self.show_page(8)
        self.assistant_panel.tabs.setCurrentIndex(2)
        self.assistant_panel.question.setFocus()

    def speak_home_reminder(self):
        self.show_page(7)
        self.reminders.speak_requested.emit()

    def start_home_meeting(self):
        self.show_page(1)
        self.notetaker_start.emit()

    def refresh_home(self, reminders=None):
        if reminders is not None:
            self.home_reminders = list(reminders)
        self.home.refresh(self.records, self.meeting_records, self.home_reminders)

    def set_shortcut_hints(self, bindings):
        self.shortcuts = dict(bindings)
        label = lambda action: shortcut_label(bindings, action)
        self.dictation_key_hint.setText(f"Dictate · Hold {label('dictation')}")
        self.assistant_key_hint.setText(f"Assistant · Hold {label('assistant')}")
        self.capture.shortcut_hint = "Record here, or dictate into another app."
        if self.capture.session_state == "idle":
            self.capture.detail.setText(self.capture.shortcut_hint)
        self.items.refresh(self.records)
        self.reminders.shortcut_hint.setText('Say "remind me in an hour to take out the garbage", or type it below.')
        self.assistant_panel.command_hint.setText('Speak naturally with local Needle 3 tools. Try "summarize selected text" or "daily briefing".')
        self.assistant_panel.selection_hint.setText('Ask the assistant to explain, summarize, or translate selected text. You can also paste below.')

    def export_notes_file(self):
        if self.capture_busy:
            return
        path, selected = QFileDialog.getSaveFileName(self, "Export notes", "Neyra-notes.md", "Markdown (*.md);;Plain text (*.txt)")
        if not path:
            return
        from .data_transfer import export_notes, write_text_atomic
        target = Path(path)
        if not target.suffix:
            target = target.with_suffix(".txt" if "*.txt" in selected else ".md")
        try:
            if target.suffix.lower() not in (".md", ".txt"):
                raise ValueError("Choose a .md or .txt file.")
            write_text_atomic(target, export_notes(self.records, self.meeting_records, markdown=target.suffix.lower() == ".md"))
            self.data_panel.status.setText(f"Notes exported to {target}")
            self.status_label.setText(f"Notes exported: {target.name}")
        except (OSError, ValueError) as exc:
            self.data_panel.status.setText(f"Export failed: {exc}")
            self.status_label.setText("Notes could not be exported. See Data & backup.")

    def backup_file(self):
        if self.capture_busy:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Create backup", "Neyra-backup.json", "Neyra backup (*.json)")
        if not path:
            return
        from .data_transfer import create_backup, write_text_atomic
        if not path.lower().endswith(".json"):
            path += ".json"
        try:
            write_text_atomic(path, json.dumps(create_backup(self.settings), ensure_ascii=False, allow_nan=False, indent=2) + "\n")
            self.data_panel.status.setText(f"Backup saved to {path}")
        except (OSError, ValueError) as exc:
            self.data_panel.status.setText(f"Backup failed: {exc}")

    def restore_file(self):
        if self.capture_busy:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Restore backup", "", "Neyra backup (*.json)")
        if not path:
            return
        from .data_transfer import validate_backup
        try:
            with open(path, "rb") as backup:
                raw = backup.read(64 * 1024 * 1024 + 1)
            if len(raw) > 64 * 1024 * 1024:
                raise ValueError("Choose a backup smaller than 64 MiB.")
            payload = json.loads(raw.decode("utf-8"))
            validate_backup(payload)
            data = payload["data"]
            message = (f'Replace local data with {len(data["history"])} dictations, '
                       f'{len(data["meetings"])} meeting notes, {len(data["reminders"])} reminders, '
                       'vocabulary, agenda, and portable settings?\n\n'
                       'This replaces the included data and settings. Create a backup first if you want to keep them. '
                       'Neyra will quit after restoration. Reopen it to use the restored data.')
            if QMessageBox.question(self, "Replace data from backup?", message,
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                    QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
                self.restore_data_requested.emit(payload)
        except (OSError, ValueError, UnicodeError) as exc:
            self.data_panel.status.setText(f"Restore failed: {exc}")

    def toggle_maximized(self):
        self.showNormal() if self.isMaximized() else self.showMaximized()

    def resizeEvent(self, event):
        super().resizeEvent(event)

    def search_history(self, text):
        self.feed_date.setVisible(not text.strip())
        self.items.refresh(query=text)

    def begin_window_drag(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.windowHandle():
            self.windowHandle().startSystemMove()

    def show_help(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Using Neyra")
        dialog.setWindowIcon(app_icon())
        dialog.setStyleSheet(self.styleSheet())
        dialog.resize(560, 620)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(16)
        heading = QLabel("Make room for your voice")
        heading.setObjectName("heading")
        heading.setWordWrap(True)
        layout.addWidget(heading)
        intro = QLabel("Your shortcuts, notes, and reminders in one place.")
        intro.setObjectName("muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        body = QVBoxLayout(content)
        body.setContentsMargins(0, 0, 8, 0)
        body.setSpacing(16)
        card = QFrame()
        card.setObjectName("settingsCard")
        shortcuts = QVBoxLayout(card)
        shortcuts.setContentsMargins(18, 16, 18, 16)
        shortcuts.setSpacing(14)
        for action, title, detail in (
            ("dictation", "Dictate anywhere", "Hold to speak, then release to paste."),
            ("assistant", "Ask your assistant", "Hold to speak an assistant command."),
        ):
            row = QHBoxLayout()
            text = QVBoxLayout()
            name = QLabel(title)
            name.setStyleSheet("font-weight: 600;")
            text.addWidget(name)
            hint = QLabel(detail)
            hint.setObjectName("muted")
            hint.setWordWrap(True)
            text.addWidget(hint)
            row.addLayout(text, 1)
            key = QLabel(shortcut_label(self.shortcuts, action))
            key.setStyleSheet("background: #dee2ed; color: #263256; border-radius: 6px; padding: 6px 9px; font-size: 12px;")
            row.addWidget(key)
            shortcuts.addLayout(row)
        body.addWidget(card)
        for title, detail in (
            ("Make it yours", "Change key combinations in Voice settings → Shortcuts. Snooze or complete tasks in Reminders → Actions."),
            ("Keep your words", "Export from Notes. Create or restore a backup in Voice settings → Data."),
            ("Stay connected", "Keep Neyra running in the tray for on-time notifications. Only text you choose to send is shared with ChatGPT."),
        ):
            name = QLabel(title)
            name.setObjectName("sectionTitle")
            body.addWidget(name)
            hint = QLabel(detail)
            hint.setObjectName("muted")
            hint.setWordWrap(True)
            body.addWidget(hint)
        body.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        footer = QHBoxLayout()
        footer.addStretch()
        done = QPushButton("Got it")
        done.setObjectName("primary")
        done.setDefault(True)
        done.clicked.connect(dialog.accept)
        footer.addWidget(done)
        layout.addLayout(footer)
        dialog.exec()

    def toggle_search(self):
        self.search_input.setVisible(not self.search_input.isVisible())
        if self.search_input.isVisible():
            self.search_input.setFocus()
        else:
            self.search_input.clear()

    def delete_transcript(self, record):
        index = next((i for i, item in enumerate(self.records) if item is record), None)
        if index is None:
            return
        self.records.pop(index)
        self.settings.setValue("history", json.dumps(self.records))
        self.items.refresh(self.records)
        self.refresh_notes_state()
        self.transcript_deleted.emit(record)

    def clear_history(self):
        if not self.records:
            return
        answer = QMessageBox.question(self, "Clear dictation history?",
                                      "Delete all saved dictations from this computer? Meeting notes and your system clipboard are unchanged.",
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                      QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.records.clear()
        self.settings.setValue("history", "[]")
        self.items.refresh(self.records)
        self.refresh_notes_state()
        self.history_cleared.emit()

    def add_transcript(self, text, duration=0):
        if not self.save_history_toggle.isChecked():
            return
        record = {"text": text, "time": datetime.now().isoformat(timespec="seconds"), "duration": max(0, duration)}
        self.records.append(record)
        self.records = self.records[-500:]
        self.settings.setValue("history", json.dumps(self.records))
        self.items.refresh(self.records)
        self.refresh_notes_state()
        return record

    def save_meeting_options(self):
        for key, value in self.notetaker.processing_options().items():
            self.settings.setValue(f"meeting_{key}", value)

    def save_meetings(self):
        self.settings.setValue("meetings", json.dumps(self.meeting_records))
        self.refresh_home()

    def add_meeting(self, text, metadata=None):
        record = dict(metadata or {})
        record.update(text=text, time=datetime.now().isoformat(timespec="seconds"))
        self.meeting_records.append(record)
        self.meeting_records = self.meeting_records[-100:]
        self.settings.setValue("meetings", json.dumps(self.meeting_records))
        self.notetaker.records = self.meeting_records
        self.notetaker.refresh()
        self.refresh_home()

    def delete_meeting(self, record):
        self.meeting_records.remove(record)
        self.settings.setValue("meetings", json.dumps(self.meeting_records))
        self.notetaker.refresh()
        self.refresh_home()

    def set_meeting_state(self, state, message=None):
        self.notetaker.set_state(state, message)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        from .themes import color
        painter.setPen(QPen(QColor(color("#dde0e7")), 1))
        painter.setBrush(QColor(color("#f5f6f9")))
        radius = 0 if self.isMaximized() else 10
        painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), radius, radius)

    def refresh_analytics(self):
        self.analytics_panel.refresh(self.records, self.meeting_records, self.analytics_usage)

    def refresh_notes_state(self):
        date = datetime.fromisoformat(self.records[-1]["time"]) if self.records else datetime.now()
        self.feed_date.setText(date.strftime("%B %d, %Y").upper())
        self.clear_history_button.setEnabled(bool(self.records))
        self.refresh_analytics()
        self.refresh_home()

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

    def vocabulary_corrections(self):
        return {key: value for key, value in load_setting(self.settings, "vocabulary_corrections", dict, {}).items()
                if isinstance(key, str) and key.strip() and isinstance(value, str) and value.strip()}

    def refresh_corrections(self):
        self.corrections_table.setRowCount(0)
        for heard, written in self.vocabulary_corrections().items():
            row = self.corrections_table.rowCount()
            self.corrections_table.insertRow(row)
            self.corrections_table.setItem(row, 0, QTableWidgetItem(heard))
            self.corrections_table.setItem(row, 1, QTableWidgetItem(written))

    def select_correction(self):
        row = self.corrections_table.currentRow()
        if row >= 0 and self.corrections_table.item(row, 1):
            self.correction_heard.setText(self.corrections_table.item(row, 0).text())
            self.correction_written.setText(self.corrections_table.item(row, 1).text())

    def save_correction(self):
        heard, written = self.correction_heard.text().strip(), self.correction_written.text().strip()
        if not heard or not written:
            return
        corrections = {key: value for key, value in self.vocabulary_corrections().items() if key.casefold() != heard.casefold()}
        corrections[heard] = written
        self.settings.setValue("vocabulary_corrections", json.dumps(corrections))
        self.refresh_corrections()
        self.correction_heard.clear()
        self.correction_written.clear()

    def remove_correction(self):
        row = self.corrections_table.currentRow()
        if row >= 0:
            corrections = self.vocabulary_corrections()
            corrections.pop(self.corrections_table.item(row, 0).text(), None)
            self.settings.setValue("vocabulary_corrections", json.dumps(corrections))
            self.refresh_corrections()
            self.correction_heard.clear()
            self.correction_written.clear()

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
    speaker_mute_error = Signal(str)

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.closing = False
        self.recording_duration = 0
        self.recording_started = 0
        self._pending_paste = ""
        self._paste_on_complete = True
        self.mic_test = None
        self.reminder_command_time = None
        self.notification_alerts = []
        self._reminders_in_flight = set()
        self.feedback_timer = QTimer(self)
        self.feedback_timer.setSingleShot(True)
        self.feedback_timer.timeout.connect(self.overlay_feedback_finished)
        self.paste_timer = QTimer(self)
        self.paste_timer.setInterval(50)
        self.paste_timer.timeout.connect(self.paste_when_released)
        self.overlay = Overlay()
        self.overlay.cancel_requested.connect(self.cancel_assistant)
        self.assistant_overlay_timer = QTimer(self)
        self.assistant_overlay_timer.setSingleShot(True)
        self.assistant_overlay_timer.timeout.connect(self.hide_assistant_overlay)
        self._discard_assistant_transcript = False
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
        self.speaker_mute = SpeakerMute(on_error=self.speaker_mute_error.emit)
        self.speaker_mute_error.connect(lambda message: self.history.desktop_status.setText(message))
        self.history.mute_while_speaking_toggle.toggled.connect(self.change_recording_mute)
        self.reminder_store = ReminderStore(self.history.settings)
        self.history.reminders.refresh(self.reminder_store.records)
        self.history.reminders.speak_requested.connect(self.toggle_reminder)
        self.history.reminders.command_submitted.connect(self.submit_reminder)
        self.history.reminders.remove_requested.connect(self.remove_reminder)
        self.history.reminders.snooze_requested.connect(self.snooze_reminder)
        self.history.reminders.done_requested.connect(self.complete_reminder)
        self.history.restore_data_requested.connect(self.restore_data)
        self.reminder_timer = QTimer(self)
        self.reminder_timer.setInterval(1000)
        self.reminder_timer.timeout.connect(self.check_reminders)
        self.engine.model_status.connect(self.history.set_model_status)
        self.history.capture.toggle_requested.connect(self.toggle_capture)
        self.history.test_mic_button.clicked.connect(self.toggle_microphone_test)
        self.history.refresh_mics_button.clicked.connect(self.refresh_microphones)
        self.history.mic_choice.currentIndexChanged.connect(self.stop_microphone_test)
        self.history.pages.currentChanged.connect(self.stop_microphone_test)
        self.history.retry_model_button.clicked.connect(self.prepare_selected_engine)
        self.history.closed.connect(self.dashboard_closed)
        self.history.history_cleared.connect(self.clear_last_transcript)
        self.history.transcript_deleted.connect(self.transcript_deleted)
        self._last_record = self.history.records[-1] if self.history.records else None
        self.last_text = self._last_record["text"] if self._last_record else ""
        self.app.aboutToQuit.connect(self.cleanup)
        self.history.notetaker_start.connect(self.start_notetaker)
        self.history.notetaker_stop.connect(self.stop_notetaker)
        self.history.notetaker.retry_requested.connect(self.process_meeting)
        self.history.notetaker.discard_requested.connect(self.discard_meeting)
        self.assistant_features = AssistantFeatures(self)
        self.assistant_features.voice_state.connect(self.set_assistant_voice_state)
        self.history.notetaker.followups_requested.connect(self.assistant_features.show_followups)
        self.tray = QSystemTrayIcon(app_icon(), app)
        menu = self.tray_menu = QMenu()
        self.tray_status = menu.addAction("Ready to dictate")
        self.tray_status.setEnabled(False)
        menu.addSeparator()
        for title, action in [("Start dictation", self.toggle), ("Speak a reminder", self.toggle_reminder), ("Speak a command", self.toggle_assistant), ("Assistant", self.assistant_features.show), ("Reminders", self.show_reminders), ("Stop Notetaker", self.stop_notetaker), ("Open Neyra", self.show_history), ("Copy last transcript", self.copy_last), ("Settings", self.show_settings), ("Quit Neyra", self.quit)]:
            item = QAction(title, menu)
            item.triggered.connect(action)
            menu.addAction(item)
            if title == "Start dictation":
                self.record_action = item
            elif title == "Stop Notetaker":
                self.meeting_action = item
            elif title == "Copy last transcript":
                self.copy_action = item
            elif title == "Speak a reminder":
                self.reminder_action = item
            elif title == "Speak a command":
                self.assistant_action = item
        self.tray.setContextMenu(menu)
        self.tray.setToolTip("Neyra")
        self.tray.activated.connect(self.tray_activated)
        self.tray.messageClicked.connect(self.show_reminders)
        self.tray.show()
        tray_available = QSystemTrayIcon.isSystemTrayAvailable()
        self.history.close_to_tray_toggle.setEnabled(tray_available)
        if not tray_available:
            self.history.desktop_status.setText("This desktop has no system tray. Closing the dashboard will quit Neyra.")
        self.history.engine_choice.currentIndexChanged.connect(self.prepare_selected_engine)
        self.hotkeys = None
        self.hotkeys_available = False
        self.overlay.text = f"Hold {shortcut_label(self.history.shortcuts, 'dictation')} to dictate"
        if not is_wayland():
            try:
                from .hotkeys import Hotkeys
                self.hotkeys = Hotkeys(self.history.shortcuts)
                self.hotkeys.hold_start.connect(self.start)
                self.hotkeys.hold_stop.connect(self.stop_dictation)
                self.hotkeys.toggle.connect(self.toggle)
                self.hotkeys.reminder_start.connect(self.start_reminder)
                self.hotkeys.reminder_stop.connect(self.stop_reminder)
                self.hotkeys.assistant_start.connect(self.start_assistant)
                self.hotkeys.assistant_stop.connect(self.stop_assistant)
                self.hotkeys.selection_requested.connect(self.assistant_features.capture_selection)
                self.hotkeys.start()
                self.hotkeys_available = True
            except Exception as exc:
                self.overlay.text = f"Hotkeys unavailable: {exc}. Use tray menu."
        else:
            self.overlay.text = "Wayland: use tray menu; compositor shortcuts can be configured externally"
        self.history.shortcut_panel.apply_requested.connect(self.apply_shortcut_settings)
        self.prepare_selected_engine()
        self.update_controls()
        self.reminder_timer.start()
        QTimer.singleShot(0, self.check_reminders)

    def prepare_selected_engine(self, *_):
        if self.history.engine_choice.currentData() == "whistle":
            self.engine.prepare_whistle()
        else:
            self.engine.prepare_voz()

    def apply_shortcut_settings(self, bindings):
        if self.closing:
            return
        settings = self.history.settings
        existed = settings.contains("shortcuts")
        saved = settings.value("shortcuts")
        writing = False
        def persist(canonical):
            nonlocal writing
            writing = True
            settings.setValue("shortcuts", json.dumps(canonical))
            settings.sync()
            if settings.status() != QSettings.Status.NoError:
                raise OSError("Settings could not be saved. Check file access and disk space.")
        try:
            if self.recording or self.processing or self.notetaker_active:
                raise ValueError("Finish the current recording before changing shortcuts.")
            canonical = validate_bindings(bindings)
            if self.hotkeys:
                self.hotkeys.set_bindings(canonical, persist=lambda: persist(canonical))
            else:
                persist(canonical)
            self.history.set_shortcut_hints(canonical)
            for action, value in canonical.items():
                self.history.shortcut_panel.fields[action].setText(value)
            message = ("Shortcuts saved and applied." if self.hotkeys_available else
                       "Shortcuts saved. Global shortcuts are unavailable in this session; use the app controls.")
            self.history.shortcut_panel.status.setText(message)
            if self.overlay.state == "Ready" and not is_wayland():
                self.overlay.text = f"Hold {shortcut_label(canonical, 'dictation')} to dictate"
        except (ValueError, OSError) as exc:
            if writing:
                try:
                    settings.setValue("shortcuts", saved) if existed else settings.remove("shortcuts")
                    settings.sync()
                except OSError:
                    pass
            self.history.shortcut_panel.status.setText(f"Shortcuts not changed: {exc}")

    def restore_data(self, payload):
        if self.closing:
            return
        if (self.recording or self.processing or self.notetaker_active or self._meeting_audio is not None
                or self.assistant_features.job.running):
            self.history.data_panel.status.setText("Finish recordings and assistant requests before restoring a backup.")
            return
        from .data_transfer import restore_backup
        try:
            restore_backup(self.history.settings, payload)
        except (OSError, ValueError, RuntimeError) as exc:
            self.history.data_panel.status.setText(f"Restore failed: {exc}")
            return
        try:
            self.cleanup()
        finally:
            self.quit()

    def create_microphone(self, chunks, level):
        device = self.history.selected_microphone()
        return Microphone(chunks, level) if device is None else Microphone(chunks, level, device=device)

    def toggle_microphone_test(self):
        if self.mic_test:
            self.stop_microphone_test()
            return
        if self.recording or self.notetaker_active or self.processing:
            return
        try:
            self.mic_test = self.create_microphone(None, self.level_changed.emit)
            self.mic_test.start()
            self.history.test_mic_button.setText("Stop microphone test")
            self.history.mic_status.setText("Listening for input. This test does not save audio or create a transcript.")
        except Exception as exc:
            self.stop_microphone_test()
            self.history.mic_status.setText(f"Microphone test failed: {exc}")

    def stop_microphone_test(self, *_):
        microphone, self.mic_test = self.mic_test, None
        self.history.test_mic_button.setText("Test microphone")
        self.history.input_meter.reset()
        self.history.mic_status.setText("The meter lights up while testing or recording.")
        if microphone:
            try:
                microphone.stop()
            except Exception as exc:
                self.history.mic_status.setText(f"Could not close the microphone test: {exc}")

    def refresh_microphones(self):
        self.stop_microphone_test()
        self.history.refresh_microphones()

    def update_controls(self, message=None):
        busy = self.recording or self.processing or self.notetaker_active
        state = "meeting" if self.notetaker_active or (self.processing and self.active_mode == "notetaker") else "recording" if self.recording else "processing" if self.processing else "idle"
        self.history.capture.set_session(state, message)
        reminder_recording = self.recording and self.active_mode == "reminder"
        reminder_busy = (self.recording or self.processing) and self.active_mode == "reminder"
        if reminder_busy:
            self.history.capture.title.setText("Listening for a reminder" if self.recording else "Understanding your reminder")
            self.history.capture.detail.setText(message or ('Say "remind me in an hour to take out the garbage".' if self.recording else "Transcribing your reminder command locally..."))
            if self.recording:
                self.history.capture.record_button.setText("Stop and set reminder")
        self.history.set_capture_busy(busy)
        self.history.reminders.set_capture_state(reminder_recording, busy)
        assistant_recording = self.recording and self.active_mode == "assistant"
        self.history.assistant_panel.set_capture_state(assistant_recording, busy)
        self.assistant_action.setText("Finish command" if assistant_recording else "Speak a command")
        self.assistant_action.setEnabled(assistant_recording or not busy)
        self.record_action.setText("Stop dictation" if self.recording and not reminder_recording else "Start dictation")
        self.record_action.setEnabled(not self.processing and not self.notetaker_active and not reminder_recording and not assistant_recording)
        self.reminder_action.setText("Stop reminder command" if reminder_recording else "Speak a reminder")
        self.reminder_action.setEnabled(reminder_recording or not busy)
        self.meeting_action.setEnabled(self.notetaker_active)
        self.copy_action.setEnabled(bool(self.last_text))
        label = {"idle": "Ready to dictate", "recording": "Recording dictation", "processing": "Transcribing", "meeting": "Notetaker active"}[state]
        if reminder_busy:
            label = "Recording reminder" if self.recording else "Setting reminder"
        if self.active_mode == "assistant" and (self.recording or self.processing):
            label = "Listening for a command" if self.recording else "Transcribing command"
            self.history.capture.title.setText(label)
            self.history.capture.detail.setText(f"Release {shortcut_label(self.history.shortcuts, 'assistant')} when you finish speaking.")
        self.tray_status.setText(label)
        self.tray.setToolTip(f"Neyra · {label}")

    def dashboard_closed(self):
        self.stop_microphone_test()
        if not self.closing and (not QSystemTrayIcon.isSystemTrayAvailable() or not self.history.close_to_tray_toggle.isChecked()):
            self.app.quit()

    def clear_last_transcript(self):
        self._last_record = None
        self.last_text = ""
        self._pending_paste = ""
        self.paste_timer.stop()
        self.copy_action.setEnabled(False)

    def transcript_deleted(self, record):
        if record is self._last_record:
            self.clear_last_transcript()

    def show_settings(self):
        self.history.show_page(6)
        self.show_history()

    def show_reminders(self):
        self.history.show_page(7)
        self.show_history()

    @Slot()
    def start_reminder(self):
        if not self.recording and not self.processing and not self.notetaker_active:
            self.start("reminder")

    @Slot()
    def start_assistant(self):
        self.start("assistant")

    @Slot()
    def stop_assistant(self):
        if self.active_mode == "assistant":
            self.stop()

    @Slot()
    def toggle_assistant(self):
        if self.recording:
            self.stop_assistant()
        else:
            self.start_assistant()

    @Slot()
    def stop_reminder(self):
        if self.active_mode == "reminder":
            self.stop()

    @Slot()
    def stop_dictation(self):
        if self.active_mode == "dictation":
            self.stop()

    def toggle_reminder(self):
        if self.recording and self.active_mode == "reminder":
            self.stop_reminder()
        else:
            self.start_reminder()

    def toggle_capture(self):
        self.stop() if self.recording else self.toggle()

    @Slot(str)
    def submit_reminder(self, command, now=None, spoken=False):
        try:
            record = self.reminder_store.add(command, now=now)
        except (ValueError, OSError) as exc:
            message = f"Reminder not saved. {exc}"
            self.history.reminders.status.setText(message)
            self.history.reminders.command.setText(command)
            if spoken:
                self.history.status_label.setText("Reminder not saved")
                self.show_notification("Reminder not saved", str(exc))
            return False
        self.history.reminders.refresh(self.reminder_store.records)
        self.history.reminders.command.clear()
        message = f"Reminder set for {due_label(record['due_at'])}: {record['text']}"
        self.history.reminders.status.setText(message)
        if spoken:
            self.history.status_label.setText("Reminder set")
            self.history.capture.detail.setText(message[:400])
            self.overlay.state = "Reminder set"
            self.overlay.text = f"{due_label(record['due_at'])} · {record['text']}"
            self.overlay.show()
            self.feedback_timer.start(3500)
        self.check_reminders()
        return True

    def overlay_feedback_finished(self):
        if not self.recording and not self.processing and self.overlay.state == "Reminder set":
            self.overlay.hide()

    @Slot(str)
    def remove_reminder(self, identity):
        if self.reminder_store.remove(identity):
            self._reminders_in_flight.discard(identity)
            self.history.reminders.refresh(self.reminder_store.records)
            self.history.reminders.status.setText("Reminder removed.")

    def snooze_reminder(self, identity, preset):
        try:
            deadline = snooze_deadline(preset)
            if self.reminder_store.snooze(identity, deadline):
                self._reminders_in_flight.discard(identity)
                self.history.reminders.refresh(self.reminder_store.records)
                self.history.reminders.status.setText(f"Snoozed until {due_label(deadline)}.")
        except (ValueError, OSError) as exc:
            self.history.reminders.status.setText(f"Could not snooze reminder: {exc}")

    def complete_reminder(self, identity):
        try:
            if self.reminder_store.complete(identity):
                self._reminders_in_flight.discard(identity)
                self.history.reminders.refresh(self.reminder_store.records)
                self.history.reminders.status.setText("Reminder marked done.")
        except OSError as exc:
            self.history.reminders.status.setText(f"Could not complete reminder: {exc}")

    @Slot()
    def check_reminders(self):
        if self.closing:
            return
        due = [record for record in self.reminder_store.pending_due() if record["id"] not in self._reminders_in_flight]
        if not due:
            return
        self.history.reminders.status.setText(f"{len(due)} reminder{'s are' if len(due) != 1 else ' is'} due. See Recent reminders below.")
        identities = [record["id"] for record in due]
        self._reminders_in_flight.update(identities)
        deadlines = {record["id"]: record["due_at"] for record in due}
        acknowledged = lambda: self.reminder_notification_sent(identities, deadlines)
        if len(due) == 1:
            self.show_notification("Neyra reminder", due[0]["text"] + "\nOpen Reminders to snooze or mark done.", on_shown=acknowledged)
        else:
            message = "\n".join(record["text"][:200] for record in due[:3])
            if len(due) > 3:
                message += "\nOpen Reminders to see all of them."
            self.show_notification(f"Neyra · {len(due)} reminders due", message, on_shown=acknowledged)

    def reminder_notification_sent(self, identities, deadlines=None):
        if self.closing:
            return
        if deadlines is not None:
            identities = [record["id"] for record in self.reminder_store.records
                          if record["id"] in deadlines and record["due_at"] == deadlines[record["id"]]
                          and record["status"] == "pending"]
        self._reminders_in_flight.difference_update(identities)
        self.reminder_store.mark_fired(identities)
        self.history.reminders.refresh(self.reminder_store.records)

    def show_notification(self, title, message, on_shown=None):
        if self.closing:
            return
        if QSystemTrayIcon.isSystemTrayAvailable() and QSystemTrayIcon.supportsMessages():
            self.tray.showMessage(title, message[:1500], QSystemTrayIcon.MessageIcon.Information, 15000)
            if on_shown:
                on_shown()
            return
        notifier = shutil.which("notify-send") if sys.platform.startswith("linux") else None
        if notifier:
            process = QProcess(self)
            timer = QTimer(process)
            timer.setSingleShot(True)
            timer.timeout.connect(process.kill)
            def finished(code, status):
                if code != 0 or status == QProcess.ExitStatus.CrashExit:
                    self.show_reminder_alert(title, message, on_shown)
                elif on_shown:
                    on_shown()
                process.deleteLater()
            def failed(error):
                if error == QProcess.ProcessError.FailedToStart:
                    self.show_reminder_alert(title, message, on_shown)
                    process.deleteLater()
            process.finished.connect(finished)
            process.errorOccurred.connect(failed)
            process.start(notifier, ["--app-name=Neyra", "--", title, message[:1500]])
            timer.start(10000)
        else:
            self.show_reminder_alert(title, message, on_shown)

    def show_reminder_alert(self, title, message, on_shown=None):
        if self.closing:
            return
        alert = ReminderAlert(title, message)
        alert.open_requested.connect(self.show_reminders)
        self.notification_alerts.append(alert)
        alert.finished.connect(lambda _result: self.notification_alerts.remove(alert))
        alert.show()
        if on_shown:
            on_shown()

    @Slot(float)
    def set_level(self, value):
        self.overlay.level = value
        if self.recording or self.notetaker_active or self.mic_test:
            self.history.input_meter.set_level(value)
        if self.recording:
            self.history.capture.meter.set_level(value)

    @Slot(str, str)
    def set_assistant_voice_state(self, state, message):
        if self.closing or self.recording or (self.processing and self.active_mode == "assistant"):
            return
        self.assistant_overlay_timer.stop()
        self.overlay.set_assistant_state(state, message)
        self.overlay.show()
        if state in ("Ready", "Error"):
            self.assistant_overlay_timer.start(5000 if state == "Error" else 1600)

    def hide_assistant_overlay(self):
        if not self.recording and not self.processing and not self.assistant_features.job.running and not self.assistant_features.speech_active:
            self.overlay.hide()

    @Slot()
    def cancel_assistant(self):
        if self.closing:
            return
        self.assistant_overlay_timer.stop()
        self.assistant_features.interrupt_voice()
        if self.active_mode == "assistant" and (self.recording or self.processing):
            self._discard_assistant_transcript = True
            if self.recording:
                self.stop()
        self.overlay.hide()
        self.history.status_label.setText("Assistant cancelled")

    @Slot(bool)
    def change_recording_mute(self, enabled):
        if self.recording and enabled:
            self.speaker_mute.begin()
        elif not enabled:
            self.speaker_mute.end()

    @Slot()
    def start(self, mode="dictation"):
        if self.closing or self.recording or self.notetaker_active:
            return
        if self.processing:
            if mode == "assistant" or self.active_mode == "assistant":
                self.overlay.set_assistant_state("Thinking", "Finishing the previous audio request...")
            else:
                self.overlay.set_plain_mode()
                self.overlay.state = "Transcribing"
            self.overlay.show()
            return
        self._pending_paste = ""
        self.paste_timer.stop()
        self.feedback_timer.stop()
        self.assistant_overlay_timer.stop()
        self.stop_microphone_test()
        if mode == "assistant":
            self.assistant_features.interrupt_voice()
        else:
            self.assistant_features.stop_speech()
        self.active_mode = mode
        self._discard_assistant_transcript = False
        self.overlay.set_plain_mode()
        self.reminder_command_time = None
        self._paste_on_complete = mode == "dictation" and not self.history.isActiveWindow()
        self.overlay.state = "Reminder" if mode == "reminder" else "Listening"
        self.overlay.text = 'Say "remind me in an hour to..."' if mode == "reminder" else "Speak now..."
        if mode == "assistant":
            self.overlay.set_assistant_state("Listening", "Speak naturally. Release the keys when you finish.")
        self.overlay.show()
        chunks = queue.Queue()
        try:
            self.recorder = self.create_microphone(chunks, self.level_changed.emit)
            if self.history.mute_while_speaking_toggle.isChecked():
                self.speaker_mute.begin()
            self.recorder.start()
            self.recording = True
            self.recording_started = time.monotonic()
            self.history.status_label.setText("Listening...")
            self.update_controls()
            hints = self.history.dictionary_words() + list(self.history.vocabulary_corrections().values()) + list(self.history.snippets())
            self.engine.run(chunks, keywords=hints, model=self.history.engine_choice.currentData())
        except Exception as exc:
            self.error(str(exc))

    @Slot()
    def stop(self):
        if not self.recording: return
        self.recording = False
        if self.active_mode in ("reminder", "assistant"):
            self.reminder_command_time = time.time()
        self.recording_duration = time.monotonic() - self.recording_started
        self.processing = True
        self.history.status_label.setText("Transcribing...")
        if self.active_mode == "assistant":
            self.overlay.set_assistant_state("Thinking", "Understanding your speech...")
            self.overlay.show()
        else:
            self.overlay.state = "Transcribing"
            self.overlay.hide()
        self.history.input_meter.reset()
        self.update_controls()
        try:
            self.recorder.stop()
        except Exception as exc:
            self.error(str(exc))
        finally:
            self.speaker_mute.end()

    @Slot()
    def toggle(self):
        if self.recording and self.active_mode != "dictation":
            return
        if self.recording: self.stop()
        else: self.start()

    @Slot(str)
    def preview(self, text):
        if self.closing or self._discard_assistant_transcript:
            return
        self.history.status_label.setText("Listening..." if self.recording else "Processing meeting..." if self.active_mode == "notetaker" else "Transcribing..." if self.processing else "Preparing model...")
        self.history.status_label.setToolTip(text)
        if self.active_mode == "notetaker":
            self.history.notetaker_status.setText(text or "Transcribing meeting audio...")
        else:
            self.overlay.text = text or "Listening..."
            if self.recording or self.processing:
                self.history.capture.detail.setText(text[-400:] or "Listening...")

    @Slot(str)
    def complete(self, text):
        if self.closing:
            return
        self.processing = False
        self.history.input_meter.reset()
        if self._discard_assistant_transcript:
            self._discard_assistant_transcript = False
            self.active_mode = "dictation"
            self.update_controls()
            self.history.status_label.setText("Assistant cancelled")
            return
        if self.active_mode == "assistant":
            self.active_mode = "dictation"
            self.update_controls()
            self.history.status_label.setText("Ready to dictate")
            self.assistant_features.command(text, now=self.reminder_command_time, spoken=True)
            return
        if self.active_mode == "reminder":
            self.active_mode = "dictation"
            self.update_controls()
            self.submit_reminder(text, now=self.reminder_command_time, spoken=True)
            return
        self.update_controls("Your transcript is ready." if text else "No speech detected. Check the microphone meter and try again.")
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
        text = expand_snippets(text, self.history.vocabulary_corrections())
        text = expand_snippets(apply_style(text, self.history.style_choice.currentText()), self.history.snippets())
        self.last_text = text
        self._last_record = None
        self.copy_action.setEnabled(bool(text))
        self.overlay.state = "Ready"
        self.overlay.text = text or "No speech detected"
        if text:
            self._last_record = self.history.add_transcript(text, self.recording_duration)
            QApplication.clipboard().setText(text)
            self.copy_action.setEnabled(True)
            if self._paste_on_complete:
                self._pending_paste = text
                self.paste_timer.start()

    @Slot()
    def paste_when_released(self):
        if self.hotkeys and self.hotkeys.modifiers_active():
            return
        self.paste_timer.stop()
        text, self._pending_paste = self._pending_paste, ""
        if text and not self.closing:
            if self.history.isActiveWindow():
                return
            try:
                insert_text(text)
            except Exception as exc:
                self.error(f"Transcript copied, but paste failed: {exc}")

    def start_notetaker(self):
        if self.closing or self.notetaker_active or self.recording or self.processing or self._meeting_audio is not None:
            return
        try:
            self.stop_microphone_test()
            self.assistant_features.stop_speech()
            bridge_path()
            self.meeting_options = self.history.notetaker.processing_options()
            self._meeting_capture_warnings = []
            self.notetaker_chunks = queue.Queue()
            self.notetaker_mic = self.create_microphone(self.notetaker_chunks, self.level_changed.emit)
            self.system_audio = SystemAudioRecorder()
            self.system_audio.start()
            self.notetaker_mic.start()
            self.notetaker_active = True
            self.update_controls()
            self.history.status_label.setText("Recording meeting...")
            self.history.set_meeting_state("recording", "Recording microphone and computer audio. Stop when your meeting ends.")
        except Exception as exc:
            self.stop_meeting_capture()
            self.update_controls()
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
            self.update_controls()
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
            self.history.input_meter.reset()
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
                self.history.status_label.setText("No meeting audio captured")
                self.update_controls()
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
                self.update_controls()
            else:
                self.process_meeting()
        except Exception as exc:
            self.processing = False
            self.active_mode = "dictation"
            self.update_controls()
            self.history.set_meeting_state("idle", f"Meeting transcription failed: {exc}")

    @Slot(str)
    def error(self, message):
        if self.closing:
            return
        self.speaker_mute.end()
        if self._discard_assistant_transcript:
            self._discard_assistant_transcript = False
            self.processing = False
            self.recording = False
            self.active_mode = "dictation"
            self.update_controls()
            return
        if self.recorder and self.recorder.stream:
            try:
                self.recorder.stop()
            except Exception as exc:
                message += f"; microphone cleanup: {exc}"
        self.processing = False
        self.recording = False
        if self.active_mode == "reminder":
            self.history.reminders.status.setText(f"Reminder not saved. {message}")
            self.active_mode = "dictation"
        elif self.active_mode == "assistant":
            self.history.assistant_panel.status.setText(message)
            self.active_mode = "dictation"
        self.history.input_meter.reset()
        self.update_controls()
        self.history.capture.set_session("error", message)
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
        self.assistant_overlay_timer.stop()
        self.assistant_features.cleanup()
        self.reminder_timer.stop()
        self.feedback_timer.stop()
        for alert in tuple(self.notification_alerts):
            alert.close()
        for process in self.findChildren(QProcess):
            if process.state() != QProcess.ProcessState.NotRunning:
                process.kill()
                process.waitForFinished(1000)
        self.stop_microphone_test()
        self.history.notetaker.timer.stop()
        self.paste_timer.stop()
        if self.recorder:
            try:
                self.recorder.stop()
            except Exception:
                pass
        self.stop_meeting_capture()
        self.speaker_mute.close()
        self._meeting_audio = None
        self.engine.close()
        if self.hotkeys:
            self.hotkeys.stop()
        self.tray.hide()
        self.overlay.hide()
        self.history.hide()

def main():
    app = QApplication(sys.argv)
    app.setWindowIcon(app_icon())
    # Qt adopts the user's process locale on Unix. Keep C numeric formatting
    # locale-independent for JSON emitted by the native Whistle engine.
    locale.setlocale(locale.LC_NUMERIC, "C")
    app.setQuitOnLastWindowClosed(False)
    controller = Assistant(app)
    if "--background" not in sys.argv or not QSystemTrayIcon.isSystemTrayAvailable():
        controller.show_history()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
