"""Fetch the wake-word encoder, so the feature can be enabled from Settings.

A single 12 MB file — whisper-tiny's encoder as sherpa-onnx exports it —
rather than the release tarball, which carries the 97 MB decoder the wake
word never loads.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from roomkit_ui.model_catalog import (
    WAKEWORD_ENCODER_BYTES,
    WAKEWORD_ENCODER_SHA256,
    WAKEWORD_ENCODER_URL,
    wakeword_encoder_path,
)

# (bytes_downloaded, total_bytes), as the other model downloads report it.
ProgressCallback = Callable[[int, int], None]


def download_encoder_sync(progress: ProgressCallback | None = None) -> None:
    """Download the encoder (blocking), checked against its pinned digest."""
    from roomkit_ui.model_download import _download_file

    target = wakeword_encoder_path()
    if target.is_file():
        return
    target.parent.mkdir(parents=True, exist_ok=True)

    total = WAKEWORD_ENCODER_BYTES
    downloaded = 0
    if progress is not None:
        progress(0, total)

    def on_bytes(n: int) -> None:
        nonlocal downloaded
        downloaded += n
        if progress is not None:
            progress(downloaded, total)

    _download_file(
        WAKEWORD_ENCODER_URL,
        target,
        expected_size=total,
        on_bytes=on_bytes,
        expected_sha256=WAKEWORD_ENCODER_SHA256,
    )


async def download_encoder(progress: ProgressCallback | None = None) -> None:
    """Download the encoder in a background thread."""
    await asyncio.to_thread(download_encoder_sync, progress)
