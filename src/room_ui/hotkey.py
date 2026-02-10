"""Global hotkey listener — bridges pynput to a Qt signal."""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal

logger = logging.getLogger(__name__)


class HotkeyListener(QObject):
    """Listens for a global keyboard shortcut and emits *hotkey_pressed*.

    Runs a pynput listener in a daemon thread so the Qt event loop is never
    blocked.  The signal is emitted on the pynput thread but connected via Qt's
    auto-connection, which safely queues the call onto the main thread when the
    receiver lives there.

    For multi-key combos (e.g. ``<ctrl>+<shift>+h``) we use ``GlobalHotKeys``.
    For single modifier keys (e.g. ``<cmd_r>``) we use a raw ``Listener`` that
    fires on key release — this avoids issues with GlobalHotKeys treating
    modifier-only hotkeys inconsistently.
    """

    hotkey_pressed = Signal()

    def __init__(
        self,
        hotkey: str = "<ctrl>+<shift>+h",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._hotkey = hotkey
        self._listener = None

    def _is_single_key(self) -> bool:
        """Return True if the hotkey is a single key (no ``+`` combos)."""
        return "+" not in self._hotkey

    def start(self) -> None:
        if self._listener is not None:
            return
        try:
            from pynput import keyboard
        except ImportError:
            logger.error("pynput is not installed — global hotkey disabled")
            return

        if self._is_single_key():
            self._start_single_key(keyboard)
        else:
            self._start_combo(keyboard)

        logger.info("Global hotkey listener started: %s", self._hotkey)

    def _start_combo(self, keyboard) -> None:  # noqa: ANN001
        """Use GlobalHotKeys for multi-key combos."""
        self._listener = keyboard.GlobalHotKeys(
            {self._hotkey: self._on_activate}
        )
        self._listener.daemon = True
        self._listener.start()

    def _start_single_key(self, keyboard) -> None:  # noqa: ANN001
        """Use a raw Listener for a single modifier key (fires on release)."""
        from pynput.keyboard import HotKey, Key

        parsed = HotKey.parse(self._hotkey)
        if not parsed:
            logger.error("Could not parse hotkey: %s", self._hotkey)
            return
        target_key = parsed[0]

        def on_release(key: Key) -> None:
            if key == target_key:
                self._on_activate()

        self._listener = keyboard.Listener(on_release=on_release)
        self._listener.daemon = True
        self._listener.start()

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
            logger.info("Global hotkey listener stopped")

    def _on_activate(self) -> None:
        logger.debug("Hotkey activated")
        self.hotkey_pressed.emit()
