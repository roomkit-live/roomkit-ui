"""The wake word's lifetime: the shared microphone and the listener on it.

A shared capture source holds the device open for as long as it runs — the
system's microphone indicator stays lit — so it runs only while the wake
word is enabled.  Sessions take their audio from it while it does, which is
what lets them replay the words spoken before they existed; when it does
not, they open the device themselves.

Nothing here stops the device from inside the capture drain: every path
that releases it is driven by a setting being saved, a session ending or
the application quitting (see ``SegmentCapture.stop`` for why).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, Signal

logger = logging.getLogger(__name__)

SourceFactory = Callable[[dict], Any]
ListenerFactory = Callable[[dict, Any], Any]

# A session subscribed to the shared source: stopping it would cut that
# session's microphone mid-call.
_SESSION = "session"


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
        self._source_running = False
        self._listener: Any = None
        self._suspended_by: set[str] = set()
        self._release_pending = False

    @property
    def listening(self) -> bool:
        return self._listener is not None and self._listener.listening

    @property
    def capturing(self) -> bool:
        """Whether the shared source currently holds the device."""
        return self._source_running

    # -- configuration -------------------------------------------------------

    def start(self, settings: dict) -> None:
        """Build what the settings ask for at launch."""
        if not settings.get("wakeword_enabled", False):
            return
        # Built stopped: the device opens only once the listener exists.
        source = self._build_source(settings)
        listener = self._build_listener(settings, source)
        if listener is None:
            return
        self._source = source
        self._acquire_source()
        self._adopt(listener)

    def set_enabled(self, enabled: bool) -> None:
        """Arm or disarm, releasing the device while disarmed."""
        if self._listener is None:
            return
        if enabled:
            self._acquire_source()
            self._listener.set_enabled(True)
        else:
            self._listener.set_enabled(False)
            self._release_source()

    def _adopt(self, listener: Any) -> None:
        listener.detected.connect(lambda mark, _distance: self.detected.emit(mark))
        listener.error.connect(self.error)
        for reason in self._suspended_by:
            listener.suspend(reason)
        listener.set_enabled(True)
        self._listener = listener

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
        if reason == _SESSION and self._release_pending:
            self._release_source()

    # -- the shared device ---------------------------------------------------

    def _acquire_source(self) -> None:
        self._release_pending = False
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
        if _SESSION in self._suspended_by:
            self._release_pending = True
            return
        self._release_pending = False
        if self._source_running:
            self._source.stop()
            self._source_running = False
            logger.info("Wake word off — shared microphone released")

    def close(self) -> None:
        """Release everything (application quit)."""
        if self._listener is not None:
            self._listener.close()
        if self._source is not None:
            self._engine.set_capture_source(None)
            self._source.close()
            self._source_running = False
        self._release_pending = False


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

    from roomkit_ui.engine_realtime import _realtime_sample_rate

    # The source owns the input format and refuses a conflicting one, so it
    # must match the transport the configured provider will ask for.
    rate = _realtime_sample_rate(str(settings.get("provider", "gemini")))
    source = LocalMicSource(
        input_device=settings.get("input_device"),
        sample_rate=rate,
        backlog_seconds=10,
    )
    return source


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
