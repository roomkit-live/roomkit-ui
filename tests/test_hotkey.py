"""Hotkey matching: a lone modifier tap fires, a chord through it does not."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from roomkit_ui.hotkey import (
    HotkeyListener,
    _KeyMatcher,
    _modifier_tap_handler,
    _ModifierTap,
)


@pytest.fixture
def keys():
    """pynput's key types — only importable where it finds a display backend."""
    keyboard = pytest.importorskip(
        "pynput.keyboard", reason="pynput needs a display backend", exc_type=ImportError
    )
    return SimpleNamespace(Key=keyboard.Key, char=keyboard.KeyCode.from_char)


# -- the tap itself ----------------------------------------------------------


def test_a_lone_tap_fires():
    tap = _ModifierTap()
    tap.press(True)
    assert tap.release(True)


def test_a_key_pressed_while_held_cancels_the_tap():
    tap = _ModifierTap()
    tap.press(True)
    tap.press(False)
    assert not tap.release(True)


def test_auto_repeat_does_not_reset_a_chord():
    tap = _ModifierTap()
    tap.press(True)
    tap.press(False)
    tap.press(True)  # the modifier repeats while held
    assert not tap.release(True)


def test_the_next_tap_after_a_chord_fires_again():
    tap = _ModifierTap()
    tap.press(True)
    tap.press(False)
    tap.release(True)
    tap.press(True)
    assert tap.release(True)


def test_a_key_pressed_before_the_modifier_does_not_cancel():
    tap = _ModifierTap()
    tap.press(False)
    tap.release(False)
    tap.press(True)
    assert tap.release(True)


# -- pynput matcher ----------------------------------------------------------


def _matcher(hotkey: str) -> tuple[_KeyMatcher, list[int]]:
    fired: list[int] = []
    return _KeyMatcher(hotkey, lambda: fired.append(1)), fired


def test_single_modifier_fires_on_a_lone_tap(keys):
    matcher, fired = _matcher("<ctrl>")
    matcher.press(keys.Key.ctrl_r)
    matcher.release(keys.Key.ctrl_r)
    assert fired == [1]


def test_single_modifier_ignores_a_chord(keys):
    """Before: Ctrl+C toggled dictation when the hotkey was <ctrl>."""
    matcher, fired = _matcher("<ctrl>")
    matcher.press(keys.Key.ctrl)
    matcher.press(keys.char("c"))
    matcher.release(keys.char("c"))
    matcher.release(keys.Key.ctrl)
    assert fired == []


def test_combo_still_fires(keys):
    matcher, fired = _matcher("<ctrl>+<shift>+h")
    for key in (keys.Key.ctrl, keys.Key.shift, keys.char("h")):
        matcher.press(key)
    assert fired == [1]


def test_swapping_to_a_single_modifier_starts_from_a_clean_tap(keys):
    matcher, fired = _matcher("<ctrl>")
    matcher.press(keys.Key.ctrl)
    matcher.swap(_KeyMatcher("<shift>"))
    matcher.press(keys.Key.shift)
    matcher.release(keys.Key.shift)
    assert fired == [1]


@pytest.mark.parametrize("hotkey", ["", "<foo>", "<ctrl>+<ctrl>", "<ctrl>+"])
def test_an_unparsable_hotkey_is_invalid_not_an_exception(keys, hotkey):
    """Before: HotKey.parse raised and start() took the app down at launch."""
    assert not _KeyMatcher(hotkey).valid


def test_listener_reports_an_unparsable_hotkey(keys, qapp, monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    listener = HotkeyListener(hotkey="<foo>")
    messages: list[str] = []
    listener.hotkey_invalid.connect(messages.append)

    listener.start()

    assert messages and "<foo>" in messages[0]
    assert listener._listener is None


# -- macOS NSEvent handler ---------------------------------------------------

_FLAGS_CHANGED, _KEY_DOWN = 12, 10
_CMD_MASK = 1 << 20
_CMD_R, _SHIFT_L = 0x36, 0x38


class FakeEvent:
    def __init__(self, kind: int, keycode: int, flags: int = 0) -> None:
        self._kind, self._keycode, self._flags = kind, keycode, flags

    def type(self) -> int:
        return self._kind

    def keyCode(self) -> int:  # noqa: N802 — NSEvent API
        return self._keycode

    def modifierFlags(self) -> int:  # noqa: N802 — NSEvent API
        return self._flags


def _ns_handler() -> tuple[object, list[int]]:
    fired: list[int] = []
    handler = _modifier_tap_handler({_CMD_R}, _CMD_MASK, _FLAGS_CHANGED, lambda: fired.append(1))
    return handler, fired


def test_nsevent_right_cmd_tap_fires():
    handler, fired = _ns_handler()
    handler(FakeEvent(_FLAGS_CHANGED, _CMD_R, _CMD_MASK))
    handler(FakeEvent(_FLAGS_CHANGED, _CMD_R, 0))
    assert fired == [1]


def test_nsevent_right_cmd_c_does_not_fire():
    """Before: with the macOS default <cmd_r>, copying toggled dictation."""
    handler, fired = _ns_handler()
    handler(FakeEvent(_FLAGS_CHANGED, _CMD_R, _CMD_MASK))
    handler(FakeEvent(_KEY_DOWN, 8))  # C
    handler(FakeEvent(_FLAGS_CHANGED, _CMD_R, 0))
    assert fired == []


def test_nsevent_another_modifier_while_held_does_not_fire():
    handler, fired = _ns_handler()
    handler(FakeEvent(_FLAGS_CHANGED, _CMD_R, _CMD_MASK))
    handler(FakeEvent(_FLAGS_CHANGED, _SHIFT_L, _CMD_MASK))
    handler(FakeEvent(_FLAGS_CHANGED, _CMD_R, 0))
    assert fired == []
