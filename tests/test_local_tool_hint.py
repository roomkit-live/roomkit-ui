"""A local model that refuses tools points the user at the setting.

The hint wrapped the provider's ``generate()``, which the AIChannel never
calls — it streams through ``generate_structured_stream()`` — so the
message never showed. The refusal reaches the app through ON_ERROR, where
roomkit funnels every failed turn with the provider's message.
"""

from collections.abc import AsyncIterator

from roomkit import AIChannel, RoomKit, VoiceChannel
from roomkit.models.delivery import InboundMessage
from roomkit.models.enums import ChannelCategory
from roomkit.models.event import TextContent
from roomkit.providers.ai.base import AIProvider, AIResponse
from roomkit.voice.backends.mock import MockVoiceBackend
from roomkit.voice.tts.mock import MockTTSProvider

from roomkit_ui.engine_vc_helpers import register_local_tool_hint

_TOOL = {"name": "get_time", "description": "Time", "parameters": {"type": "object"}}


class _RefusingModel(AIProvider):
    """Fails each turn the way an OpenAI-compatible local server does."""

    def __init__(self, message: str) -> None:
        self._message = message

    @property
    def model_name(self) -> str:
        return "gemma:2b"

    @property
    def supports_streaming(self) -> bool:
        return True

    @property
    def supports_structured_streaming(self) -> bool:
        return True

    async def generate(self, context) -> AIResponse:  # pragma: no cover — never called
        return AIResponse(content="unused")

    async def generate_structured_stream(self, context) -> AsyncIterator:
        raise RuntimeError(self._message)
        yield  # pragma: no cover


async def _turns(message: str, count: int) -> list[str]:
    backend = MockVoiceBackend()
    kit = RoomKit(voice=backend)
    kit.register_channel(VoiceChannel("voice", tts=MockTTSProvider(), backend=backend))
    kit.register_channel(AIChannel("ai", provider=_RefusingModel(message)))
    room = await kit.create_room()
    await kit.attach_channel(room.id, "voice")
    await kit.attach_channel(
        room.id, "ai", category=ChannelCategory.INTELLIGENCE, metadata={"tools": [_TOOL]}
    )
    await kit.join(room.id, "voice", participant_id="user")
    shown: list[str] = []
    register_local_tool_hint(kit, shown.append)

    for _ in range(count):
        await kit.process_inbound(
            InboundMessage(channel_id="voice", sender_id="user", content=TextContent(body="hi")),
            room_id=room.id,
        )
    await kit.close()
    return shown


async def test_a_tool_refusal_shows_the_hint_once():
    shown = await _turns(
        "Error code: 400 - registry.ollama.ai/library/gemma:2b does not support tools", 2
    )

    assert len(shown) == 1
    assert "Model supports tool use" in shown[0]


async def test_another_failure_is_not_taken_for_a_tool_refusal():
    assert await _turns("Error code: 503 - model is loading", 1) == []
