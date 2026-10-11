"""Wake-word lifetime: the shared microphone runs only while it is needed."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QObject, Signal

from roomkit_ui.wakeword.controller import WakeWordController


class FakeEngine:
    def __init__(self) -> None:
        self.capture_source = None

    def set_capture_source(self, source) -> None:
        self.capture_source = source


class FakeSource:
    sample_rate = 24000

    def __init__(self, settings: dict) -> None:
        self.settings = settings
        self.running = False
        self.starts = 0
        self.closed = False

    def start(self) -> None:
        self.running = True
        self.starts += 1

    def stop(self) -> None:
        self.running = False

    def close(self) -> None:
        self.running = False
        self.closed = True


class FakeListener(QObject):
    detected = Signal(object, float)
    error = Signal(str)

    def __init__(self, settings: dict, source) -> None:
        super().__init__()
        self.settings = settings
        self.source = source
        self.enabled = False
        self.suspended_by: set[str] = set()
        self.closed = False

    @property
    def listening(self) -> bool:
        return self.enabled and not self.suspended_by and not self.closed

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled

    def suspend(self, reason: str) -> None:
        self.suspended_by.add(reason)

    def resume(self, reason: str) -> None:
        self.suspended_by.discard(reason)

    def close(self) -> None:
        self.closed = True


class World:
    def __init__(self) -> None:
        self.engine = FakeEngine()
        self.sources: list[FakeSource] = []
        self.listeners: list[FakeListener] = []
        self.can_listen = True

    def build_source(self, settings: dict) -> FakeSource:
        source = FakeSource(settings)
        self.sources.append(source)
        return source

    def build_listener(self, settings: dict, source) -> FakeListener | None:
        if not self.can_listen:
            return None
        listener = FakeListener(settings, source)
        self.listeners.append(listener)
        return listener

    def controller(self) -> WakeWordController:
        return WakeWordController(
            self.engine, build_source=self.build_source, build_listener=self.build_listener
        )


ENABLED = {"wakeword_enabled": True}
DISABLED = {"wakeword_enabled": False}


@pytest.fixture
def world(qapp):
    return World()


def test_disabled_at_launch_never_opens_the_device(world):
    wake = world.controller()
    wake.apply(DISABLED)
    assert not any(s.running for s in world.sources)
    assert world.engine.capture_source is None


def test_enabled_at_launch_captures_and_shares_the_device(world):
    wake = world.controller()
    wake.apply(ENABLED)
    source = world.sources[0]
    assert source.running
    assert world.engine.capture_source is source
    assert wake.listening


def test_missing_prerequisites_never_open_the_device(world):
    world.can_listen = False
    wake = world.controller()
    wake.apply(ENABLED)
    assert not any(s.running for s in world.sources)
    assert world.engine.capture_source is None


def test_disabling_releases_the_device(world):
    """Before: the device kept capturing (and the mic indicator lit) until quit."""
    wake = world.controller()
    wake.apply(ENABLED)
    wake.apply(DISABLED)

    assert not world.sources[0].running
    assert world.engine.capture_source is None  # sessions open their own device
    assert not wake.listening


def test_re_enabling_captures_again(world):
    wake = world.controller()
    wake.apply(ENABLED)
    wake.apply(DISABLED)
    wake.apply(ENABLED)

    source = world.sources[0]
    assert source.running and source.starts == 2
    assert world.engine.capture_source is source
    assert wake.listening


def test_disabling_mid_session_waits_for_the_session_to_end(world):
    """The running session is subscribed: stopping now would cut its mic."""
    wake = world.controller()
    wake.apply(ENABLED)
    wake.suspend("session")
    wake.apply(DISABLED)

    assert world.sources[0].running

    wake.resume("session")
    assert not world.sources[0].running
    assert world.engine.capture_source is None  # the next session opens its own


def test_re_enabling_mid_session_cancels_the_pending_release(world):
    wake = world.controller()
    wake.apply(ENABLED)
    wake.suspend("session")
    wake.apply(DISABLED)
    wake.apply(ENABLED)
    wake.resume("session")

    assert world.sources[0].running
    assert world.engine.capture_source is world.sources[0]


# -- settings apply once saved ----------------------------------------------


def test_enabling_after_a_disabled_launch_arms_it(world):
    """Before: disabled at launch, nothing was built until a restart."""
    wake = world.controller()
    wake.apply(DISABLED)
    wake.apply(ENABLED)

    assert wake.listening
    assert world.sources[-1].running


def test_a_new_sensitivity_rebuilds_the_listener(world):
    """Before: only enable/disable reached the listener; the rest waited."""
    wake = world.controller()
    wake.apply({**ENABLED, "wakeword_sensitivity": "balanced"})
    wake.apply({**ENABLED, "wakeword_sensitivity": "cautious"})

    old, new = world.listeners
    assert old.closed
    assert new.settings["wakeword_sensitivity"] == "cautious"
    assert wake.listening


def test_a_rebuild_keeps_the_device_when_it_did_not_change(world):
    wake = world.controller()
    wake.apply(ENABLED)
    wake.apply({**ENABLED, "wakeword_sensitivity": "responsive"})

    assert len(world.sources) == 1
    assert world.sources[0].starts == 1
    assert world.listeners[-1].source is world.sources[0]


def test_another_microphone_reopens_the_device(world):
    wake = world.controller()
    wake.apply({**ENABLED, "input_device": 1})
    wake.apply({**ENABLED, "input_device": 4})

    old, new = world.sources
    assert old.closed
    assert new.running and new.settings["input_device"] == 4
    assert world.engine.capture_source is new


def test_settings_saved_mid_session_apply_when_it_ends(world):
    wake = world.controller()
    wake.apply(ENABLED)
    wake.suspend("session")
    wake.apply({**ENABLED, "wakeword_sensitivity": "cautious"})

    assert len(world.listeners) == 1

    wake.resume("session")
    assert world.listeners[-1].settings["wakeword_sensitivity"] == "cautious"
    assert wake.listening


def test_deaf_while_settings_is_open(world):
    """Before: re-recording the phrase in the wizard opened a session."""
    wake = world.controller()
    wake.apply(ENABLED)
    wake.suspend("settings")
    assert not wake.listening

    # Saving rebuilds the listener; it must still be deaf until the resume.
    wake.apply({**ENABLED, "wakeword_sensitivity": "cautious"})
    assert not wake.listening

    wake.resume("settings")
    assert wake.listening


def test_quit_closes_the_device_and_the_listener(world):
    """Before: nothing ever closed the shared source."""
    wake = world.controller()
    wake.apply(ENABLED)
    wake.close()

    assert world.sources[0].closed
    assert world.listeners[0].closed
    assert world.engine.capture_source is None


def test_detection_hands_over_the_replay_mark(world):
    wake = world.controller()
    wake.apply(ENABLED)
    marks = []
    wake.detected.connect(marks.append)

    world.listeners[0].detected.emit("mark-1", 0.04)

    assert marks == ["mark-1"]


def test_a_device_that_fails_to_open_is_reported_not_fatal(world):
    """This runs from main() at launch: an exception here killed the app."""

    class BrokenSource(FakeSource):
        def start(self) -> None:
            raise OSError("device unavailable")

    world.build_source = BrokenSource
    wake = world.controller()
    errors: list[str] = []
    wake.error.connect(errors.append)

    wake.apply(ENABLED)

    assert errors and "device unavailable" in errors[0]
    assert world.engine.capture_source is None


def test_the_real_source_is_built_stopped():
    """The controller decides when the device opens, not the factory."""
    pytest.importorskip("roomkit.voice.capture")
    from roomkit_ui.wakeword.controller import build_capture_source

    source = build_capture_source({"provider": "gemini", "input_device": None})

    assert source is not None
    assert source._stream is None
