"""The wake word's lifetime: the shared microphone and the listener on it.

A shared capture source holds the device open for as long as it runs — the
system's microphone indicator stays lit — so it runs only while the wake
word is enabled.  Sessions take their audio from it while it does, which is
what lets them replay the words spoken before they existed; when it does
not, they open the device themselves.

Settings apply as soon as they are saved — enabling, sensitivity, a
re-recorded phrase, another microphone — and the listener stands down
while Settings is open, so recording the phrase again cannot wake it.

Nothing here stops the device from inside the capture drain: every path
that releases it is driven by a setting being saved, a session ending or
the application quitting (see ``SegmentCapture.stop`` for why).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, Signal

from roomkit_ui.wakeword.capture import SAMPLE_RATE

logger = logging.getLogger(__name__)

SourceFactory = Callable[[dict], Any]
ListenerFactory = Callable[[dict, Any], Any]

# A session subscribed to the shared source: stopping it would cut that
# session's microphone mid-call.
_SESSION = "session"
# What build_capture_source opens the device with — the input device, and
# the provider whose transport rate the source must match.
_SOURCE_SETTINGS = ("input_device", "provider")


class WakeWordController(QObject):
    """Owns the shared microphone and the listener, and when each runs."""

    detected = Signal(object)  # replay mark on the shared source, or None
    error = Signal(str)

    def __init__(
        self,
        engine: Any,
        *,
        build_source: SourceFactory,
        build_listener: ListenerFactory,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._engine = engine
        self._build_source = build_source
        self._build_listener = build_listener
        self._source: Any = None
        self._source_key: tuple[Any, ...] | None = None
        self._source_running = False
        self._listener: Any = None
        self._suspended_by: set[str] = set()
        self._pending: dict | None = None

    @property
    def listening(self) -> bool:
        return self._listener is not None and self._listener.listening

    @property
    def capturing(self) -> bool:
        """Whether the shared source currently holds the device."""
        return self._source_running

    # -- configuration -------------------------------------------------------

    def apply(self, settings: dict) -> None:
        """Make the wake word match *settings*, at launch or once saved.

        The listener is rebuilt every time — that is what picks up a new
        sensitivity or a re-recorded phrase; the device is reopened only
        when what it was opened with changed.
        """
        if _SESSION in self._suspended_by:
            # The session is subscribed to the source: rebuilding now would
            # cut its microphone mid-call.  Its end applies this.
            self._pending = settings
            return
        self._pending = None
        self._drop_listener()
        if not settings.get("wakeword_enabled", False):
            self._release_source()
            return
        source = self._source_for(settings)
        listener = self._build_listener(settings, source)
        if listener is None:
            self._release_source()
            return
        self._acquire_source()
        self._adopt(listener)

    def _adopt(self, listener: Any) -> None:
        listener.detected.connect(lambda mark, _distance: self.detected.emit(mark))
        listener.error.connect(self.error)
        for reason in self._suspended_by:
            listener.suspend(reason)
        listener.set_enabled(True)
        self._listener = listener

    def _drop_listener(self) -> None:
        if self._listener is not None:
            self._listener.close()
            self._listener = None

    # -- suspensions ---------------------------------------------------------

    def suspend(self, reason: str) -> None:
        """Stand down for *reason* (reference-counted with :meth:`resume`)."""
        self._suspended_by.add(reason)
        if self._listener is not None:
            self._listener.suspend(reason)

    def resume(self, reason: str) -> None:
        self._suspended_by.discard(reason)
        if self._listener is not None:
            self._listener.resume(reason)
        if reason == _SESSION and self._pending is not None:
            self.apply(self._pending)

    # -- the shared device ---------------------------------------------------

    def _source_for(self, settings: dict) -> Any:
        """The source to listen on: the current one, unless its device changed."""
        key = tuple(settings.get(name) for name in _SOURCE_SETTINGS)
        if self._source is not None and key == self._source_key:
            return self._source
        self._close_source()
        self._source = self._build_source(settings)  # built stopped
        self._source_key = key
        return self._source

    def _acquire_source(self) -> None:
        if self._source is None:
            return
        if not self._source_running:
            try:
                self._source.start()
            except Exception as exc:  # a device unplugged since it was chosen
                logger.exception("Wake word: shared microphone failed to open")
                self.error.emit(f"Wake word: the microphone could not be opened ({exc})")
                return
            self._source_running = True
        self._engine.set_capture_source(self._source)

    def _release_source(self) -> None:
        """Stop holding the device; sessions open their own from now on."""
        if self._source is None:
            return
        self._engine.set_capture_source(None)
        if self._source_running:
            self._source.stop()
            self._source_running = False
            logger.info("Wake word off — shared microphone released")

    def _close_source(self) -> None:
        if self._source is None:
            return
        self._engine.set_capture_source(None)
        self._source.close()
        self._source = None
        self._source_key = None
        self._source_running = False

    def close(self) -> None:
        """Release everything (application quit)."""
        self._pending = None
        self._drop_listener()
        self._close_source()


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def build_capture_source(settings: dict) -> Any:
    """Open the shared microphone, when this roomkit provides one.

    Shared so that a session subscribes to a device already capturing,
    instead of the listener handing it back and the session reopening it —
    a gap of a few hundred milliseconds landing exactly while the user is
    still talking.  Returns None on an install without the primitive, where
    everything still works minus the replay.

    The source is returned stopped: the controller starts it, and owns
    when it stops.
    """
    try:
        from roomkit.voice.capture import LocalMicSource
    except ImportError:
        logger.info(
            "roomkit has no shared capture source — the wake word will open its "
            "own device and speech before the session will not be replayed"
        )
        return None

    return LocalMicSource(
        input_device=settings.get("input_device"),
        sample_rate=capture_rate(settings),
        backlog_seconds=10,
    )


def capture_rate(settings: dict) -> int:
    """The rate the wake word hears the microphone at.

    The shared source owns the input format and refuses a conflicting one,
    so it runs at the rate the configured provider's transport asks for.
    Enrolment records at this rate too, so its takes are converted to
    16 kHz exactly as detection's audio will be.  Without the shared
    source the listener opens the device at 16 kHz itself.
    """
    try:
        import roomkit.voice.capture  # noqa: F401
    except ImportError:
        return SAMPLE_RATE

    from roomkit_ui.engine_realtime import _realtime_sample_rate

    return _realtime_sample_rate(str(settings.get("provider", "gemini")))


def build_listener(settings: dict, source: Any) -> Any:
    """Assemble the wake-word listener, or None when it cannot run."""
    from roomkit_ui.features import is_available
    from roomkit_ui.model_catalog import (
        is_vad_model_downloaded,
        is_wakeword_encoder_downloaded,
        vad_model_path,
        wakeword_encoder_path,
    )
    from roomkit_ui.wakeword import load as load_fingerprint
    from roomkit_ui.wakeword.detector import EmbeddingWakeDetector
    from roomkit_ui.wakeword.listener import WakeWordListener
    from roomkit_ui.wakeword.page_sensitivity import apply_sensitivity

    if not is_available("wakeword") or not is_vad_model_downloaded("ten-vad"):
        logger.warning("Wake word enabled but its dependencies are missing — skipping")
        return None
    if not is_wakeword_encoder_downloaded():
        logger.warning("Wake word enabled but the encoder is not downloaded — skipping")
        return None

    fingerprint = load_fingerprint()
    if fingerprint is None or not fingerprint.usable:
        logger.warning("Wake word enabled but no phrase is enrolled — skipping")
        return None

    apply_sensitivity(fingerprint, str(settings.get("wakeword_sensitivity", "balanced")))
    detector = EmbeddingWakeDetector(str(wakeword_encoder_path()), fingerprint)
    logger.info("Wake word armed: %r", fingerprint.label)
    return WakeWordListener(
        detector,
        str(vad_model_path("ten-vad") / "ten-vad.int8.onnx"),
        input_device=settings.get("input_device"),
        source=source,
    )
