"""Wake-word detection: listen locally, open a provider session on demand.

The user enrols a phrase by saying it a few times; those recordings
become the fingerprint.  Detection compares sound to sound — no
transcription, so the phrase works in any language and its spelling is
only a label.
"""

from roomkit_ui.wakeword.detector import Detection, EmbeddingWakeDetector, WakeDetector
from roomkit_ui.wakeword.fingerprint import (
    Calibration,
    Fingerprint,
    calibrate,
    clear,
    load,
    outlier_prototypes,
    save,
)

__all__ = [
    "Calibration",
    "Detection",
    "EmbeddingWakeDetector",
    "Fingerprint",
    "WakeDetector",
    "calibrate",
    "clear",
    "load",
    "outlier_prototypes",
    "save",
]
