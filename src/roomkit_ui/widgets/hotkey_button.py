"""Press-to-record hotkey capture button."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton

from roomkit_ui.theme import colors

# ── Qt modifier → pynput token ──────────────────────────────────────────

_QT_MOD_TO_PYNPUT = [
    (Qt.ControlModifier, "<ctrl>"),
    (Qt.AltModifier, "<alt>"),
    (Qt.ShiftModifier, "<shift>"),
    (Qt.MetaModifier, "<cmd>"),
]

# ── Qt.Key → pynput token (special keys) ────────────────────────────────

_QT_KEY_TO_PYNPUT: dict[int, str] = {
    Qt.Key_F1: "<F1>",
    Qt.Key_F2: "<F2>",
    Qt.Key_F3: "<F3>",
    Qt.Key_F4: "<F4>",
    Qt.Key_F5: "<F5>",
    Qt.Key_F6: "<F6>",
    Qt.Key_F7: "<F7>",
    Qt.Key_F8: "<F8>",
    Qt.Key_F9: "<F9>",
    Qt.Key_F10: "<F10>",
    Qt.Key_F11: "<F11>",
    Qt.Key_F12: "<F12>",
    Qt.Key_Space: "<space>",
    Qt.Key_Tab: "<tab>",
    Qt.Key_Return: "<enter>",
    Qt.Key_Enter: "<enter>",
    Qt.Key_Backspace: "<backspace>",
    Qt.Key_Delete: "<delete>",
    Qt.Key_Home: "<home>",
    Qt.Key_End: "<end>",
    Qt.Key_PageUp: "<page_up>",
    Qt.Key_PageDown: "<page_down>",
    Qt.Key_Up: "<up>",
    Qt.Key_Down: "<down>",
    Qt.Key_Left: "<left>",
    Qt.Key_Right: "<right>",
    Qt.Key_Insert: "<insert>",
}

# Pure modifier keys — can be used alone as a hotkey
_MODIFIER_KEYS = {
    Qt.Key_Control,
    Qt.Key_Shift,
    Qt.Key_Alt,
    Qt.Key_Meta,
    Qt.Key_AltGr,
    Qt.Key_Super_L,
    Qt.Key_Super_R,
    Qt.Key_Hyper_L,
    Qt.Key_Hyper_R,
}

# Map Qt modifier Key_* → pynput token for single-modifier hotkeys
_QT_MODIFIER_KEY_TO_PYNPUT: dict[int, str] = {
    Qt.Key_Control: "<ctrl>",
    Qt.Key_Shift: "<shift>",
    Qt.Key_Alt: "<alt>",
    Qt.Key_Meta: "<cmd>",
    Qt.Key_AltGr: "<alt_gr>",
    Qt.Key_Super_L: "<cmd_l>",
    Qt.Key_Super_R: "<cmd_r>",
}


def _qt_key_to_pynput(key: int) -> str | None:
    """Convert a Qt.Key enum value to its pynput string token."""
    if key in _QT_KEY_TO_PYNPUT:
        return _QT_KEY_TO_PYNPUT[key]
    # a-z
    if Qt.Key_A <= key <= Qt.Key_Z:
        return chr(key - Qt.Key_A + ord("a"))
    # 0-9
    if Qt.Key_0 <= key <= Qt.Key_9:
        return chr(key - Qt.Key_0 + ord("0"))
    return None


def pynput_to_display(pynput_str: str) -> str:
    """Convert a pynput hotkey string to a friendly display name.

    ``<ctrl>+<shift>+h`` → ``Ctrl+Shift+H``
    """
    if not pynput_str:
        return ""
    names = {
        "<ctrl>": "Ctrl",
        "<ctrl_l>": "Ctrl L",
        "<ctrl_r>": "Ctrl R",
        "<alt>": "Alt",
        "<alt_l>": "Alt L",
        "<alt_r>": "Alt R",
        "<alt_gr>": "AltGr",
        "<shift>": "Shift",
        "<shift_l>": "Shift L",
        "<shift_r>": "Shift R",
        "<cmd>": "Cmd",
        "<cmd_l>": "Cmd L",
        "<cmd_r>": "Cmd R",
        "<space>": "Space",
        "<tab>": "Tab",
        "<enter>": "Enter",
        "<backspace>": "Backspace",
        "<delete>": "Delete",
        "<home>": "Home",
        "<end>": "End",
        "<page_up>": "PageUp",
        "<page_down>": "PageDown",
        "<up>": "Up",
        "<down>": "Down",
        "<left>": "Left",
        "<right>": "Right",
        "<insert>": "Insert",
    }
    parts: list[str] = []
    for tok in pynput_str.split("+"):
        tok_lower = tok.lower()
        if tok_lower in names:
            parts.append(names[tok_lower])
        elif tok_lower.startswith("<f") and tok_lower.endswith(">"):
            # <F5> → F5
            parts.append(tok[1:-1].upper())
        else:
            parts.append(tok.upper())
    return "+".join(parts)


class HotkeyButton(QPushButton):
    """Click-to-record keyboard shortcut capture widget.

    Idle state shows the friendly name (e.g. "Ctrl+Shift+H").
    Click to enter recording mode, then press a modifier+key combo.
    Escape or focus loss cancels recording.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._pynput_value = ""
        self._recording = False
        self._pending_modifier: int | None = None
        self._apply_style()
        self.clicked.connect(self._start_recording)

    # ── Public API ──────────────────────────────────────────────────────

    def value(self) -> str:
        """Return the current hotkey in pynput format."""
        return self._pynput_value

    def set_value(self, pynput_str: str) -> None:
        """Set the hotkey from a pynput format string."""
        self._pynput_value = pynput_str
        self.setText(pynput_to_display(pynput_str) or "None")
        self._apply_style()

    # ── Recording lifecycle ─────────────────────────────────────────────

    def _start_recording(self) -> None:
        self._recording = True
        self._pending_modifier = None
        self.setText("Press a key or combination\u2026")
        self._apply_style()
        self.grabKeyboard()

    def _stop_recording(self) -> None:
        self._recording = False
        self.releaseKeyboard()
        self.setText(pynput_to_display(self._pynput_value) or "None")
        self._apply_style()

    # ── Event overrides ─────────────────────────────────────────────────

    def keyPressEvent(self, event) -> None:
        if not self._recording:
            super().keyPressEvent(event)
            return

        key = event.key()

        # Escape cancels
        if key == Qt.Key_Escape:
            self._stop_recording()
            return

        # Modifier pressed alone — remember it, finalize on release
        if key in _MODIFIER_KEYS:
            self._pending_modifier = key
            return

        # Non-modifier key pressed — clear pending modifier
        self._pending_modifier = None

        pynput_key = _qt_key_to_pynput(key)
        if pynput_key is None:
            return

        # Collect active modifiers
        mods = event.modifiers()
        tokens: list[str] = []
        for qt_mod, pynput_tok in _QT_MOD_TO_PYNPUT:
            if mods & qt_mod:
                tokens.append(pynput_tok)
        tokens.append(pynput_key)

        self._pynput_value = "+".join(tokens)
        self._stop_recording()

    def keyReleaseEvent(self, event) -> None:  # noqa: N802
        if not self._recording:
            super().keyReleaseEvent(event)
            return

        key = event.key()
        # Modifier released without any other key → use it as the hotkey
        if key == self._pending_modifier:
            pynput_tok = _QT_MODIFIER_KEY_TO_PYNPUT.get(key)
            if pynput_tok:
                self._pynput_value = pynput_tok
                self._stop_recording()
                return

        super().keyReleaseEvent(event)

    def focusOutEvent(self, event) -> None:
        if self._recording:
            self._stop_recording()
        super().focusOutEvent(event)

    # ── Styling ─────────────────────────────────────────────────────────

    def _apply_style(self) -> None:
        c = colors()
        if self._recording:
            self.setStyleSheet(
                f"QPushButton {{ border: 2px solid {c['ACCENT_BLUE']};"
                f" background-color: {c['BG_SECONDARY']};"
                f" color: {c['TEXT_SECONDARY']};"
                f" border-radius: 8px; padding: 8px 12px;"
                f" font-size: 14px; font-style: italic; }}"
            )
        else:
            self.setStyleSheet(
                f"QPushButton {{ border: 1px solid {c['BG_TERTIARY']};"
                f" background-color: {c['BG_SECONDARY']};"
                f" color: {c['TEXT_PRIMARY']};"
                f" border-radius: 8px; padding: 8px 12px;"
                f" font-size: 14px; }}"
                f"QPushButton:hover {{ border-color: {c['ACCENT_BLUE']}; }}"
            )
