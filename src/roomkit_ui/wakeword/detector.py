"""Wake-word detection over VAD segments.

Deliberately behind a protocol: the embedding matcher below is what we
measured as workable today, but a trained keyword-spotting model (250 KB,
higher recall) would slot in here without touching the listener, the
auto-hangup or the settings.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from roomkit_ui.wakeword.features import SAMPLE_RATE, WhisperEmbedder
from roomkit_ui.wakeword.fingerprint import Fingerprint

logger = logging.getLogger(__name__)

# A wake phrase lasts about a second; anything far outside that window is
# someone talking, not a summons.  Bounds are generous — this only skips
# obvious non-candidates before the encoder runs.
_MIN_SECONDS = 0.4
_MAX_SECONDS = 4.0


@dataclass(frozen=True)
class Detection:
    """One decision about one segment of speech."""

    triggered: bool
    distance: float
    threshold: float
    duration: float

    @property
    def confidence(self) -> float:
        """0–1, saturating: 1.0 dead-on, 0.0 at twice the threshold."""
        if self.threshold <= 0:
            return 0.0
        return max(0.0, min(1.0, 2.0 - self.distance / self.threshold))


class WakeDetector(Protocol):
    """Decides whether a speech segment is the wake phrase."""

    @property
    def ready(self) -> bool:
        """Whether the detector can currently decide anything."""
        ...

    def detect(self, pcm: bytes) -> Detection | None:
        """Judge one segment; ``None`` when it isn't a plausible candidate."""
        ...


class EmbeddingWakeDetector:
    """Matches segments against an enrolled fingerprint, by sound alone.

    Carries no transcription: the phrase may be in any language, and the
    spelling the user typed is only ever a display label.
    """

    def __init__(self, encoder_path: str | Path, fingerprint: Fingerprint) -> None:
        self._embedder = WhisperEmbedder(encoder_path)
        self._fingerprint = fingerprint

    @property
    def ready(self) -> bool:
        return self._fingerprint.usable

    @property
    def label(self) -> str:
        return self._fingerprint.label

    def share_embedder(self, embedder: WhisperEmbedder) -> None:
        """Adopt an already-loaded encoder instead of opening a second one.

        The encoder is 12 MB and takes ~200 ms to load; when a caller
        already has one (enrolment handing over to detection), paying that
        twice would land on the user's first attempt.
        """
        self._embedder = embedder

    def warmup(self) -> None:
        """Load the encoder ahead of the first segment.

        Worth calling when arming the listener: the first inference
        otherwise pays session creation, and that latency lands on the
        user's first attempt.
        """
        self._embedder.load()

    def close(self) -> None:
        self._embedder.close()

    def detect(self, pcm: bytes) -> Detection | None:
        if not self.ready:
            return None
        duration = len(pcm) / (SAMPLE_RATE * 2)
        if not _MIN_SECONDS <= duration <= _MAX_SECONDS:
            return None
        try:
            embedding = self._embedder.embed(pcm)
        except (FileNotFoundError, ImportError):
            raise
        except Exception:
            logger.exception("Wake word embedding failed — segment skipped")
            return None
        if len(embedding) == 0:
            return None

        triggered, distance = self._fingerprint.matches(embedding)
        return Detection(
            triggered=triggered,
            distance=distance,
            threshold=self._fingerprint.threshold,
            duration=duration,
        )
