"""Dynamic Time Warping between two sequences of acoustic frames.

Wake-word detection compares one utterance against enrolled prototypes,
and two utterances of the same phrase never share a duration — the user
speaks faster when in a hurry.  DTW stretches the time axis to align
them, which is exactly what a fingerprint comparison (Shazam-style)
cannot do: that one matches an identical signal, this one matches the
same *phrase* spoken differently.
"""

from __future__ import annotations

import numpy as np


def dtw_distance(a: np.ndarray, b: np.ndarray) -> float:
    """Path-normalised DTW distance between two ``(frames, dims)`` arrays.

    Frames are compared by cosine distance, then aligned by dynamic
    programming.  The result is divided by the path length so that
    longer utterances don't score worse merely for being longer.

    Returns ``inf`` when either sequence is empty; ``0.0`` for identical
    input.  Typical values with the whisper encoder: ~0.05 for the same
    phrase by the same speaker, ~0.5 for unrelated speech.
    """
    if len(a) == 0 or len(b) == 0:
        return float("inf")

    an = a / np.maximum(np.linalg.norm(a, axis=1, keepdims=True), 1e-8)
    bn = b / np.maximum(np.linalg.norm(b, axis=1, keepdims=True), 1e-8)
    cost = 1.0 - an @ bn.T

    n, m = cost.shape
    acc = np.full((n + 1, m + 1), np.inf, dtype=np.float32)
    acc[0, 0] = 0.0
    for i in range(1, n + 1):
        row, prev = acc[i], acc[i - 1]
        c = cost[i - 1]
        for j in range(1, m + 1):
            row[j] = c[j - 1] + min(prev[j], row[j - 1], prev[j - 1])
    return float(acc[n, m] / (n + m))


def distance_to_prototypes(query: np.ndarray, prototypes: list[np.ndarray]) -> float:
    """Distance from *query* to an enrolled set: mean of the two closest.

    Averaging the two nearest prototypes measurably beats taking the
    single minimum — one lucky prototype shouldn't carry a match on its
    own, and one bad enrolment shouldn't sink it either.
    """
    if not prototypes:
        return float("inf")
    distances = sorted(dtw_distance(query, p) for p in prototypes)
    return float(np.mean(distances[:2]))
