"""Shortcut and data preferences. Controllers apply changes and handle files."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QScrollArea, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFrame, QMessageBox,
)
from .shortcuts import DEFAULT_SHORTCUTS, SHORTCUT_LABELS, load_bindings, validate_bindings, shortcut_warnings


def content(page):
    page.setWidgetResizable(True)
    page.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    widget = QWidget()
    page.setWidget(widget)
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(0, 0, 8, 0)
    card = QFrame()
    card.setObjectName("settingsCard")
    layout.addWidget(card)
    layout.addStretch()
    box = QVBoxLayout(card)
    box.setContentsMargins(22, 20, 22, 20)
    box.setSpacing(14)
    return box


def description(text):
    label = QLabel(text)
    label.setWordWrap(True)
    label.setObjectName("muted")
    label.setTextFormat(Qt.TextFormat.PlainText)
    return label


class ShortcutsPanel(QScrollArea):
    apply_requested = Signal(object)

    def __init__(self, settings):
        super().__init__()
        box = content(self)
        box.setContentsMargins(18, 16, 18, 16)
        box.setSpacing(10)
        box.addWidget(description("Type a combination such as Ctrl+Alt+R. Win also accepts Cmd, Meta, or Super. Use a modifier with a letter, digit, Space, or F1–F12. Two modifiers alone are also supported."))
        self.fields = {}
        current = load_bindings(settings)
        for action, title in SHORTCUT_LABELS.items():
            row = QHBoxLayout()
            label = QLabel(title)
            label.setMinimumWidth(170)
            row.addWidget(label)
            field = QLineEdit(current[action])
            field.setFixedHeight(34)
            field.setStyleSheet("padding: 6px 10px;")
            field.setMaxLength(80)
            field.setAccessibleName(title + " shortcut")
            label.setBuddy(field)
            row.addWidget(field, 1)
            self.fields[action] = field
            box.addLayout(row)
        row = QHBoxLayout()
        self.apply = QPushButton("Apply shortcuts")
        self.apply.setObjectName("primary")
        self.apply.clicked.connect(self.request_apply)
        self.defaults = QPushButton("Restore defaults")
        self.defaults.clicked.connect(self.restore_defaults)
        row.addWidget(self.apply)
        row.addWidget(self.defaults)
        row.addStretch()
        box.addLayout(row)
        self.status = description("Neyra checks its own shortcut conflicts and warns about common system combinations. Other apps may still intercept a shortcut. Native Wayland restrictions still apply.")
        box.addWidget(self.status)

    def request_apply(self):
        try:
            bindings = validate_bindings({action: field.text() for action, field in self.fields.items()})
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        warnings = shortcut_warnings(bindings)
        if warnings and QMessageBox.question(self, "Shortcut conflict warning",
                                              "\n".join(warnings) + "\n\nUse these shortcuts anyway?",
                                              QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                              QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        self.apply_requested.emit(bindings)

    def restore_defaults(self):
        for action, value in DEFAULT_SHORTCUTS.items():
            self.fields[action].setText(value)
        self.request_apply()

    def set_busy(self, busy):
        for field in (*self.fields.values(), self.apply, self.defaults):
            field.setEnabled(not busy)


class DataPanel(QScrollArea):
    export_requested = Signal()
    backup_requested = Signal()
    restore_requested = Signal()

    def __init__(self):
        super().__init__()
        box = content(self)
        box.addWidget(description("Export dictations and meeting notes as Markdown or plain text."))
        self.export = QPushButton("Export all notes")
        self.export.setObjectName("primary")
        self.export.clicked.connect(self.export_requested.emit)
        box.addWidget(self.export, 0, Qt.AlignmentFlag.AlignLeft)
        box.addWidget(description("Back up notes, reminders, vocabulary, snippets, agenda, shortcuts, and portable preferences. Backups contain personal text and are not encrypted. Store them somewhere private."))
        self.backup = QPushButton("Create backup")
        self.backup.clicked.connect(self.backup_requested.emit)
        box.addWidget(self.backup, 0, Qt.AlignmentFlag.AlignLeft)
        box.addWidget(description("Restore replaces the included data and settings, then quits Neyra so you can reopen it. Account credentials, custom executable paths, login startup, and device-specific settings are excluded."))
        self.restore = QPushButton("Restore backup…")
        self.restore.setObjectName("danger")
        self.restore.clicked.connect(self.restore_requested.emit)
        box.addWidget(self.restore, 0, Qt.AlignmentFlag.AlignLeft)
        self.status = description("Choose an action above.")
        box.addWidget(self.status)

    def set_busy(self, busy):
        for button in (self.export, self.backup, self.restore):
            button.setEnabled(not busy)


class ProviderPanel(QWidget):
    changed = Signal()

    def __init__(self, settings):
        super().__init__()
        from PySide6.QtWidgets import QComboBox, QFormLayout
        self.settings = settings
        form = QFormLayout(self)
        self.provider = QComboBox()
        for label, value in [('ChatGPT', 'chatgpt'), ('Local model server', 'local'), ('OpenCode API', 'opencode_api'), ('OpenCode CLI', 'opencode_cli'), ('No assistant (local tools only)', 'none')]:
            self.provider.addItem(label, value)
        self.url = QLineEdit()
        self.model = QLineEdit()
        self.executable = QLineEdit(settings.value('opencode_executable', 'opencode'))
        for label, field in [('Provider', self.provider), ('Server URL', self.url), ('Model', self.model), ('OpenCode executable', self.executable)]:
            field.setAccessibleName(label)
            form.addRow(label, field)
        self.note = description('')
        form.addRow(self.note)
        save = QPushButton('Apply provider')
        save.clicked.connect(self.save)
        form.addRow(save)
        self.provider.setCurrentIndex(max(0, self.provider.findData(settings.value('assistant_provider', 'chatgpt'))))
        self.provider.currentIndexChanged.connect(self.load)
        self.load()

    def load(self):
        kind = self.provider.currentData()
        self.url.setText(self.settings.value(kind + '_url', 'http://127.0.0.1:4096' if kind == 'opencode_api' else 'http://127.0.0.1:11434/v1'))
        self.model.setText(self.settings.value(kind + '_model', ''))
        self.url.setEnabled(kind in ('local', 'opencode_api'))
        self.model.setEnabled(kind in ('local', 'opencode_api', 'opencode_cli'))
        self.executable.setEnabled(kind == 'opencode_cli')
        self.note.setText({'local': 'Use an OpenAI-compatible local server, such as Ollama, LM Studio, or llama.cpp. Enter its model name. Optional key: NEYRA_ASSISTANT_API_KEY environment variable.',
                           'opencode_api': 'Start opencode serve. Optional model: provider/model. Authentication uses OPENCODE_SERVER_PASSWORD and OPENCODE_SERVER_USERNAME.',
                           'opencode_cli': 'Uses your installed OpenCode and its signed-in providers. Optional model: provider/model. Desktop actions stay in Neyra.',
                           'none': 'Needle 3 understands local tool requests. Summaries, translations, and general questions need an assistant provider.',
                           'chatgpt': 'Sign in on the Assistant page. Local tool routing uses Needle 3 independently.'}[kind])

    def save(self):
        from .providers import endpoint
        kind = self.provider.currentData()
        try:
            if kind in ('local', 'opencode_api'):
                endpoint(self.url.text().strip())
            if kind == 'local' and not self.model.text().strip():
                raise ValueError('Enter a local model name.')
            if kind.startswith('opencode') and self.model.text().strip() and '/' not in self.model.text():
                raise ValueError('Use provider/model for an OpenCode model.')
            if kind == 'opencode_cli' and not self.executable.text().strip():
                raise ValueError('Enter the OpenCode executable name or path.')
        except ValueError as exc:
            self.note.setText(str(exc))
            return
        self.settings.setValue('assistant_provider', kind)
        self.settings.setValue(kind + '_url', self.url.text().strip())
        self.settings.setValue(kind + '_model', self.model.text().strip())
        self.settings.setValue('opencode_executable', self.executable.text().strip())
        self.changed.emit()
        self.note.setText('Provider saved. It will be used for the next assistant request.')
