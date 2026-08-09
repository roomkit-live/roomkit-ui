"""Apply the user's sensitivity choice to a measured threshold.

Enrolment measures a threshold from the phrase and its decoys.  This
scales it by what the user asked for, rather than exposing a raw
distance in the settings — nobody can reason about 0.0823.
"""

from __future__ import annotations

import logging

from roomkit_ui.wakeword.fingerprint import Fingerprint

logger = logging.getLogger(__name__)

# Named by the experience, not the multiplier.  The span reflects what
# measurement showed: tight enough to reject a close first name, or loose
# enough to always answer at the cost of the occasional near-miss.
FACTORS: dict[str, float] = {
    "cautious": 0.85,
    "balanced": 1.0,
    "responsive": 1.5,
}


def apply_sensitivity(fingerprint: Fingerprint, sensitivity: str) -> float:
    """Scale *fingerprint*'s threshold in place; returns the new value."""
    factor = FACTORS.get(sensitivity)
    if factor is None:
        logger.warning("Unknown wake word sensitivity %r — using balanced", sensitivity)
        factor = 1.0
    if factor != 1.0:
        fingerprint.threshold = round(fingerprint.threshold * factor, 4)
    return fingerprint.threshold
