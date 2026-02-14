"""Voice enrollment recorder — records audio and extracts speaker embeddings."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[float], None]  # 0.0 – 1.0


def _record_sync(
    duration: float,
    sample_rate: int,
    progress: ProgressCallback | None,
) -> bytes:
    """Record *duration* seconds of 16-bit mono PCM (blocking)."""
    import sounddevice as sd

    frames = int(sample_rate * duration)
    block_size = sample_rate // 10  # 100ms blocks

    chunks: list[bytes] = []
    recorded = 0

    def _callback(indata, frame_count, time_info, status):
        nonlocal recorded
        chunks.append(bytes(indata))
        recorded += frame_count
        if progress is not None:
            progress(min(recorded / frames, 1.0))

    with sd.RawInputStream(
        samplerate=sample_rate,
        channels=1,
        dtype="int16",
        blocksize=block_size,
        callback=_callback,
    ):
        import time

        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            time.sleep(0.05)

    return b"".join(chunks)


def _extract_embedding(
    extractor, pcm_float: list[float], sample_rate: int
) -> list[float] | None:
    """Extract a single embedding from float PCM samples."""
    stream = extractor.create_stream()
    stream.accept_waveform(sample_rate=sample_rate, waveform=pcm_float)
    stream.input_finished()
    if not extractor.is_ready(stream):
        return None
    return list(extractor.compute(stream))


async def record_and_extract(
    model_path: str,
    duration: float = 10.0,
    progress: ProgressCallback | None = None,
    *,
    num_threads: int = 1,
    provider: str = "cpu",
) -> list[float]:
    """Record audio and extract a speaker embedding.

    Returns the embedding vector as a list of floats.
    """
    sample_rate = 16000

    def _run() -> list[float]:
        import sherpa_onnx

        pcm = _record_sync(duration, sample_rate, progress)

        config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=model_path,
            num_threads=num_threads,
            provider=provider,
        )
        extractor = sherpa_onnx.SpeakerEmbeddingExtractor(config=config)

        import array

        samples = array.array("h")
        samples.frombytes(pcm)
        float_samples = [s / 32768.0 for s in samples]

        embedding = _extract_embedding(extractor, float_samples, sample_rate)
        if embedding is None:
            raise ValueError("Recording too short or too quiet to extract embedding")
        return embedding

    return await asyncio.to_thread(_run)


async def record_and_extract_multi(
    model_path: str,
    duration: float = 10.0,
    progress: ProgressCallback | None = None,
    *,
    segment_sec: float = 3.0,
    hop_sec: float = 2.0,
    num_threads: int = 1,
    provider: str = "cpu",
) -> list[list[float]]:
    """Record audio and extract multiple embeddings from overlapping segments.

    Splits the recording into *segment_sec* windows with *hop_sec* stride.
    Returns a list of embedding vectors (one per segment).
    """
    sample_rate = 16000

    def _run() -> list[list[float]]:
        import array

        import sherpa_onnx

        pcm = _record_sync(duration, sample_rate, progress)

        config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=model_path,
            num_threads=num_threads,
            provider=provider,
        )
        extractor = sherpa_onnx.SpeakerEmbeddingExtractor(config=config)

        samples = array.array("h")
        samples.frombytes(pcm)
        float_samples = [s / 32768.0 for s in samples]

        total_samples = len(float_samples)
        seg_samples = int(segment_sec * sample_rate)
        hop_samples = int(hop_sec * sample_rate)

        embeddings: list[list[float]] = []
        offset = 0
        while offset + seg_samples <= total_samples:
            segment = float_samples[offset : offset + seg_samples]
            emb = _extract_embedding(extractor, segment, sample_rate)
            if emb is not None:
                embeddings.append(emb)
                logger.info(
                    "Extracted embedding %d from offset %.1fs",
                    len(embeddings),
                    offset / sample_rate,
                )
            offset += hop_samples

        if not embeddings:
            raise ValueError("Could not extract any embeddings from recording")

        logger.info("Extracted %d embeddings from %.1fs recording", len(embeddings), duration)
        return embeddings

    return await asyncio.to_thread(_run)
