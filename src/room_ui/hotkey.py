"""Global hotkey listener — bridges pynput to a Qt signal."""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal

logger = logging.getLogger(__name__)


class HotkeyListener(QObject):
    """Listens for a global keyboard shortcut and emits *hotkey_pressed*.

    Uses ``pynput.keyboard.GlobalHotKeys`` running in a daemon thread so the
    Qt event loop is never blocked.  The signal is emitted on the pynput
    thread but connected via Qt's auto-connection, which safely queues the
    call onto the main thread when the receiver lives there.
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

    def start(self) -> None:
        if self._listener is not None:
            return
        try:
            from pynput.keyboard import GlobalHotKeys
        except ImportError:
            logger.error("pynput is not installed — global hotkey disabled")
            return

        self._listener = GlobalHotKeys({self._hotkey: self._on_activate})
        self._listener.daemon = True
        self._listener.start()
        logger.info("Global hotkey listener started: %s", self._hotkey)

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
            logger.info("Global hotkey listener stopped")

    def _on_activate(self) -> None:
        logger.debug("Hotkey activated")
        self.hotkey_pressed.emit()
