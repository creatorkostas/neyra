"""Light and dark dashboard palettes, preserving Neyra's blue actions."""
import re
from PySide6.QtWidgets import QApplication

# Existing light stylesheet colors grouped by their semantic role.
DARK_COLORS = {}
for colors, target in [
    ('#f5f6f9', '#151922'),
    ('#ffffff #fffdf9', '#1b202b'),
    ('#f3f4f7 #f0f2f7 #f6f7f9 #eff0f4', '#232a37'),
    ('#ebecf0 #eeeff2 #ede9e2 #e3e5eb', '#2d3544'),
    ('#dde0e8 #e7e9ee #f1f2f6 #dee2ed #eeeae2 #f0ece4 #dbdfea #ccd2e4', '#364359'),
    ('#ced3e1 #c5cbde', '#43516b'),
    ('#dde0e7 #d3d6e0 #eae6de #eeeae3 #e9eaee #bcc4d9 #dbdee7 #dde0ea', '#46536a'),
    ('#171c2d #1b233c #19223d #19223c #263256 #252323', '#e9edf5'),
    ('#565a6a #686057 #394464 #454c60 #68635d #6c665f #706875', '#bdc8dc'),
    ('#979087 #888078 #646878', '#9aa8bf'),
    ('#d8d3cb #b9b1a6', '#63728b'),
    ('#a23940', '#ffb9bf'), ('#faeaea #f5d9db', '#562e39'),
]:
    DARK_COLORS.update(dict.fromkeys(colors.split(), target))


def current_theme():
    app = QApplication.instance()
    return app.property('neyra_theme') or 'light' if app else 'light'


def color(value):
    return DARK_COLORS.get(value, value) if current_theme() == 'dark' else value


def stylesheet(theme=None):
    from .ui import THEME
    if (theme or current_theme()) != 'dark':
        return THEME
    # Literal white on actions must stay white; white surfaces become elevated.
    source = THEME.replace('background: white;', 'background: #ffffff;')
    return re.sub(r'#[0-9a-fA-F]{6}', lambda m: DARK_COLORS.get(m[0], m[0]), source)


def apply_theme(window, theme):
    theme = 'dark' if theme == 'dark' else 'light'
    QApplication.instance().setProperty('neyra_theme', theme)
    window.setStyleSheet(stylesheet(theme))
    from .ui import icon
    from PySide6.QtWidgets import QPushButton, QLabel
    for widget in window.findChildren(QPushButton):
        name = widget.property('neyra_icon')
        if name:
            widget.setIcon(icon(name))
    for widget in window.findChildren(QLabel):
        original = widget.property('neyra_light_style')
        if original is None:
            original = widget.styleSheet()
            widget.setProperty('neyra_light_style', original)
        widget.setStyleSheet(re.sub(r'#[0-9a-fA-F]{6}', lambda m: color(m[0]), original))
    window.update()
