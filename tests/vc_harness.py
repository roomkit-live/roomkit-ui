"""A real voice-channel kit on roomkit's mocks, wired with roomkit-ui's VC hooks.

Speech is scripted (``MockVADProvider`` + ``MockSTTProvider``), the reply
streams token by token from :class:`TokenAI`, and what the assistant says
reaches the TTS mock. The hooks talk to a :class:`FakeEngine` that records
every chat emit: the chat as the user sees it.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from PySide6.QtCore import QObject, Signal
from roomkit import RoomKit, VoiceChannel
from roomkit.channels.ai import AIChannel
from roomkit.models.enums import ChannelCategory
from roomkit.models.event import TextContent
from roomkit.providers.ai.base import AIContext, AIProvider, AIResponse
from roomkit.voice.audio_frame import AudioFrame
from roomkit.voice.backends.mock import MockVoiceBackend
from roomkit.voice.base import AudioChunk
from roomkit.voice.pipeline import AudioPipelineConfig, MockVADProvider
from roomkit.voice.pipeline.vad.base import VADEvent, VADEventType
from roomkit.voice.stt.mock import MockSTTProvider
from roomkit.voice.tts.base import TTSProvider

from roomkit_ui.engine_state import EngineState
from roomkit_ui.hooks import register_vc_hooks


class FakeEngine(QObject):
    """The engine surface the VC hooks use; ``chat`` is every transcription emit."""

    transcription = Signal(str, str, bool, str)
    user_speaking = Signal(bool)
    ai_speaking = Signal(bool)
    mic_audio_level = Signal(float)
    speaker_identified = Signal(str, float)
    session_notice = Signal(str)
    speaker_named = Signal(str, str)

    def __init__(self) -> None:
        super().__init__()
        self._state = EngineState.ACTIVE
        self._mic_muted = False
        self._primary_speaker_mode = False
        self._primary_speaker_name = ""
        self._speakers: Any = None
        self._partial_buffers: dict[str, str] = {}
        self._spk_rms_queue: list[float] = []
        self.chat: list[tuple[str, str, bool, str]] = []
        self.emit_threads: set[int] = set()
        self.transcription.connect(self._record)

    def _record(self, text: str, role: str, final: bool, speaker: str) -> None:
        self.emit_threads.add(threading.get_ident())
        self.chat.append((text, role, final, speaker))

    def _accumulate_usage(self, usage: dict) -> None:
        pass

    def finals(self, role: str) -> list[tuple[str, str]]:
        """(text, speaker) of each final bubble of *role*."""
        return [(text, spk) for text, r, final, spk in self.chat if r == role and final]


class TokenAI(AIProvider):
    """A streaming LLM that answers every turn with the same tokens."""

    def __init__(self, tokens: list[str]) -> None:
        self._tokens = tokens
        self.contexts: list[AIContext] = []

    @property
    def model_name(self) -> str:
        return "token-ai"

    @property
    def supports_streaming(self) -> bool:
        return True

    async def generate(self, context: AIContext) -> AIResponse:
        self.contexts.append(context)
        return AIResponse(content="".join(self._tokens))

    async def generate_stream(self, context: AIContext) -> AsyncIterator[str]:
        self.contexts.append(context)
        for token in self._tokens:
            yield token


class StreamingInputTTS(TTSProvider):
    """A TTS fed sentence by sentence, as ElevenLabs and Gradium are."""

    def __init__(self) -> None:
        self.spoken: list[str] = []

    @property
    def supports_streaming_input(self) -> bool:
        return True

    async def synthesize(self, text: str, *, voice: str | None = None) -> Any:
        raise NotImplementedError

    async def synthesize_stream_input(
        self, text_stream: AsyncIterator[str], *, voice: str | None = None, **_: Any
    ) -> AsyncIterator[AudioChunk]:
        async for sentence in text_stream:
            self.spoken.append(sentence)
            yield AudioChunk(data=b"\x00\x00" * 160, sample_rate=16000)
        yield AudioChunk(data=b"", sample_rate=16000, is_final=True)


def utterance(audio: bytes = b"\x01\x00" * 160) -> list[VADEvent | None]:
    """VAD events of one utterance over three frames."""
    return [
        VADEvent(type=VADEventType.SPEECH_START),
        None,
        VADEvent(type=VADEventType.SPEECH_END, audio_bytes=audio),
    ]


@dataclass
class VCSession:
    kit: RoomKit
    voice: VoiceChannel
    backend: MockVoiceBackend
    session: Any
    engine: FakeEngine
    ai: TokenAI

    async def speak(self, frames: int = 3) -> None:
        """Feed *frames* mic frames: one per scripted VAD event."""
        for _ in range(frames):
            frame = AudioFrame(data=b"\x01\x00" * 160, sample_rate=16000)
            await self.backend.simulate_audio_received(self.session, frame)


async def open_session(
    *,
    tts: TTSProvider,
    reply: list[str],
    transcripts: list[str] | None = None,
    vad_events: list[VADEvent | None] | None = None,
    pipeline: dict[str, Any] | None = None,
    build_channel: Callable[..., VoiceChannel] | None = None,
    engine: FakeEngine | None = None,
    tts_filter: Any = None,
    ai_options: dict[str, Any] | None = None,
    history: list[str] | None = None,
) -> VCSession:
    """A connected voice session whose user turns the TokenAI answers.

    *build_channel* is called as ``(stt, tts, backend, pipeline, tts_filter)``
    — the engine's ``_build_voice_channel`` — instead of a plain VoiceChannel.
    *ai_options* go to the AIChannel (a speak policy, a thinker).
    *history* is what the assistant said in the room before the session.
    """
    stt = MockSTTProvider(transcripts=transcripts or ["Hello"])
    backend = MockVoiceBackend()
    stages = {"vad": MockVADProvider(events=vad_events or utterance()), **(pipeline or {})}
    config = AudioPipelineConfig(**stages)
    build = build_channel or _plain_channel
    channel = build(stt, tts, backend, config, tts_filter)
    kit = RoomKit(stt=stt, voice=backend)
    kit.register_channel(channel)
    ai = TokenAI(reply)
    kit.register_channel(
        AIChannel("ai", provider=ai, system_prompt="Be brief.", **(ai_options or {}))
    )
    room = await kit.create_room()
    await kit.attach_channel(room.id, "voice")
    await kit.attach_channel(room.id, "ai", category=ChannelCategory.INTELLIGENCE)
    for said in history or []:
        # Stored as the assistant's, five minutes ago, answered by nobody.
        await kit.send_event(
            room.id,
            "ai",
            TextContent(body=said),
            created_at=datetime.now(UTC) - timedelta(minutes=5),
            addressed_to=[],
        )
    engine = engine or FakeEngine()
    register_vc_hooks(kit, engine, tts_filter=tts_filter)
    session = await kit.join(room.id, "voice", participant_id="user-1")
    return VCSession(kit, channel, backend, session, engine, ai)


def _plain_channel(
    stt: Any, tts: Any, backend: Any, pipeline: AudioPipelineConfig, tts_filter: Any
) -> VoiceChannel:
    return VoiceChannel(
        "voice", stt=stt, tts=tts, backend=backend, pipeline=pipeline, tts_filter=tts_filter
    )


async def until(predicate: Callable[[], bool], timeout: float = 3.0) -> None:
    """Wait for *predicate* to hold, yielding to the loop in between."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() > deadline:
            raise TimeoutError("condition not met in time")
        await asyncio.sleep(0.01)
