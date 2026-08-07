"""_start_session wires what the realtime channel needs — skills included.

The realtime path forgot skills entirely (the VC path loads them, the
channel supports them), so the agent in a realtime session truthfully
told the user it had no way to activate skills. RoomKit and the channel
class are injected parameters, so fakes capture the constructor call.
"""

import pytest

from roomkit_ui.engine import Engine


class _FakeChannel:
    last_kwargs: dict = {}

    def __init__(self, channel_id, **kwargs):
        _FakeChannel.last_kwargs = kwargs

    async def start_session(self, room_id, participant_id, connection=None, metadata=None):
        return object()


class _FakeStore:
    async def room_exists(self, room_id):
        return False


class _FakeKit:
    def __init__(self, telemetry=None, store=None):
        self.store = store or _FakeStore()

    def register_channel(self, channel):
        pass

    async def create_room(self, room_id):
        pass

    async def attach_channel(self, room_id, channel_id):
        pass

    async def close(self):
        pass


@pytest.fixture
def engine(qapp):
    eng = Engine()
    yield eng
    if eng._cleanup_monitor_task is not None:
        eng._cleanup_monitor_task.cancel()


async def test_start_session_passes_skills_to_the_channel(engine):
    registry = object()
    session = await engine._start_session(
        _FakeKit,
        _FakeChannel,
        provider=object(),
        transport=object(),
        system_prompt="hi",
        voice="Aoede",
        sample_rate=24000,
        tools=[],
        tool_handler=None,
        skills=registry,
    )
    assert session is not None
    assert _FakeChannel.last_kwargs["skills"] is registry
    assert _FakeChannel.last_kwargs["voice"] == "Aoede"


async def test_start_session_empty_voice_reaches_channel_as_none(engine):
    await engine._start_session(
        _FakeKit,
        _FakeChannel,
        provider=object(),
        transport=object(),
        system_prompt="hi",
        voice="",  # ElevenLabs: the agent defines the voice
        sample_rate=16000,
        tools=[],
        tool_handler=None,
    )
    assert _FakeChannel.last_kwargs["voice"] is None
    assert _FakeChannel.last_kwargs["skills"] is None
