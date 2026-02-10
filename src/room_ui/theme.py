"""Apple-inspired dark theme QSS stylesheet."""

BG_PRIMARY = "#1C1C1E"
BG_SECONDARY = "#2C2C2E"
BG_TERTIARY = "#3A3A3C"
TEXT_PRIMARY = "#FFFFFF"
TEXT_SECONDARY = "#8E8E93"
ACCENT_BLUE = "#0A84FF"
ACCENT_GREEN = "#30D158"
ACCENT_RED = "#FF453A"

STYLESHEET = f"""
/* ── Global ── */
QMainWindow, QWidget {{
    background-color: {BG_PRIMARY};
    color: {TEXT_PRIMARY};
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
    background: {BG_TERTIARY};
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
    background-color: {BG_SECONDARY};
    color: {TEXT_PRIMARY};
    border: none;
    border-radius: 10px;
    padding: 8px 18px;
    font-size: 14px;
    font-weight: 500;
}}
QPushButton:hover {{
    background-color: {BG_TERTIARY};
}}
QPushButton:pressed {{
    background-color: #48484A;
}}

/* ── Start button (green pill) ── */
QPushButton#startButton {{
    background-color: {ACCENT_GREEN};
    color: #000000;
    font-size: 15px;
    font-weight: 600;
    padding: 12px 28px;
    border-radius: 24px;
}}
QPushButton#startButton:hover {{
    background-color: #28c04e;
}}
QPushButton#startButton:pressed {{
    background-color: #22a843;
}}

/* ── Stop / End button (red pill) ── */
QPushButton#stopButton {{
    background-color: {ACCENT_RED};
    color: #FFFFFF;
    font-size: 15px;
    font-weight: 600;
    padding: 12px 28px;
    border-radius: 24px;
}}
QPushButton#stopButton:hover {{
    background-color: #e03e34;
}}
QPushButton#stopButton:pressed {{
    background-color: #c4352c;
}}

/* ── Mic mute button (circle) ── */
QPushButton#muteButton {{
    background-color: {BG_SECONDARY};
    border: 1px solid {BG_TERTIARY};
    border-radius: 22px;
    padding: 0px;
}}
QPushButton#muteButton:hover {{
    background-color: {BG_TERTIARY};
    border-color: #48484A;
}}
QPushButton#muteButton[muted="true"] {{
    background-color: rgba(255, 69, 58, 0.2);
    border-color: {ACCENT_RED};
}}

/* ── Gear / settings button ── */
QPushButton#gearButton {{
    background-color: transparent;
    border: none;
    border-radius: 18px;
    padding: 0px;
}}
QPushButton#gearButton:hover {{
    background-color: {BG_SECONDARY};
}}

/* ── Labels ── */
QLabel#titleLabel {{
    font-size: 16px;
    font-weight: 600;
    color: {TEXT_PRIMARY};
    background: transparent;
}}
QLabel#statusLabel {{
    font-size: 11px;
    color: {TEXT_SECONDARY};
    background: transparent;
}}

/* ── Settings dialog ── */
QDialog {{
    background-color: {BG_PRIMARY};
}}
QLineEdit, QTextEdit, QComboBox {{
    background-color: {BG_SECONDARY};
    color: {TEXT_PRIMARY};
    border: 1px solid {BG_TERTIARY};
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 14px;
    selection-background-color: {ACCENT_BLUE};
}}
QLineEdit:focus, QTextEdit:focus, QComboBox:focus {{
    border: 1px solid {ACCENT_BLUE};
}}
QComboBox::drop-down {{
    border: none;
    width: 24px;
}}
QComboBox::down-arrow {{
    image: none;
}}
QComboBox QAbstractItemView {{
    background-color: {BG_SECONDARY};
    color: {TEXT_PRIMARY};
    selection-background-color: {ACCENT_BLUE};
    border: 1px solid {BG_TERTIARY};
    border-radius: 8px;
}}
QCheckBox {{
    color: {TEXT_PRIMARY};
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 2px solid {BG_TERTIARY};
    background: {BG_SECONDARY};
}}
QCheckBox::indicator:checked {{
    background: {ACCENT_BLUE};
    border-color: {ACCENT_BLUE};
}}
"""
