"""Dual-palette theme system (dark + light) with dynamic QSS generation."""

from __future__ import annotations

from PySide6.QtCore import QSettings

# ---------------------------------------------------------------------------
# Color palettes
# ---------------------------------------------------------------------------

DARK: dict[str, str] = {
    "BG_PRIMARY": "#1C1C1E",
    "BG_SECONDARY": "#2C2C2E",
    "BG_TERTIARY": "#3A3A3C",
    "TEXT_PRIMARY": "#FFFFFF",
    "TEXT_SECONDARY": "#8E8E93",
    "ACCENT_BLUE": "#0A84FF",
    "ACCENT_GREEN": "#30D158",
    "ACCENT_RED": "#FF453A",
    "BUBBLE_USER_BG": "#0A84FF",
    "BUBBLE_USER_TEXT": "#FFFFFF",
    "BUBBLE_AI_BG": "#2C2C2E",
    "BUBBLE_AI_TEXT": "#FFFFFF",
    "BUBBLE_OTHER_BG": "#3A3A3C",
    "SPEAKER_LABEL": "#8E8E93",
    "CODE_BG": "#1A1A1C",
    "SEPARATOR": "#2C2C2E",
}

LIGHT: dict[str, str] = {
    "BG_PRIMARY": "#FFFFFF",
    "BG_SECONDARY": "#F2F2F7",
    "BG_TERTIARY": "#E5E5EA",
    "TEXT_PRIMARY": "#000000",
    "TEXT_SECONDARY": "#6C6C70",
    "ACCENT_BLUE": "#007AFF",
    "ACCENT_GREEN": "#34C759",
    "ACCENT_RED": "#FF3B30",
    "BUBBLE_USER_BG": "#007AFF",
    "BUBBLE_USER_TEXT": "#FFFFFF",
    "BUBBLE_AI_BG": "#E5E5EA",
    "BUBBLE_AI_TEXT": "#000000",
    "BUBBLE_OTHER_BG": "#D1D1D6",
    "SPEAKER_LABEL": "#6C6C70",
    "CODE_BG": "#D8D8DD",
    "SEPARATOR": "#D1D1D6",
}

_PALETTES = {"dark": DARK, "light": LIGHT}


def get_colors(theme: str = "dark") -> dict[str, str]:
    """Return the palette dict for *theme* ('dark' or 'light')."""
    return _PALETTES.get(theme, DARK)


def colors() -> dict[str, str]:
    """Shortcut: return the palette for the currently persisted theme."""
    qs = QSettings()
    theme = str(qs.value("room/theme", "dark"))
    return get_colors(theme)


# ---------------------------------------------------------------------------
# Stylesheet generator
# ---------------------------------------------------------------------------


def get_stylesheet(theme: str = "dark") -> str:
    """Generate the full application QSS for *theme*."""
    c = get_colors(theme)

    # Derive hover/pressed shades for buttons
    if theme == "light":
        btn_pressed = "#C7C7CC"
        start_hover = "#2DB84E"
        start_pressed = "#28A745"
        stop_hover = "#E0352B"
        stop_pressed = "#C42E25"
        mute_hover_border = "#C7C7CC"
    else:
        btn_pressed = "#48484A"
        start_hover = "#28c04e"
        start_pressed = "#22a843"
        stop_hover = "#e03e34"
        stop_pressed = "#c4352c"
        mute_hover_border = "#48484A"

    # Light mode needs visible borders on buttons
    btn_border = f"border: 1px solid {c['SEPARATOR']};" if theme == "light" else "border: none;"

    return f"""
/* ── Global ── */
QMainWindow, QWidget {{
    background-color: {c["BG_PRIMARY"]};
    color: {c["TEXT_PRIMARY"]};
    font-family: -apple-system, "SF Pro Text", "Helvetica Neue",
                 "Segoe UI", sans-serif;
    font-size: 14px;
}}

/* ── Scroll area ── */
QScrollArea {{
    border: none;
    background: transparent;
}}
QScrollArea > QWidget > QWidget {{
    background: transparent;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 6px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {c["BG_TERTIARY"]};
    border-radius: 3px;
    min-height: 30px;
}}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {{
    height: 0; background: none;
}}

/* ── Generic buttons ── */
QPushButton {{
    background-color: {c["BG_SECONDARY"]};
    color: {c["TEXT_PRIMARY"]};
    {btn_border}
    border-radius: 10px;
    padding: 8px 18px;
    font-size: 14px;
    font-weight: 500;
}}
QPushButton:hover {{
    background-color: {c["BG_TERTIARY"]};
}}
QPushButton:pressed {{
    background-color: {btn_pressed};
}}

/* ── Start button (green pill) ── */
QPushButton#startButton {{
    background-color: {c["ACCENT_GREEN"]};
    color: #000000;
    font-size: 15px;
    font-weight: 600;
    padding: 12px 28px;
    border-radius: 24px;
}}
QPushButton#startButton:hover {{
    background-color: {start_hover};
}}
QPushButton#startButton:pressed {{
    background-color: {start_pressed};
}}

/* ── Stop / End button (red pill) ── */
QPushButton#stopButton {{
    background-color: {c["ACCENT_RED"]};
    color: #FFFFFF;
    font-size: 15px;
    font-weight: 600;
    padding: 12px 28px;
    border-radius: 24px;
}}
QPushButton#stopButton:hover {{
    background-color: {stop_hover};
}}
QPushButton#stopButton:pressed {{
    background-color: {stop_pressed};
}}

/* ── Mic mute button (circle) ── */
QPushButton#muteButton {{
    background-color: {c["BG_SECONDARY"]};
    border: 1px solid {c["SEPARATOR"]};
    border-radius: 22px;
    padding: 0px;
}}
QPushButton#muteButton:hover {{
    background-color: {c["BG_TERTIARY"]};
    border-color: {mute_hover_border};
}}
QPushButton#muteButton[muted="true"] {{
    background-color: rgba(255, 69, 58, 0.2);
    border-color: {c["ACCENT_RED"]};
}}

/* ── Gear / settings button ── */
QPushButton#gearButton {{
    background-color: transparent;
    border: none;
    border-radius: 18px;
    padding: 0px;
}}
QPushButton#gearButton:hover {{
    background-color: {c["BG_SECONDARY"]};
}}

/* ── Labels ── */
QLabel#titleLabel {{
    font-size: 16px;
    font-weight: 600;
    color: {c["TEXT_PRIMARY"]};
    background: transparent;
}}
QLabel#statusLabel {{
    font-size: 11px;
    color: {c["TEXT_SECONDARY"]};
    background: transparent;
}}

/* ── Settings dialog ── */
QDialog {{
    background-color: {c["BG_PRIMARY"]};
}}
QLineEdit, QTextEdit, QComboBox {{
    background-color: {c["BG_SECONDARY"]};
    color: {c["TEXT_PRIMARY"]};
    border: 1px solid {c["BG_TERTIARY"]};
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 14px;
    selection-background-color: {c["ACCENT_BLUE"]};
}}
QLineEdit:focus, QTextEdit:focus, QComboBox:focus {{
    border: 1px solid {c["ACCENT_BLUE"]};
}}
QScrollBar:horizontal {{
    height: 0;
    background: none;
}}
QComboBox::drop-down {{
    border: none;
    width: 24px;
}}
QComboBox::down-arrow {{
    image: none;
}}
QComboBox QAbstractItemView {{
    background-color: {c["BG_SECONDARY"]};
    color: {c["TEXT_PRIMARY"]};
    selection-background-color: {c["ACCENT_BLUE"]};
    border: 1px solid {c["BG_TERTIARY"]};
    border-radius: 8px;
}}
QCheckBox {{
    color: {c["TEXT_PRIMARY"]};
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 2px solid {c["BG_TERTIARY"]};
    background: {c["BG_SECONDARY"]};
}}
QCheckBox::indicator:checked {{
    background: {c["ACCENT_BLUE"]};
    border-color: {c["ACCENT_BLUE"]};
}}
"""


# ---------------------------------------------------------------------------
# Backward-compat: module-level constants (dark palette) so existing imports
# like `from roomkit_ui.theme import STYLESHEET` keep working during migration.
# ---------------------------------------------------------------------------

BG_PRIMARY = DARK["BG_PRIMARY"]
BG_SECONDARY = DARK["BG_SECONDARY"]
BG_TERTIARY = DARK["BG_TERTIARY"]
TEXT_PRIMARY = DARK["TEXT_PRIMARY"]
TEXT_SECONDARY = DARK["TEXT_SECONDARY"]
ACCENT_BLUE = DARK["ACCENT_BLUE"]
ACCENT_GREEN = DARK["ACCENT_GREEN"]
ACCENT_RED = DARK["ACCENT_RED"]

STYLESHEET = get_stylesheet("dark")
