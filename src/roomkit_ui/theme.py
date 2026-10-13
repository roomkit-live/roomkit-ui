"""Dual-palette theme system (dark + light) with dynamic QSS generation."""

from __future__ import annotations

from PySide6.QtCore import QSettings

from roomkit_ui.paths import data_dir

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
    "ACCENT_BRAND": "#B7A6F0",
    "ACCENT_GREEN": "#30D158",
    "ACCENT_RED": "#FF453A",
    # Subtle grey user bubble (modern AI-chat look) — the assistant renders
    # bubble-less, so the user's message no longer needs a loud accent.
    "BUBBLE_USER_BG": "#2C2C2E",
    "BUBBLE_USER_TEXT": "#F2F2F7",
    "BUBBLE_AI_BG": "#2C2C2E",
    "BUBBLE_AI_TEXT": "#F2F2F7",
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
    "ACCENT_BRAND": "#6652BD",
    "ACCENT_GREEN": "#34C759",
    "ACCENT_RED": "#FF3B30",
    "BUBBLE_USER_BG": "#E9E9EB",
    "BUBBLE_USER_TEXT": "#1C1C1E",
    "BUBBLE_AI_BG": "#E5E5EA",
    "BUBBLE_AI_TEXT": "#000000",
    "BUBBLE_OTHER_BG": "#D1D1D6",
    "SPEAKER_LABEL": "#6C6C70",
    "CODE_BG": "#D8D8DD",
    "SEPARATOR": "#D1D1D6",
}

_PALETTES = {"dark": DARK, "light": LIGHT}

# One size for everything *said* in the conversation — user and assistant
# alike — in the window's own family: a chat set in a different family than
# the window around it reads as a foreign element, not as elegance.
#
# No font-family anywhere: Qt's application font already is the platform's UI
# font (SF on macOS, Segoe UI on Windows, the desktop's on Linux).  Named, it
# could only be named wrong — "-apple-system" and "SF Pro Text" are CSS and
# marketing names Qt does not know: it skipped them for Helvetica Neue, after
# a font-alias lookup it warned about at every start.
CHAT_FONT_SIZE_PX = 15


def fixed_font_family() -> str:
    """The platform's fixed-width font, by the name Qt knows it (Menlo on macOS).

    For code and logs.  "monospace" is a CSS name: Qt on macOS does not know
    it, looks it up (a font-alias warning) and falls back.  Without a running
    QGuiApplication Qt cannot say, and the generic name is all there is.
    """
    from PySide6.QtGui import QFontDatabase, QGuiApplication

    if QGuiApplication.instance() is None:
        return "monospace"
    family: str = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont).family()
    return family


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

# Heroicons chevron-down (MIT), the same family icons.py renders.  QSS takes
# image files, not inline markup, so the glyph lives as a tiny cached SVG.
_CHEVRON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" '
    'stroke-width="2" stroke="{color}">'
    '<path stroke-linecap="round" stroke-linejoin="round" '
    'd="m19.5 8.25-7.5 7.5-7.5-7.5"/></svg>'
)


def _cached_svg(name: str, svg: str) -> str:
    """Path (as_posix, for QSS ``url()``) of *svg*, written once as
    ``cache/<name>.svg``.  An unwritable data dir degrades to ``""``: the
    caller then keeps its native glyph rather than shipping a broken ``url()``.
    """
    path = data_dir() / "cache" / f"{name}.svg"
    try:
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(svg, encoding="utf-8")
    except OSError:
        return ""
    return path.as_posix()


def _chevron_url(color: str, *, up: bool = False) -> str:
    """A chevron-down (or up) SVG in *color*, keyed by color so each theme
    keeps its own file."""
    svg = _CHEVRON_SVG.format(color=color)
    if up:
        svg = svg.replace("m19.5 8.25-7.5 7.5-7.5-7.5", "m4.5 15.75 7.5-7.5 7.5 7.5")
    direction = "up" if up else "chevron"
    return _cached_svg(f"{direction}-{color.lstrip('#').lower()}", svg)


# SettingsToggle's switch as an image, so every checkbox draws it: a 38x20
# track, a 14 px knob, on a 44x26 canvas that leaves room for the focus ring.
_SWITCH_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="44" height="26" viewBox="0 0 44 26">'
    "{ring}"
    '<g opacity="{opacity}">'
    '<rect x="3" y="3" width="38" height="20" rx="10" fill="{track}"/>'
    '<circle cx="{knob_x}" cy="13" r="7" fill="{knob}"/></g></svg>'
)
_SWITCH_RING = (
    '<rect x="0.75" y="0.75" width="42.5" height="24.5" rx="12.25" fill="none" '
    'stroke="{color}" stroke-width="1.5"/>'
)


def switch_indicator_qss(scope: str, *, on: str, off: str, knob_on: str, knob_off: str) -> str:
    """QSS drawing every QCheckBox under *scope* as the settings' switch:
    on, off, disabled, and with the keyboard focus ring.  Empty when the
    images cannot be written (the checkboxes keep their own look)."""
    urls: dict[str, str] = {}
    for state, checked, disabled, focus in (
        ("off", False, False, False),
        ("on", True, False, False),
        ("off-disabled", False, True, False),
        ("on-disabled", True, True, False),
        ("off-focus", False, False, True),
        ("on-focus", True, False, True),
    ):
        svg = _SWITCH_SVG.format(
            ring=_SWITCH_RING.format(color=on) if focus else "",
            opacity="0.45" if disabled else "1",
            track=on if checked else off,
            knob=knob_on if checked else knob_off,
            knob_x=31 if checked else 13,
        )
        key = "-".join(color.lstrip("#").lower() for color in (on, off, knob_on, knob_off))
        urls[state] = _cached_svg(f"switch-{state}-{key}", svg)
        if not urls[state]:
            return ""
    box = f"{scope} QCheckBox"
    return f"""
{box} {{ spacing: 10px; }}
{box}::indicator {{
    width: 44px; height: 26px; border: none; background: transparent;
    image: url("{urls["off"]}");
}}
{box}::indicator:checked {{ image: url("{urls["on"]}"); }}
{box}::indicator:disabled {{ image: url("{urls["off-disabled"]}"); }}
{box}::indicator:checked:disabled {{ image: url("{urls["on-disabled"]}"); }}
{box}::indicator:focus {{ image: url("{urls["off-focus"]}"); }}
{box}::indicator:checked:focus {{ image: url("{urls["on-focus"]}"); }}
"""


def spin_buttons_qss(scope: str, *, arrow: str, hover: str) -> str:
    """QSS giving every number field under *scope* its own up/down buttons,
    clear of its text and border, with chevrons in *arrow*."""
    up, down = _chevron_url(arrow, up=True), _chevron_url(arrow)
    spin = f"{scope} QAbstractSpinBox"
    arrows = (
        f"""
{spin}::up-arrow {{ image: url("{up}"); width: 10px; height: 10px; }}
{spin}::down-arrow {{ image: url("{down}"); width: 10px; height: 10px; }}
"""
        if up and down
        else ""
    )
    return (
        f"""
{spin} {{ padding-right: 30px; }}
{spin}::up-button, {spin}::down-button {{
    subcontrol-origin: border; width: 22px; border: none; border-radius: 4px;
    background: transparent;
}}
{spin}::up-button {{ subcontrol-position: top right; margin: 4px 4px 0 0; }}
{spin}::down-button {{ subcontrol-position: bottom right; margin: 0 4px 4px 0; }}
{spin}::up-button:hover, {spin}::down-button:hover {{ background: {hover}; }}
"""
        + arrows
    )


def get_stylesheet(theme: str = "dark") -> str:
    """Generate the full application QSS for *theme*."""
    c = get_colors(theme)

    btn_pressed = "#C7C7CC" if theme == "light" else "#48484A"

    # Light mode needs visible borders on buttons
    btn_border = f"border: 1px solid {c['SEPARATOR']};" if theme == "light" else "border: none;"

    # Editable combos read as plain line edits without a visible arrow — the
    # text area takes the click for editing, so the arrow is the only popup
    # affordance they have.
    chevron = _chevron_url(c["TEXT_SECONDARY"])
    if chevron:
        down_arrow = f'image: url("{chevron}");\n    width: 14px;\n    height: 14px;'
    else:
        down_arrow = "image: none;"

    return f"""
/* ── Global ── */
QMainWindow, QWidget {{
    background-color: {c["BG_PRIMARY"]};
    color: {c["TEXT_PRIMARY"]};
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
    {down_arrow}
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
QCheckBox:disabled {{
    color: {c["TEXT_SECONDARY"]};
}}
""" + switch_indicator_qss(
        "",
        on=c["ACCENT_BRAND"],
        off=c["TEXT_SECONDARY"],
        knob_on=c["BG_PRIMARY"],
        knob_off="#FFFFFF",
    )


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
