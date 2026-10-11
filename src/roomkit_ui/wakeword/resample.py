"""Streaming sample-rate conversion to the 16 kHz the speech models expect.

The shared microphone runs at the transport's rate — 24 kHz for every
realtime provider but ElevenLabs — and arrives in 20 ms blocks.  Each
block used to be stretched on its own with ``np.interp``: no low-pass, so
everything between 8 and 12 kHz folded back into the band the encoder
listens to, and ``linspace(0, n - 1, ...)`` restarted the phase at every
block edge.  Fingerprints enrolled one way were then matched against
audio converted another.

This is a rational polyphase resampler: a Kaiser-windowed sinc low-pass
below the output Nyquist, evaluated only at the output instants, with the
input history carried across blocks so block edges are invisible and the
output keeps the input's duration.  numpy only — roomkit's sinc resampler
is pure Python and too slow for a microphone that never stops.
"""

from __future__ import annotations

from math import gcd

import numpy as np

# Kernel span on each side of the centre, in zero crossings of the cutoff
# sinc, and the Kaiser shape: about 80 dB of stopband, ample for int16.
_ZERO_CROSSINGS = 16
_KAISER_BETA = 8.0
# Cutoff as a fraction of the output Nyquist: the transition band sits
# just below it, so nothing above it folds back.
_ROLLOFF = 0.9


def _design(up: int, down: int) -> tuple[np.ndarray, int]:
    """Polyphase filter bank ``(up, taps)`` and the kernel's half length."""
    cutoff = _ROLLOFF / max(up, down)  # of the upsampled Nyquist
    half = int(np.ceil(_ZERO_CROSSINGS / cutoff))
    n = np.arange(-half, half + 1)
    kernel = cutoff * np.sinc(cutoff * n) * np.kaiser(2 * half + 1, _KAISER_BETA) * up
    taps = -(-len(kernel) // up)  # ceil
    padded = np.zeros(taps * up)
    padded[: len(kernel)] = kernel
    # bank[p, q] = kernel[p + q * up]: the taps phase p applies to x[i], x[i-1]...
    bank = padded.reshape(taps, up).T.copy()
    return bank, half


class StreamResampler:
    """Converts a stream of int16 mono blocks from one rate to another."""

    def __init__(self, src_rate: int, dst_rate: int) -> None:
        g = gcd(src_rate, dst_rate)
        self._up = dst_rate // g
        self._down = src_rate // g
        self._bank, self._half = _design(self._up, self._down)
        self._taps = self._bank.shape[1]
        self.reset()

    def reset(self) -> None:
        """Forget the history — the next block starts a new stream."""
        # Zeros stand in for the samples before the stream began.
        self._history = np.zeros(self._taps - 1)
        self._first = -(self._taps - 1)  # stream index of _history[0]
        self._next = 0  # index of the next output sample

    def process(self, pcm: bytes) -> bytes:
        """Resample one block; returns whatever output it completes."""
        block = np.frombuffer(pcm, dtype=np.int16).astype(np.float64)
        buffer = np.concatenate((self._history, block))
        last = self._first + len(buffer) - 1  # newest input index available

        # Output k sits at upsampled instant k*down; centring the kernel on
        # it (+half) keeps the output aligned in time with the input.  An
        # output is complete once the newest input it needs has arrived.
        candidates = len(block) * self._up // self._down + 2
        instants = np.arange(self._next, self._next + candidates) * self._down + self._half
        count = int(np.searchsorted(instants // self._up, last, side="right"))
        out = np.empty(0)
        if count:
            instants = instants[:count]
            phases = instants % self._up
            columns = (instants // self._up - self._first)[:, None] - np.arange(self._taps)
            out = np.einsum("kq,kq->k", buffer[columns], self._bank[phases])
            self._next += count

        keep = self._taps - 1
        self._history = buffer[-keep:]
        self._first = last - keep + 1
        return np.clip(np.rint(out), -32768, 32767).astype(np.int16).tobytes()
