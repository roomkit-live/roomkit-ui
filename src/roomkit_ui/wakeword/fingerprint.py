"""The enrolled voice fingerprint: prototypes, decoys, and the threshold.

The user records their phrase a few times; those recordings *are* the
model.  Nothing is trained — the examples become prototypes in a
representation space learned elsewhere, which is why enrolment takes
seconds instead of the 90 minutes a custom wake-word model needs.

Two findings from measurement shape this file:

* Prototypes must cover the **conditions of use**.  A fingerprint
  enrolled only at arm's length misses the same phrase spoken from two
  metres away — that miss scored worse than a different first name.
* The threshold must be **measured, not guessed**.  Derived from the
  positives alone it sits too loose and lets neighbours through; placed
  between the worst positive and the closest decoy, it separates.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from roomkit_ui.wakeword.dtw import distance_to_prototypes, dtw_distance

logger = logging.getLogger(__name__)

# Fallback when no decoy was recorded: the threshold can only be inferred
# from how much the user's own repetitions vary.
_BLIND_MARGIN = 1.3
# When positives and decoys overlap, favour precision — a false wake opens
# a session behind the user's back, a missed one costs a repeat.
_OVERLAP_MARGIN = 0.9
_MIN_PROTOTYPES = 3


@dataclass
class Fingerprint:
    """An enrolled wake phrase: what to match, and how close is close enough."""

    label: str
    prototypes: list[np.ndarray] = field(default_factory=list)
    decoys: list[np.ndarray] = field(default_factory=list)
    threshold: float = 0.0

    @property
    def usable(self) -> bool:
        return len(self.prototypes) >= _MIN_PROTOTYPES and self.threshold > 0.0

    def distance(self, embedding: np.ndarray) -> float:
        """How far *embedding* sits from this fingerprint."""
        return distance_to_prototypes(embedding, self.prototypes)

    def matches(self, embedding: np.ndarray) -> tuple[bool, float]:
        """``(triggered, distance)`` for one candidate segment."""
        d = self.distance(embedding)
        return d <= self.threshold, d


@dataclass
class Calibration:
    """What the threshold was derived from — shown to the user, not hidden."""

    threshold: float
    worst_positive: float
    closest_decoy: float
    overlapping: bool

    @property
    def margin(self) -> float:
        return self.closest_decoy - self.worst_positive


def calibrate(prototypes: list[np.ndarray], decoys: list[np.ndarray]) -> Calibration:
    """Place the threshold between the enrolled phrase and its decoys.

    ``worst_positive`` is leave-one-out: each prototype scored against
    the others, so it reflects what an unseen utterance would score
    rather than a prototype's distance to itself (which is zero).
    """
    n = len(prototypes)
    worst_positive = 0.0
    if n > 1:
        worst_positive = max(
            min(dtw_distance(prototypes[i], prototypes[j]) for j in range(n) if j != i)
            for i in range(n)
        )

    if not decoys:
        return Calibration(
            threshold=round(worst_positive * _BLIND_MARGIN, 4),
            worst_positive=worst_positive,
            closest_decoy=float("inf"),
            overlapping=False,
        )

    closest_decoy = min(distance_to_prototypes(d, prototypes) for d in decoys)
    overlapping = closest_decoy <= worst_positive
    if overlapping:
        threshold = closest_decoy * _OVERLAP_MARGIN
    else:
        threshold = (worst_positive + closest_decoy) / 2.0
    return Calibration(
        threshold=round(threshold, 4),
        worst_positive=worst_positive,
        closest_decoy=closest_decoy,
        overlapping=overlapping,
    )


def outlier_prototypes(prototypes: list[np.ndarray], durations: list[float]) -> list[int]:
    """Indices of enrolment takes that should be re-recorded.

    Catches the case where the VAD captured a stray word or the user said
    the phrase twice in one breath: such a take poisons the fingerprint
    and, unnoticed, drags the threshold with it.
    """
    if len(durations) < 3:
        return []
    median = float(np.median(durations))
    return [i for i, d in enumerate(durations) if d < median * 0.6 or d > median * 1.5]


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def storage_dir() -> Path:
    """Where fingerprints live (created on demand)."""
    path = Path.home() / ".local" / "share" / "roomkit-ui" / "wakeword"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _paths() -> tuple[Path, Path]:
    root = storage_dir()
    return root / "fingerprint.npz", root / "fingerprint.json"


def save(fingerprint: Fingerprint) -> None:
    """Persist a fingerprint, replacing any previous one."""
    arrays_path, meta_path = _paths()
    arrays: dict[str, Any] = {f"p{i}": m for i, m in enumerate(fingerprint.prototypes)}
    arrays.update({f"d{i}": m for i, m in enumerate(fingerprint.decoys)})
    np.savez_compressed(arrays_path, **arrays)
    meta_path.write_text(
        json.dumps(
            {
                "label": fingerprint.label,
                "threshold": fingerprint.threshold,
                "prototypes": len(fingerprint.prototypes),
                "decoys": len(fingerprint.decoys),
                "version": 1,
            },
            indent=2,
        )
    )
    logger.info(
        "Wake word fingerprint saved: %r (%d prototypes, %d decoys, threshold %.4f)",
        fingerprint.label,
        len(fingerprint.prototypes),
        len(fingerprint.decoys),
        fingerprint.threshold,
    )


def load() -> Fingerprint | None:
    """Load the stored fingerprint, or ``None`` when none is enrolled."""
    arrays_path, meta_path = _paths()
    if not arrays_path.is_file() or not meta_path.is_file():
        return None
    try:
        meta = json.loads(meta_path.read_text())
        data = np.load(arrays_path)
        return Fingerprint(
            label=meta.get("label", ""),
            prototypes=[data[f"p{i}"] for i in range(meta.get("prototypes", 0))],
            decoys=[data[f"d{i}"] for i in range(meta.get("decoys", 0))],
            threshold=float(meta.get("threshold", 0.0)),
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        logger.exception("Wake word fingerprint unreadable — treating as not enrolled")
        return None


def clear() -> None:
    """Forget the enrolled phrase."""
    for path in _paths():
        path.unlink(missing_ok=True)
