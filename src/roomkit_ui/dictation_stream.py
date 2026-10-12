"""A user-ended STT stream over RoomKit's public audio/provider interfaces."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable

from roomkit.voice.audio_frame import AudioFrame
from roomkit.voice.base import AudioChunk
from roomkit.voice.stt.base import STTProvider


class DictationStream:
    """Decode during capture; EOF drains the last words without waiting for silence."""

    MAX_FRAMES = 500  # Ten seconds of 20 ms frames; never silently drop speech.

    def __init__(self, provider: STTProvider, on_error: Callable[[str], None]) -> None:
        # One reserved slot lets Finish enqueue EOF even at the buffer limit.
        self._queue: asyncio.Queue[AudioChunk | None] = asyncio.Queue(self.MAX_FRAMES + 1)
        self._finishing = False
        self._error: BaseException | None = None
        self._on_error = on_error
        self.finals: list[str] = []
        self.task = asyncio.create_task(self._run(provider), name="dictation_stt")
        self.task.add_done_callback(self._completed)

    def feed(self, _session: object, frame: AudioFrame) -> None:
        if self._finishing or self.task.done():
            return
        if self._queue.qsize() >= self.MAX_FRAMES:
            self._error = RuntimeError(
                "Speech recognition cannot keep up. Try a shorter dictation."
            )
            self._finishing = True
            self.task.cancel()
            return
        self._queue.put_nowait(
            AudioChunk(data=frame.data, sample_rate=frame.sample_rate, channels=frame.channels)
        )

    async def _audio(self) -> AsyncIterator[AudioChunk]:
        while (chunk := await self._queue.get()) is not None:
            yield chunk

    async def _run(self, provider: STTProvider) -> None:
        results = provider.transcribe_stream(self._audio())
        try:
            async for result in results:
                if result.is_final and result.text.strip():
                    self.finals.append(result.text.strip())
        finally:
            close = getattr(results, "aclose", None)
            if close is not None:
                await close()
        if not self._finishing:
            raise RuntimeError("Speech recognition stopped unexpectedly. Please try again.")

    def _completed(self, task: asyncio.Task) -> None:
        if not task.cancelled():
            self._error = task.exception()
        if self._error is not None:
            self._on_error(str(self._error))

    async def finish(self) -> list[str]:
        if not self._finishing:
            self._finishing = True
            self._queue.put_nowait(None)
        if self._error is not None:
            raise self._error
        await asyncio.wait_for(asyncio.shield(self.task), timeout=30)
        return list(self.finals)

    async def close(self) -> None:
        self._finishing = True
        if not self.task.done():
            self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)
        while not self._queue.empty():
            self._queue.get_nowait()
