"""Join a call: availability, the call found, the backend a session gets, the relay."""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from roomkit_ui import call_mode


def process(bundle: str | None, name: str, app: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(bundle_id=bundle, name=name, app_bundle_id=app)


CHROME = process("com.google.Chrome", "Google Chrome")
CHROME_HELPER = process("com.google.Chrome.helper", "Google Chrome Helper", "com.google.Chrome")
ZOOM = process("us.zoom.xos", "zoom.us")


@pytest.fixture
def devices(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """A fake roomkit_devices: installed driver, granted permission, Chrome in a call."""
    state = SimpleNamespace(
        installed=True,
        permission="granted",
        audio=[CHROME, CHROME_HELPER, ZOOM, process("systemsoundserverd", "")],
        recording=[CHROME_HELPER],
        backend_kwargs=None,
        microphones=[],
        start_error=None,
    )
    rd = ModuleType("roomkit_devices")
    rd.virtual_microphone_installed = lambda: state.installed  # type: ignore[attr-defined]
    rd.audio_capture_permission = lambda: state.permission  # type: ignore[attr-defined]
    rd.list_audio_apps = lambda: state.audio  # type: ignore[attr-defined]
    rd.list_virtual_microphone_apps = lambda: state.recording  # type: ignore[attr-defined]
    rd.virtual_microphone_name = lambda: (  # type: ignore[attr-defined]
        "RoomKit Mic" if state.installed else None
    )

    class VirtualMicrophone:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs
            self.started = self.stopped = False
            self.passthrough_muted = False
            self.passthrough_device = "Micro MacBook Pro"
            state.microphones.append(self)

        def start(self) -> None:
            if state.start_error is not None:
                raise state.start_error
            self.started = True

        def stop(self) -> None:
            self.stopped = True

    rd.VirtualMicrophone = VirtualMicrophone  # type: ignore[attr-defined]
    call = ModuleType("roomkit_devices.call")

    class CallAudioBackend:
        def __init__(self, **kwargs: Any) -> None:
            state.backend_kwargs = kwargs

    call.CallAudioBackend = CallAudioBackend  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "roomkit_devices", rd)
    monkeypatch.setitem(sys.modules, "roomkit_devices.call", call)
    return state


def test_off_by_default() -> None:
    from roomkit_ui.settings import _DEFAULTS

    assert _DEFAULTS["join_call"] is False
    assert not call_mode.join_call({})
    assert call_mode.join_call({"join_call": True})


ON = {"join_call": True}


def test_without_roomkit_devices_says_how_to_get_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "roomkit_devices", None)
    reason = call_mode.unavailable_reason()
    assert reason is not None and "--with-editable ../roomkit-devices" in reason
    assert call_mode.call_apps() == [] and not call_mode.in_call()
    assert call_mode.find_call(ON) == []  # a conversation here


def test_without_the_driver_says_how_to_install_it(devices: SimpleNamespace) -> None:
    devices.installed = False
    reason = call_mode.unavailable_reason()
    assert reason is not None and "driver.sh install" in reason
    assert call_mode.find_call(ON) == []


def test_the_call_is_the_app_recording_from_roomkit_microphone(devices: SimpleNamespace) -> None:
    assert call_mode.unavailable_reason() is None
    assert call_mode.in_call()
    # Chrome records through its audio helper: the call is Chrome.
    assert call_mode.find_call(ON) == [("com.google.Chrome", "Google Chrome")]
    devices.recording = [CHROME_HELPER, ZOOM]
    assert call_mode.call_apps() == [
        ("com.google.Chrome", "Google Chrome"),
        ("us.zoom.xos", "zoom.us"),
    ]


def test_off_or_without_a_call_live_is_a_conversation_here(devices: SimpleNamespace) -> None:
    assert call_mode.find_call({}) == []  # off: a call using RoomKit Microphone is ignored
    devices.recording = []
    assert not call_mode.in_call()
    assert call_mode.find_call(ON) == []


def test_in_a_call_a_refused_permission_fails_the_start(devices: SimpleNamespace) -> None:
    devices.permission = "denied"
    with pytest.raises(RuntimeError, match="Screen & System Audio Recording"):
        call_mode.find_call(ON)
    devices.recording = []
    assert call_mode.find_call(ON) == []  # no call: nothing to hear, nothing refused


@pytest.mark.parametrize("relayed", [True, False])
def test_the_backend_hears_the_call_and_relays_the_voice_unless_the_app_does(
    devices: SimpleNamespace, relayed: bool
) -> None:
    source = object()
    call_mode.build_call_backend(
        {"input_device": 3, "output_device": 3 if relayed else None},
        [("com.google.Chrome", "Google Chrome")],
        relayed=relayed,
        input_sample_rate=16000,
        output_sample_rate=24000,
        block_duration_ms=20,
        source=source,
    )
    assert devices.backend_kwargs == {
        "app_bundle_ids": ["com.google.Chrome"],
        "input_sample_rate": 16000,
        "output_sample_rate": 24000,
        "block_duration_ms": 20,
        "input_device": 3,
        "mic_source": source,
        "passthrough": not relayed,
        "monitor": 3 if relayed else True,
    }


def test_the_notice_names_the_apps() -> None:
    notice = call_mode.call_notice([("com.google.Chrome", "Google Chrome")])
    assert "Google Chrome" in notice and "headphones" in notice


def test_the_relay_runs_while_a_call_uses_roomkit_microphone(devices: SimpleNamespace) -> None:
    relay = call_mode.CallRelay()
    relay.apply({"join_call": False})
    assert not relay.running and devices.microphones == []  # off: never, call or not

    devices.recording = []
    relay.apply(ON)
    assert not relay.running  # on, no call: the microphone is not held

    devices.recording = [CHROME_HELPER]  # the user joins a call with RoomKit Microphone
    relay.poll()
    assert relay.running
    (microphone,) = devices.microphones
    assert microphone.kwargs == {"passthrough": True} and microphone.started
    relay.poll()
    relay.apply(ON)  # saved again: the same relay, never a gap
    assert devices.microphones == [microphone]

    relay.set_muted(True)
    assert relay.muted and microphone.passthrough_muted
    relay.set_muted(False)
    assert not relay.muted

    devices.recording = []  # the call ends
    relay.poll()
    assert not relay.running and microphone.stopped

    devices.recording = [CHROME_HELPER]
    relay.poll()
    assert relay.running
    relay.apply({"join_call": False})  # switched off mid-call
    assert not relay.running and devices.microphones[-1].stopped
    relay.close()  # closing twice is harmless


def test_a_relay_that_cannot_open_leaves_the_voice_to_the_session(
    devices: SimpleNamespace,
) -> None:
    relay = call_mode.CallRelay()
    devices.installed = False
    relay.apply(ON)
    relay.poll()
    assert not relay.running and devices.microphones == []

    devices.installed = True
    devices.start_error = RuntimeError("device busy")
    relay.apply(ON)
    assert not relay.running
    relay.set_muted(True)  # nothing to mute: no error
    assert not relay.muted


@pytest.mark.parametrize("relay_on", [True, False])
def test_a_session_joins_the_call_and_leaves_the_voice_to_the_relay(
    devices: SimpleNamespace, qapp: Any, relay_on: bool
) -> None:
    from roomkit_ui.engine import Engine

    engine = Engine()
    relay = call_mode.CallRelay()
    devices.recording = []  # the relay is not open yet when the session starts
    relay.apply({"join_call": relay_on})
    engine.set_call_relay(relay)
    devices.recording = [CHROME_HELPER]

    assert engine._find_call(ON)
    assert relay.running is relay_on  # opened for the session, not a poll later
    assert engine.in_call
    engine._build_vc_backend(ON, aec=None, output_sample_rate=24000)

    assert devices.backend_kwargs["app_bundle_ids"] == ["com.google.Chrome"]
    assert devices.backend_kwargs["passthrough"] is not relay_on
    engine._forget_session()
    assert not engine.in_call


def test_without_a_call_a_session_is_a_conversation_here(
    devices: SimpleNamespace, qapp: Any
) -> None:
    from roomkit_ui.engine import Engine

    engine = Engine()
    devices.recording = []
    assert not engine._find_call(ON)
    from roomkit.voice.backends.local import LocalAudioBackend

    backend = engine._build_vc_backend(ON, aec=None, output_sample_rate=24000)
    assert devices.backend_kwargs is None
    assert isinstance(backend, LocalAudioBackend)  # the speakers and the microphone


def test_roomkit_microphone_is_no_microphone_for_the_app(
    devices: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sounddevice as sd

    from roomkit_ui.widgets.settings.audio_processing import _list_audio_devices

    listed = [
        {"name": "Micro MacBook Pro", "max_input_channels": 1, "max_output_channels": 0},
        # Named as the driver names it, whatever that is: the name comes from the library.
        {"name": "RoomKit Mic", "max_input_channels": 1, "max_output_channels": 0},
        {"name": "Haut-parleurs MacBook Pro", "max_input_channels": 0, "max_output_channels": 2},
    ]
    monkeypatch.setattr(sd, "query_devices", lambda: listed)
    inputs, outputs = _list_audio_devices()
    assert inputs == [(0, "Micro MacBook Pro")]
    assert outputs == [(2, "Haut-parleurs MacBook Pro")]

    devices.installed = False  # no driver, nothing to leave out
    assert call_mode.virtual_microphone_name() is None
    assert len(_list_audio_devices()[0]) == 2


@pytest.mark.parametrize("on", [False, True])
def test_the_switch_is_greyed_without_roomkit_devices(
    monkeypatch: pytest.MonkeyPatch, qapp: Any, on: bool
) -> None:
    from PySide6.QtWidgets import QLabel

    from roomkit_ui.widgets.settings.audio_processing import AudioSettings

    monkeypatch.setitem(sys.modules, "roomkit_devices", None)
    page = AudioSettings({"join_call": on}, ([], []))
    # Greyed, saying why; still switchable off when it was on.
    assert page.join_call.isEnabled() is on
    assert page.join_call.isChecked() is on
    texts = [label.text() for label in page.findChildren(QLabel)]
    assert any("needs roomkit-devices" in text for text in texts)


def test_the_switch_is_live_with_roomkit_devices(devices: SimpleNamespace, qapp: Any) -> None:
    from roomkit_ui.widgets.settings.audio_processing import AudioSettings

    page = AudioSettings({}, ([], []))
    assert page.join_call.isEnabled() and not page.join_call.isChecked()
    page.join_call.setChecked(True)
    assert page.get_settings()["join_call"] is True
