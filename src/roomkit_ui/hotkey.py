"""Global hotkey listener using macOS CGEventTap or pynput fallback."""

from __future__ import annotations

import logging
import sys
from typing import Any

from PySide6.QtCore import QMetaObject, QObject, Qt, QTimer, Signal, Slot

logger = logging.getLogger(__name__)

# pynput on macOS internally calls HIServices.AXIsProcessTrusted() in its
# listener thread, which fails with newer pyobjc (KeyError on lazy import).
# Patch it at module level so all pynput Listener instances work.
if sys.platform == "darwin":
    try:
        import HIServices  # type: ignore[import-untyped]

        if not hasattr(HIServices, "AXIsProcessTrusted"):
            from ApplicationServices import AXIsProcessTrusted  # type: ignore[import-untyped]

            HIServices.AXIsProcessTrusted = AXIsProcessTrusted
            logger.debug("Patched HIServices.AXIsProcessTrusted for pynput compatibility")
    except (ImportError, AttributeError):
        pass

# macOS virtual key codes for modifier keys.
# Generic names (e.g. "<alt>") map to both left and right keycodes so the
# NSEvent handler fires on either side.
_MAC_KEYCODES: dict[str, tuple[int, ...]] = {
    "<cmd_r>": (0x36,),
    "<cmd_l>": (0x37,),
    "<cmd>": (0x37, 0x36),
    "<shift_r>": (0x3C,),
    "<shift_l>": (0x38,),
    "<shift>": (0x38, 0x3C),
    "<ctrl_r>": (0x3E,),
    "<ctrl_l>": (0x3B,),
    "<ctrl>": (0x3B, 0x3E),
    "<alt_r>": (0x3D,),
    "<alt_l>": (0x3A,),
    "<alt>": (0x3A, 0x3D),
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
    permission_required = Signal()  # emitted when macOS Accessibility is missing

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
        self._matcher: _KeyMatcher | None = None  # swappable key matching logic

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

        target_keycodes = _MAC_KEYCODES[self._hotkey]
        # All keycodes for a given modifier share the same flag
        flag_name = _KEYCODE_TO_FLAG[target_keycodes[0]]

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
        kc_set = set(target_keycodes)

        def handler(event):
            try:
                if event.keyCode() in kc_set:
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
            self.permission_required.emit()
            return

        kc_hex = ", ".join(f"0x{kc:02X}" for kc in target_keycodes)
        logger.info(
            "NSEvent hotkey listener started: %s (keycodes %s)",
            self._hotkey,
            kc_hex,
        )

    def _start_pynput(self) -> None:
        """Fallback: use pynput for multi-key combos or non-macOS."""
        # On macOS, pynput needs Accessibility (AXIsProcessTrusted).
        # We log a warning but still attempt to start — AXIsProcessTrusted()
        # can return stale results, especially for signed PyInstaller apps
        # where the TCC csreq may not match what the API checks.
        if sys.platform == "darwin":
            try:
                import HIServices

                ax = HIServices.AXIsProcessTrustedWithOptions(
                    {HIServices.kAXTrustedCheckOptionPrompt: False}
                )
            except (ImportError, AttributeError):
                try:
                    from ApplicationServices import AXIsProcessTrusted

                    ax = AXIsProcessTrusted()
                except ImportError:
                    ax = None
            if ax is False:
                logger.warning(
                    "Accessibility not granted (AXIsProcessTrusted=False). "
                    "Attempting pynput anyway — grant access in System Settings "
                    "→ Privacy & Security → Accessibility."
                )

        try:
            from pynput import keyboard
        except ImportError:
            logger.error("pynput is not installed — global hotkey disabled")
            return

        # Build the matcher for the current hotkey
        self._matcher = _KeyMatcher(self._hotkey)
        if not self._matcher.valid:
            logger.error("Could not parse hotkey: %s", self._hotkey)
            self._matcher = None
            return

        # All pynput callbacks run in a background thread — use
        # QMetaObject.invokeMethod to safely call back into the Qt main thread.
        def _safe_activate():
            QMetaObject.invokeMethod(self, "_on_activate", Qt.QueuedConnection)

        # Build a pynput HotKey that handles key canonicalization properly
        # (e.g. Ctrl+K reports vk=40 not char='k').  Use it with a plain
        # Listener instead of GlobalHotKeys to avoid the HIServices crash.
        self._matcher = _KeyMatcher(self._hotkey, _safe_activate)
        if not self._matcher.valid:
            logger.error("Could not parse hotkey: %s", self._hotkey)
            self._matcher = None
            return

        matcher = self._matcher
        listener_ref: list[keyboard.Listener] = []

        def on_press(key):
            if listener_ref:
                key = listener_ref[0].canonical(key)
            matcher.press(key)

        def on_release(key):
            if listener_ref:
                key = listener_ref[0].canonical(key)
            matcher.release(key)

        self._listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        listener_ref.append(self._listener)
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
            try:
                self._listener.join(timeout=2.0)
            except Exception:
                pass
            self._listener = None
        self._matcher = None
        logger.info("Global hotkey listener stopped")

    def reload(self) -> None:
        """Restart the listener with fresh settings."""
        from roomkit_ui.settings import load_settings

        settings = load_settings()
        enabled = settings.get(self._enabled_key, True)
        new_hotkey = settings.get(self._hotkey_key, "<ctrl>+<shift>+h")

        is_running = self._listener is not None or self._monitor is not None

        # Nothing changed — skip the teardown/recreate cycle.
        if new_hotkey == self._hotkey and enabled == is_running:
            logger.info("Hotkey unchanged (%s), skipping reload", self._hotkey)
            return

        logger.info(
            "Hotkey reload: %s → %s (enabled %s → %s)",
            self._hotkey,
            new_hotkey,
            is_running,
            enabled,
        )

        self._hotkey = new_hotkey

        if not enabled:
            self.stop()
            logger.info("Hotkey disabled by settings")
            return

        # On macOS, restarting a pynput Listener (CGEventTap) causes a
        # Trace/BPT trap (SIGTRAP) crash.  If we already have a running
        # pynput listener, hot-swap the matcher instead of stop/start.
        if sys.platform == "darwin" and self._listener is not None:
            # Switching between pynput and NSEvent requires a full restart,
            # but pynput→pynput can be done with a matcher swap.
            if new_hotkey not in _MAC_KEYCODES:
                new_matcher = _KeyMatcher(new_hotkey)
                if new_matcher.valid and self._matcher is not None:
                    self._matcher.swap(new_matcher)
                    logger.info("Hotkey reloaded (matcher swap): %s", new_hotkey)
                    return

        # Full stop/start for non-macOS or when switching listener type
        self.stop()
        self.start()
        logger.info("Hotkey reloaded: %s", new_hotkey)

    @Slot()
    def _on_activate(self) -> None:
        logger.info("Hotkey activated: %s", self._hotkey)
        self.hotkey_pressed.emit()


class _KeyMatcher:
    """Hotkey matching that can be swapped at runtime.

    Wraps pynput's ``HotKey`` for multi-key combos, and does simple
    key-set matching for single-modifier hotkeys.  The ``swap()`` method
    allows updating the target keys without destroying the pynput Listener
    (avoids the macOS SIGTRAP crash on CGEventTap re-creation).
    """

    def __init__(self, hotkey: str, callback: Any = None) -> None:
        from pynput.keyboard import HotKey, Key, KeyCode

        parsed = HotKey.parse(hotkey)
        self.valid = bool(parsed)
        if not self.valid:
            return

        self._callback = callback
        self._is_combo = "+" in hotkey

        if self._is_combo:
            self._hotkey = HotKey(parsed, self._on_activate)
        else:
            # Single-key hotkeys: build a match set with left/right variants
            variants: dict[Key | KeyCode, set[Key | KeyCode]] = {
                Key.ctrl: {Key.ctrl, Key.ctrl_l, Key.ctrl_r},
                Key.shift: {Key.shift, Key.shift_l, Key.shift_r},
                Key.alt: {Key.alt, Key.alt_l, Key.alt_r, Key.alt_gr, KeyCode.from_vk(65027)},
                Key.alt_gr: {Key.alt_gr, Key.alt_r, KeyCode.from_vk(65027)},
                Key.cmd: {Key.cmd, Key.cmd_l, Key.cmd_r},
            }
            self._match_keys = variants.get(parsed[0], {parsed[0]})
            self._hotkey = None

    def _on_activate(self) -> None:
        if self._callback:
            self._callback()

    def swap(self, other: _KeyMatcher) -> None:
        """Replace matching logic with *other*'s configuration."""
        self._is_combo = other._is_combo
        self._hotkey = other._hotkey
        if hasattr(other, "_match_keys"):
            self._match_keys = other._match_keys
        # Re-point the swapped HotKey's callback to our own
        if self._hotkey is not None:
            self._hotkey._on_activate = self._on_activate

    def press(self, key) -> None:
        """Feed a canonicalized key press."""
        if self._is_combo and self._hotkey is not None:
            self._hotkey.press(key)

    def release(self, key) -> None:
        """Feed a canonicalized key release."""
        if self._is_combo and self._hotkey is not None:
            self._hotkey.release(key)
        elif not self._is_combo and key in self._match_keys:
            self._on_activate()
