"""Global hotkey listener using macOS CGEventTap or pynput fallback."""

from __future__ import annotations

import logging
import sys
from typing import Any

from PySide6.QtCore import QMetaObject, QObject, Qt, QTimer, Signal, Slot

logger = logging.getLogger(__name__)

# macOS virtual key codes for modifier keys
_MAC_KEYCODES = {
    "<cmd_r>": 0x36,  # Right Command
    "<cmd_l>": 0x37,  # Left Command
    "<shift_r>": 0x3C,  # Right Shift
    "<shift_l>": 0x38,  # Left Shift
    "<ctrl_r>": 0x3E,  # Right Control
    "<ctrl_l>": 0x3B,  # Left Control
    "<alt_r>": 0x3D,  # Right Option
    "<alt_l>": 0x3A,  # Left Option
}

# Map keycodes to their modifier flag mask (NSEvent constants)
_KEYCODE_TO_FLAG = {
    0x36: "NSEventModifierFlagCommand",
    0x37: "NSEventModifierFlagCommand",
    0x3C: "NSEventModifierFlagShift",
    0x38: "NSEventModifierFlagShift",
    0x3E: "NSEventModifierFlagControl",
    0x3B: "NSEventModifierFlagControl",
    0x3D: "NSEventModifierFlagOption",
    0x3A: "NSEventModifierFlagOption",
}


class HotkeyListener(QObject):
    """Listens for a global keyboard shortcut and emits *hotkey_pressed*.

    On macOS, uses ``NSEvent.addGlobalMonitorForEventsMatchingMask`` for
    reliable global key monitoring.  Falls back to ``pynput`` on other
    platforms.
    """

    hotkey_pressed = Signal()

    def __init__(
        self,
        hotkey: str = "<ctrl>+<shift>+h",
        enabled_key: str = "stt_enabled",
        hotkey_key: str = "stt_hotkey",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._hotkey = hotkey
        self._enabled_key = enabled_key
        self._hotkey_key = hotkey_key
        self._listener: Any = None
        self._monitor: Any = None  # NSEvent global monitor

    def start(self) -> None:
        if self._listener is not None or self._monitor is not None:
            return

        if sys.platform == "darwin" and self._hotkey in _MAC_KEYCODES:
            self._start_nsevent()
        else:
            self._start_pynput()

    def _start_nsevent(self) -> None:
        """Use NSEvent global monitor for modifier key (macOS native)."""
        try:
            from AppKit import NSEvent, NSFlagsChangedMask
        except ImportError:
            logger.error("PyObjC/AppKit not available — falling back to pynput")
            self._start_pynput()
            return

        target_keycode = _MAC_KEYCODES[self._hotkey]
        flag_name = _KEYCODE_TO_FLAG[target_keycode]

        try:
            from AppKit import (
                NSEventModifierFlagCommand,
                NSEventModifierFlagControl,
                NSEventModifierFlagOption,
                NSEventModifierFlagShift,
            )

            flag_map = {
                "NSEventModifierFlagCommand": NSEventModifierFlagCommand,
                "NSEventModifierFlagShift": NSEventModifierFlagShift,
                "NSEventModifierFlagControl": NSEventModifierFlagControl,
                "NSEventModifierFlagOption": NSEventModifierFlagOption,
            }
            mask_value = flag_map[flag_name]
        except (ImportError, KeyError):
            logger.error("Could not resolve modifier flag %s", flag_name)
            self._start_pynput()
            return

        listener = self

        def handler(event):
            try:
                if event.keyCode() == target_keycode:
                    flags = event.modifierFlags()
                    # Fire on release: modifier flag is no longer set
                    if not (flags & mask_value):
                        # Defer signal emission to the next Qt event loop tick
                        # so the handler returns immediately.
                        QTimer.singleShot(0, listener._on_activate)
            except Exception:
                pass

        self._monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
            NSFlagsChangedMask,
            handler,
        )

        if self._monitor is None:
            logger.error(
                "NSEvent monitor creation failed — Accessibility permission required. "
                "Go to System Settings → Privacy & Security → Accessibility and add this app."
            )
            return

        logger.info(
            "NSEvent hotkey listener started: %s (keycode 0x%02X)",
            self._hotkey,
            target_keycode,
        )

    def _start_pynput(self) -> None:
        """Fallback: use pynput for multi-key combos or non-macOS."""
        try:
            from pynput import keyboard
        except ImportError:
            logger.error("pynput is not installed — global hotkey disabled")
            return

        # All pynput callbacks run in a background thread — use
        # QMetaObject.invokeMethod to safely call back into the Qt main thread.
        def _safe_activate(*_args):
            QMetaObject.invokeMethod(self, "_on_activate", Qt.QueuedConnection)

        if "+" not in self._hotkey:
            from pynput.keyboard import HotKey, Key, KeyCode

            parsed = HotKey.parse(self._hotkey)
            if not parsed:
                logger.error("Could not parse hotkey: %s", self._hotkey)
                return
            target_key = parsed[0]

            # Build a set of keys that should match — include both
            # left/right variants for generic modifiers (e.g. <ctrl>
            # should match both ctrl_l and ctrl_r).
            # AltGr on many Linux keyboards reports as ISO_Level3_Shift
            # (vk 65027) instead of pynput's Key.alt_gr (vk 65406).
            variants: dict[Key | KeyCode, set[Key | KeyCode]] = {
                Key.ctrl: {Key.ctrl, Key.ctrl_l, Key.ctrl_r},
                Key.shift: {Key.shift, Key.shift_l, Key.shift_r},
                Key.alt: {Key.alt, Key.alt_l, Key.alt_r, Key.alt_gr, KeyCode.from_vk(65027)},
                Key.alt_gr: {Key.alt_gr, Key.alt_r, KeyCode.from_vk(65027)},
                Key.cmd: {Key.cmd, Key.cmd_l, Key.cmd_r},
            }
            match_keys = variants.get(target_key, {target_key})

            def on_release(key):
                if key in match_keys:
                    _safe_activate()

            self._listener = keyboard.Listener(on_release=on_release)
        else:
            self._listener = keyboard.GlobalHotKeys({self._hotkey: _safe_activate})

        self._listener.daemon = True
        self._listener.start()
        logger.info("pynput hotkey listener started: %s", self._hotkey)

    def stop(self) -> None:
        if self._monitor is not None:
            try:
                from AppKit import NSEvent

                NSEvent.removeMonitor_(self._monitor)
            except Exception:
                pass
            self._monitor = None
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
        logger.info("Global hotkey listener stopped")

    def reload(self) -> None:
        """Restart the listener with fresh settings."""
        from roomkit_ui.settings import load_settings

        settings = load_settings()
        enabled = settings.get(self._enabled_key, True)
        new_hotkey = settings.get(self._hotkey_key, "<ctrl>+<shift>+h")

        self.stop()

        if not enabled:
            logger.info("Hotkey disabled by settings")
            return

        self._hotkey = new_hotkey
        self.start()
        logger.info("Hotkey reloaded: %s", new_hotkey)

    @Slot()
    def _on_activate(self) -> None:
        logger.info("Hotkey activated: %s", self._hotkey)
        self.hotkey_pressed.emit()
