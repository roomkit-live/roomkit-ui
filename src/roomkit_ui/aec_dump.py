"""AEC dump recorder — captures what the echo canceller actually sees.

Wraps any roomkit ``AECProvider`` and records, in arrival order, every
reference frame fed from the playback path and every capture frame with
its processed result.  The dump is the raw material for the offline AEC
bench (``scripts/aec_bench.py`` in the roomkit repo): replaying it through
a fresh provider with different settings measures a fix instead of
guessing at it.

Enabled by the ``ROOMKIT_AEC_DUMP`` environment variable (a directory);
wired on the realtime path only — the VC path hands the same AEC instance
to the backend, whose transport-level integration this wrapper does not
mimic.

Format (``aec-dump/1``): one JSONL file per stream.  Line 1 is a header
``{"format": "aec-dump/1", "sample_rate": …, "channels": …,
"sample_width": …, "stream": …, "provider": …}``; every following line is
an event — ``{"t": "ref", "ns": …, "d": <b64>}`` for a reference frame,
``{"t": "cap", "ns": …, "i": <b64>, "o": <b64>}`` for a capture frame and
its processed output, ``{"t": "act", "ns": …, "a": bool}`` for a
per-stream activation toggle — the live pipeline pairs activation with
playback (the interrupt cycle), and a replay that ignored those toggles
would not reproduce the run.  Three WAVs (``ref/mic_in/mic_out``) are written
alongside for listening; the JSONL, which preserves interleaving, is what
the bench replays.

``feed_reference`` runs on the PortAudio callback thread, so events are
buffered in memory and flushed at ``reset()`` — never any I/O on the
audio thread.  A safety cap stops recording after ~10 minutes.
"""

from __future__ import annotations

import base64
import contextlib
import json
import logging
import threading
import time
import wave
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ~10 min of 10 ms events at 24 kHz on both paths — bench sessions are
# minutes long; an overnight session must not eat the machine's RAM.
_MAX_EVENTS = 120_000


class AECDumpRecorder:
    """Pass-through ``AECProvider`` wrapper that records its traffic."""

    def __init__(self, inner: Any, directory: Path) -> None:
        self._inner = inner
        self._dir = directory
        self._lock = threading.Lock()
        # stream -> list of event tuples; ("ref", ns, bytes) or
        # ("cap", ns, in_bytes, out_bytes)
        self._events: dict[str, list[tuple]] = {}
        self._formats: dict[str, tuple[int, int, int]] = {}
        self._capped: set[str] = set()

    # -- AECProvider surface (0.43 ABC) -----------------------------------

    @property
    def name(self) -> str:
        return f"{self._inner.name}+dump"

    def process(self, frame: Any, stream: str) -> Any:
        out = self._inner.process(frame, stream)
        self._record(
            stream,
            ("cap", time.monotonic_ns(), bytes(frame.data), bytes(out.data)),
            frame,
        )
        return out

    def feed_reference(self, frame: Any, stream: str) -> None:
        self._inner.feed_reference(frame, stream)
        self._record(stream, ("ref", time.monotonic_ns(), bytes(frame.data)), frame)

    def set_active(self, active: bool) -> None:
        self._inner.set_active(active)

    def set_stream_active(self, stream: str, active: bool) -> None:
        self._inner.set_stream_active(stream, active)
        with self._lock:
            if stream not in self._capped:
                events = self._events.setdefault(stream, [])
                if len(events) < _MAX_EVENTS:
                    events.append(("act", time.monotonic_ns(), active))

    def reset(self, stream: str) -> None:
        self._inner.reset(stream)
        self._flush(stream)

    def __getattr__(self, item: str) -> Any:
        # Anything beyond the ABC (stats hooks, provider-specific knobs)
        # reaches the wrapped provider untouched.
        return getattr(self._inner, item)

    # -- recording ---------------------------------------------------------

    def _record(self, stream: str, event: tuple, frame: Any) -> None:
        with self._lock:
            if stream in self._capped:
                return
            events = self._events.setdefault(stream, [])
            if len(events) >= _MAX_EVENTS:
                self._capped.add(stream)
                logger.warning(
                    "AEC dump for stream %s hit the event cap — recording stopped", stream
                )
                return
            events.append(event)
            self._formats.setdefault(
                stream,
                (
                    getattr(frame, "sample_rate", 0),
                    getattr(frame, "channels", 1),
                    getattr(frame, "sample_width", 2),
                ),
            )

    def _flush(self, stream: str) -> None:
        with self._lock:
            events = self._events.pop(stream, [])
            fmt = self._formats.pop(stream, (0, 1, 2))
            self._capped.discard(stream)
        if not events:
            return
        try:
            session_dir = self._dir / time.strftime("%Y%m%d-%H%M%S")
            session_dir.mkdir(parents=True, exist_ok=True)
            self._write_jsonl(session_dir, stream, fmt, events)
            self._write_wavs(session_dir, fmt, events)
            logger.info(
                "AEC dump written: %s (%d events, stream %s)",
                session_dir,
                len(events),
                stream,
            )
        except Exception:
            logger.exception("Failed to write AEC dump for stream %s", stream)

    def _write_jsonl(
        self,
        session_dir: Path,
        stream: str,
        fmt: tuple[int, int, int],
        events: list[tuple],
    ) -> None:
        sample_rate, channels, sample_width = fmt
        header = {
            "format": "aec-dump/1",
            "sample_rate": sample_rate,
            "channels": channels,
            "sample_width": sample_width,
            "stream": stream,
            "provider": getattr(self._inner, "name", "unknown"),
        }
        with (session_dir / "events.jsonl").open("w", encoding="utf-8") as f:
            f.write(json.dumps(header) + "\n")
            for event in events:
                if event[0] == "ref":
                    _, ns, data = event
                    row: dict = {"t": "ref", "ns": ns, "d": _b64(data)}
                elif event[0] == "act":
                    _, ns, active = event
                    row = {"t": "act", "ns": ns, "a": bool(active)}
                else:
                    _, ns, in_data, out_data = event
                    row = {"t": "cap", "ns": ns, "i": _b64(in_data), "o": _b64(out_data)}
                f.write(json.dumps(row) + "\n")

    def _write_wavs(
        self, session_dir: Path, fmt: tuple[int, int, int], events: list[tuple]
    ) -> None:
        sample_rate, channels, sample_width = fmt
        tracks = {
            "ref.wav": b"".join(e[2] for e in events if e[0] == "ref"),
            "mic_in.wav": b"".join(e[2] for e in events if e[0] == "cap"),
            "mic_out.wav": b"".join(e[3] for e in events if e[0] == "cap"),
        }
        for filename, pcm in tracks.items():
            if not pcm:
                continue
            with contextlib.closing(wave.open(str(session_dir / filename), "wb")) as w:
                w.setnchannels(channels)
                w.setsampwidth(sample_width)
                w.setframerate(sample_rate or 24000)
                w.writeframes(pcm)


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")
