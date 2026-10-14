"""Join a call: a session hears the call and speaks into RoomKit Microphone.

roomkit-devices provides the backend (``roomkit_devices.call.CallAudioBackend``) and the
RoomKit Microphone driver. It is no dependency of the app yet: a run overlays the checkout
next door (``uv run --no-sync --with-editable ../roomkit-devices …``), so everything here
imports it lazily and says why the mode is unavailable without it.

The setting (``join_call``) turns the feature on; then nothing is to pick or switch. The
call is whichever app records from RoomKit Microphone (the user picks it as the microphone in
the call): a session started meanwhile joins it, any other is a conversation here as usual.
The assistant hears that app and the user's microphone, mixed, and speaks into RoomKit
Microphone and the session's output (the user hears it too). The user's voice reaches the
call through ``CallRelay``, open while a call records from RoomKit Microphone, session or
not; RoomKit Microphone carries the sum of both. In headphones the microphone never hears
the assistant, so the session runs without echo cancellation.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def join_call(settings: dict) -> bool:
    """Whether sessions join the call that records from RoomKit Microphone, when one does."""
    return bool(settings.get("join_call"))


def unavailable_reason() -> str | None:
    """Why a call cannot be joined on this install, ``None`` when it can."""
    try:
        import roomkit_devices as rd
    except ImportError:
        return (
            "Joining a call needs roomkit-devices: start the app with "
            "--with-editable ../roomkit-devices."
        )
    if not rd.virtual_microphone_installed():
        return (
            "Joining a call needs RoomKit Microphone: install its driver "
            "(roomkit-devices: scripts/driver.sh install)."
        )
    return None


def virtual_microphone_name() -> str | None:
    """RoomKit Microphone's name, as roomkit-devices reads it from the device; ``None``
    without roomkit-devices or its driver. The assistant speaks into it: a call's microphone,
    never the app's own."""
    try:
        import roomkit_devices as rd

        name = rd.virtual_microphone_name()
    except Exception:
        logger.debug("RoomKit Microphone's name is unknown", exc_info=True)
        return None
    return str(name) if name else None


def call_apps() -> list[tuple[str, str]]:
    """``(bundle ID, name)`` of the apps recording from RoomKit Microphone now, one per app.

    A process working for an app counts as that app: Chrome records through its audio
    helper, and the capture of ``com.google.Chrome`` takes its helpers. Empty without
    roomkit-devices or its driver.
    """
    try:
        import roomkit_devices as rd

        recording = rd.list_virtual_microphone_apps()
        processes = rd.list_audio_apps()
    except Exception:
        logger.debug("The apps recording from RoomKit Microphone are unknown", exc_info=True)
        return []
    names = {p.bundle_id: p.name for p in processes if p.bundle_id and p.name}
    apps: dict[str, str] = {}
    for process in recording:
        bundle = process.app_bundle_id or process.bundle_id
        if bundle:
            apps[bundle] = names.get(bundle) or bundle.rsplit(".", 1)[-1]
    return sorted(apps.items(), key=lambda item: item[1].lower())


def in_call() -> bool:
    """Whether an app records from RoomKit Microphone now: cheap enough to poll."""
    try:
        import roomkit_devices as rd

        return bool(rd.list_virtual_microphone_apps())
    except Exception:
        logger.debug("Whether a call is on is unknown", exc_info=True)
        return False


def find_call(settings: dict) -> list[tuple[str, str]]:
    """The call a session joins (``call_apps``). Empty, for a conversation here, when joining
    calls is off or unavailable, or no call records from RoomKit Microphone. Raises when a
    call is on but macOS will not let the app hear it: the user is in that call."""
    if not join_call(settings):
        return []
    reason = unavailable_reason()
    if reason is not None:
        logger.warning("Join a call is on, but unavailable: %s", reason)
        return []
    apps = call_apps()
    if apps:
        import roomkit_devices as rd

        if rd.audio_capture_permission() == "denied":
            raise RuntimeError(
                "macOS refuses this app the system audio: allow it in System Settings → "
                "Privacy & Security → Screen & System Audio Recording, then restart it."
            )
    return apps


def build_call_backend(
    settings: dict,
    apps: list[tuple[str, str]],
    *,
    relayed: bool,
    input_sample_rate: int,
    output_sample_rate: int,
    block_duration_ms: int,
    source: Any = None,
) -> Any:
    """The session's backend for the call in *apps* (``find_call``).

    *relayed*: ``CallRelay`` carries the user's voice already; otherwise the backend relays
    it for the session. The user hears the assistant on the session's output too.
    """
    from roomkit_devices.call import CallAudioBackend

    output = settings.get("output_device")
    return CallAudioBackend(
        app_bundle_ids=[bundle for bundle, _ in apps],
        input_sample_rate=input_sample_rate,
        output_sample_rate=output_sample_rate,
        block_duration_ms=block_duration_ms,
        input_device=settings.get("input_device"),
        mic_source=source,
        passthrough=not relayed,
        monitor=True if output is None else output,
    )


def call_notice(apps: list[tuple[str, str]]) -> str:
    """What the chat says when a session joins the call."""
    names = ", ".join(name for _, name in apps)
    return (
        f"Joined the call in {names}: the assistant hears it and you, and speaks into it; "
        "you hear it here too. Wear headphones: on speakers, the call hears it twice."
    )


class CallRelay:
    """The user's voice in the call: open while joining calls is on and a call records from
    RoomKit Microphone, session or not; closed otherwise, so the microphone is not held.

    RoomKit Microphone carries only what is played into it: without this relay, the call
    loses the user whenever no session runs. A session's own RoomKit Microphone (the
    assistant's voice) adds to it. Muted, the call stops hearing the user, and still hears
    the assistant. The owner calls ``poll`` every second or so.
    """

    def __init__(self) -> None:
        self._microphone: Any = None
        self._enabled = False

    @property
    def running(self) -> bool:
        return self._microphone is not None

    def apply(self, settings: dict) -> None:
        """Turn the relay on or off as *settings* say; ``poll`` opens it once a call is on."""
        self._enabled = join_call(settings) and unavailable_reason() is None
        if not self._enabled:
            self.close()
        self.poll()

    def poll(self) -> None:
        """Open the relay while a call records from RoomKit Microphone, close it after."""
        if not self._enabled:
            return
        call = in_call()
        if call and self._microphone is None:
            self._open()
        elif not call and self._microphone is not None:
            logger.info("The call left RoomKit Microphone: your microphone is released")
            self.close()

    def _open(self) -> None:
        import roomkit_devices as rd

        microphone = rd.VirtualMicrophone(passthrough=True)
        try:
            microphone.start()
        except Exception:
            logger.warning("Your microphone is not relayed into the call", exc_info=True)
            return
        self._microphone = microphone
        logger.info("Relaying %s into RoomKit Microphone", microphone.passthrough_device)

    def set_muted(self, muted: bool) -> None:
        if self._microphone is not None:
            self._microphone.passthrough_muted = muted

    @property
    def muted(self) -> bool:
        return self._microphone is not None and bool(self._microphone.passthrough_muted)

    def close(self) -> None:
        microphone, self._microphone = self._microphone, None
        if microphone is not None:
            microphone.stop()
