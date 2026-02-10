"""Global hotkey listener using macOS CGEventTap or pynput fallback."""

from __future__ import annotations

import logging
import sys
import threading

from PySide6.QtCore import QObject, QTimer, Signal

logger = logging.getLogger(__name__)

# macOS virtual key codes for modifier keys
_MAC_KEYCODES = {
    "<cmd_r>": 0x36,   # Right Command
    "<cmd_l>": 0x37,   # Left Command
    "<shift_r>": 0x3C, # Right Shift
    "<shift_l>": 0x38, # Left Shift
    "<ctrl_r>": 0x3E,  # Right Control
    "<ctrl_l>": 0x3B,  # Left Control
    "<alt_r>": 0x3D,   # Right Option
    "<alt_l>": 0x3A,   # Left Option
}

# Map keycodes to their modifier flag mask
_KEYCODE_TO_MASK = {
    0x36: "kCGEventFlagMaskCommand",
    0x37: "kCGEventFlagMaskCommand",
    0x3C: "kCGEventFlagMaskShift",
    0x38: "kCGEventFlagMaskShift",
    0x3E: "kCGEventFlagMaskControl",
    0x3B: "kCGEventFlagMaskControl",
    0x3D: "kCGEventFlagMaskAlternate",
    0x3A: "kCGEventFlagMaskAlternate",
}


class HotkeyListener(QObject):
    """Listens for a global keyboard shortcut and emits *hotkey_pressed*.

    On macOS, uses a ``CGEventTap`` for reliable global key monitoring in
    packaged apps.  Falls back to ``pynput`` on other platforms.
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
        self._tap = None
        self._loop_ref = None
        # Thread-safe flag: CGEventTap callback sets it, QTimer polls it
        self._pending = False
        self._poll_timer: QTimer | None = None

    def start(self) -> None:
        if self._listener is not None or self._tap is not None:
            return

        if sys.platform == "darwin" and self._hotkey in _MAC_KEYCODES:
            self._start_cgevent()
        else:
            self._start_pynput()

    def _start_cgevent(self) -> None:
        """Use CGEventTap to monitor a single key (macOS native)."""
        try:
            import Quartz
        except ImportError:
            logger.error("PyObjC/Quartz not available — falling back to pynput")
            self._start_pynput()
            return

        target_keycode = _MAC_KEYCODES[self._hotkey]
        mask_name = _KEYCODE_TO_MASK[target_keycode]
        mask_value = getattr(Quartz, mask_name)

        # Keep a reference to self for the callback closure
        listener = self

        def callback(proxy, event_type, event, refcon):
            try:
                # macOS disables taps on timeout — re-enable immediately
                if event_type == Quartz.kCGEventTapDisabledByTimeout:
                    logger.warning("CGEventTap disabled by timeout — re-enabling")
                    Quartz.CGEventTapEnable(listener._tap, True)
                    return event

                if event_type == Quartz.kCGEventFlagsChanged:
                    keycode = Quartz.CGEventGetIntegerValueField(
                        event, Quartz.kCGKeyboardEventKeycode
                    )
                    if keycode == target_keycode:
                        flags = Quartz.CGEventGetFlags(event)
                        # Fire on release: modifier flag is no longer set
                        if not (flags & mask_value):
                            listener._pending = True
            except Exception:
                pass  # never let the callback fail
            return event

        # kCGEventTapDisabledByTimeout is delivered automatically — no need
        # to include it in the mask.
        tap = Quartz.CGEventTapCreate(
            Quartz.kCGSessionEventTap,
            Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionListenOnly,
            Quartz.CGEventMaskBit(Quartz.kCGEventFlagsChanged),
            callback,
            None,
        )

        if tap is None:
            logger.error(
                "CGEventTap creation failed — Accessibility permission required. "
                "Go to System Settings → Privacy & Security → Accessibility and add this app."
            )
            return

        self._tap = tap
        run_loop_source = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)

        def run():
            loop = Quartz.CFRunLoopGetCurrent()
            self._loop_ref = loop
            Quartz.CFRunLoopAddSource(loop, run_loop_source, Quartz.kCFRunLoopCommonModes)
            Quartz.CGEventTapEnable(tap, True)
            logger.info(
                "CGEventTap hotkey listener started: %s (keycode 0x%02X)",
                self._hotkey,
                target_keycode,
            )
            Quartz.CFRunLoopRun()

        t = threading.Thread(target=run, daemon=True)
        t.start()

        # Poll the flag from the Qt main thread — avoids emitting signals
        # from the CGEventTap callback thread which can cause the tap to
        # be disabled by macOS due to timeout.
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(50)  # 50ms polling
        self._poll_timer.timeout.connect(self._poll_pending)
        self._poll_timer.start()

    def _poll_pending(self) -> None:
        """Check if the CGEventTap callback flagged a hotkey press."""
        if self._pending:
            self._pending = False
            logger.info("Hotkey activated: %s", self._hotkey)
            self.hotkey_pressed.emit()

    def _start_pynput(self) -> None:
        """Fallback: use pynput for multi-key combos or non-macOS."""
        try:
            from pynput import keyboard
        except ImportError:
            logger.error("pynput is not installed — global hotkey disabled")
            return

        if "+" not in self._hotkey:
            from pynput.keyboard import HotKey

            parsed = HotKey.parse(self._hotkey)
            if not parsed:
                logger.error("Could not parse hotkey: %s", self._hotkey)
                return
            target_key = parsed[0]

            def on_release(key):
                if key == target_key:
                    self._on_activate()

            self._listener = keyboard.Listener(on_release=on_release)
        else:
            self._listener = keyboard.GlobalHotKeys(
                {self._hotkey: self._on_activate}
            )

        self._listener.daemon = True
        self._listener.start()
        logger.info("pynput hotkey listener started: %s", self._hotkey)

    def stop(self) -> None:
        if self._poll_timer is not None:
            self._poll_timer.stop()
            self._poll_timer = None
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
        if self._loop_ref is not None:
            import Quartz

            Quartz.CFRunLoopStop(self._loop_ref)
            self._loop_ref = None
            self._tap = None
        logger.info("Global hotkey listener stopped")

    def _on_activate(self) -> None:
        logger.info("Hotkey activated: %s", self._hotkey)
        self.hotkey_pressed.emit()
