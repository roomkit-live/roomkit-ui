"""Acoustic representation for wake-word matching — whisper's encoder only.

The decoder is never loaded.  It is 97 of whisper-tiny's 109 MB, and it
is also what makes plain transcription useless here: constrained to
French it renders "hey jarvis" as "et j'arvisse", and left to English it
rewrites a whole French sentence and drops the keyword entirely.  The
encoder alone gives a 384-dim acoustic representation per frame, which
is what we actually want to compare — no language, no spelling.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
N_FFT = 400  # 25 ms
HOP = 160  # 10 ms
N_MELS = 80
EMBED_DIM = 384


def _slaney_mel_filters(sr: int = SAMPLE_RATE, n_fft: int = N_FFT, n_mels: int = N_MELS):
    """Mel filterbank in librosa/Slaney form — the one whisper expects.

    Differs from the HTK scale: linear below 1 kHz, logarithmic above,
    and each filter normalised by its width.  Feeding whisper an HTK mel
    puts it out of distribution and the embeddings become noise.
    """
    f_sp = 200.0 / 3
    min_log_hz, logstep = 1000.0, np.log(6.4) / 27.0
    min_log_mel = min_log_hz / f_sp

    def hz_to_mel(f):
        f = np.asarray(f, dtype=np.float64)
        mel = f / f_sp
        high = f >= min_log_hz
        mel[high] = min_log_mel + np.log(f[high] / min_log_hz) / logstep
        return mel

    def mel_to_hz(m):
        freqs = f_sp * m
        high = m >= min_log_mel
        freqs[high] = min_log_hz * np.exp(logstep * (m[high] - min_log_mel))
        return freqs

    fft_freqs = np.fft.rfftfreq(n_fft, 1.0 / sr)
    mels = np.linspace(0.0, hz_to_mel(np.array([sr / 2.0]))[0], n_mels + 2)
    freqs = mel_to_hz(mels)
    fdiff = np.diff(freqs)
    ramps = freqs[:, None] - fft_freqs[None, :]

    weights = np.zeros((n_mels, len(fft_freqs)), dtype=np.float32)
    for i in range(n_mels):
        lower = -ramps[i] / fdiff[i]
        upper = ramps[i + 2] / fdiff[i + 1]
        weights[i] = np.maximum(0.0, np.minimum(lower, upper))
    weights *= (2.0 / (freqs[2 : n_mels + 2] - freqs[:n_mels]))[:, None]
    return weights


_FILTERS = _slaney_mel_filters()
# Periodic Hann, matching torch.hann_window — the symmetric np.hanning
# would shift every frame slightly off what the model was trained on.
_WINDOW = (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(N_FFT) / N_FFT)).astype(np.float32)


def log_mel(pcm: bytes) -> np.ndarray:
    """16-bit mono PCM → whisper's log-mel spectrogram, shape ``(80, T)``."""
    x = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    if len(x) < N_FFT:
        return np.zeros((N_MELS, 0), dtype=np.float32)
    x = np.pad(x, N_FFT // 2, mode="reflect")  # center=True, like torch.stft
    n_frames = 1 + (len(x) - N_FFT) // HOP
    frames = (
        np.lib.stride_tricks.as_strided(
            x, shape=(n_frames, N_FFT), strides=(x.strides[0] * HOP, x.strides[0])
        )
        * _WINDOW
    )
    magnitudes = (np.abs(np.fft.rfft(frames, n=N_FFT)) ** 2)[:-1]
    mel = _FILTERS @ magnitudes.T
    log_spec = np.log10(np.maximum(mel, 1e-10))
    log_spec = np.maximum(log_spec, log_spec.max() - 8.0)
    normalised: np.ndarray = ((log_spec + 4.0) / 4.0).astype(np.float32)
    return normalised


class WhisperEmbedder:
    """Turns speech into comparable acoustic sequences via whisper's encoder.

    The ONNX session is created on first use so importing this module
    costs nothing when the wake word is disabled.
    """

    def __init__(self, encoder_path: str | Path, *, num_threads: int = 2) -> None:
        self._path = Path(encoder_path)
        self._threads = num_threads
        self._session: Any = None

    @property
    def ready(self) -> bool:
        return self._session is not None

    def load(self) -> None:
        """Create the ONNX session (idempotent)."""
        if self._session is not None:
            return
        if not self._path.is_file():
            raise FileNotFoundError(f"Wake-word encoder not found: {self._path}")
        import onnxruntime as ort

        options = ort.SessionOptions()
        options.intra_op_num_threads = self._threads
        self._session = ort.InferenceSession(
            str(self._path), options, providers=["CPUExecutionProvider"]
        )
        logger.info("Wake word encoder loaded: %s", self._path.name)

    def close(self) -> None:
        self._session = None

    def embed(self, pcm: bytes) -> np.ndarray:
        """Encode PCM into a ``(frames, 384)`` acoustic sequence.

        Returns an empty array for segments too short to encode, which
        callers treat as "no match" rather than as an error.
        """
        self.load()
        mel = log_mel(pcm)
        if mel.shape[1] < 8:
            return np.zeros((0, EMBED_DIM), dtype=np.float32)
        cross_k, _ = self._session.run(None, {"mel": mel[None, :, :]})
        # (layers, batch, frames, dim) — the last layer scored best in
        # offline comparison, with layers 0 and 2 statistically tied.
        return np.ascontiguousarray(cross_k[-1, 0]).astype(np.float32)
