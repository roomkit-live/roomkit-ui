"""Real RoomKit text routing and streaming, with an in-process test provider."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from roomkit.providers.ai.base import AIProvider, AIResponse

from roomkit_ui.engine import Engine
from roomkit_ui.engine_state import EngineState
from roomkit_ui.toolset import ToolSet

SETTINGS = {
    "vc_llm_provider": "anthropic",
    "anthropic_api_key": "test-only",
    "conversation_memory": False,
    "conversation_mode": "realtime",
    "system_prompt": "Answer the user's message.",
}


class TestProvider(AIProvider):
    __test__ = False

    def __init__(self, *, pause=False, fail=False, empty=False):
        self.contexts = []
        self.release = asyncio.Event()
        self.closed = False
        self.fail = fail
        self.empty = empty
        if not pause:
            self.release.set()

    @property
    def model_name(self):
        return "test-chat"

    @property
    def supports_streaming(self):
        return True

    async def generate(self, context):
        self.contexts.append(context)
        return AIResponse(content="Bonjour !")

    async def generate_stream(self, context):
        self.contexts.append(context)
        if self.empty:
            return
        yield "Bonjour"
        await self.release.wait()
        if self.fail:
            raise RuntimeError("Provider unavailable")
        yield " !"

    async def close(self):
        self.closed = True


@pytest.fixture
async def setup_text(qapp, monkeypatch):
    monkeypatch.setattr("roomkit_ui.text_chat.is_available", lambda _: True)
    # qasync-specific FD cleanup is covered separately; never touch pytest's loop.
    monkeypatch.setattr(Engine, "_finalize_event_loop", AsyncMock())
    monkeypatch.setattr(
        Engine, "_load_vc_tools", AsyncMock(return_value=(ToolSet([], [], []), None))
    )

    engines = []

    def install(provider, engine=None):
        monkeypatch.setattr("roomkit_ui.engine_text.create_ai_provider", lambda *_, **__: provider)
        eng = engine or Engine()
        if eng not in engines:
            engines.append(eng)
        eng._start_voice_channel = AsyncMock(side_effect=AssertionError("Audio opened"))
        eng._start_realtime = AsyncMock(side_effect=AssertionError("Audio opened"))
        return eng

    yield install
    for eng in engines:
        await eng.stop()


async def test_real_channel_streams_before_completion_and_closes_provider(setup_text):
    provider = TestProvider(pause=True)
    engine = setup_text(provider)
    received, info, states = [], [], []
    first_chunk = asyncio.Event()
    engine.transcription.connect(lambda *args: (received.append(args), first_chunk.set()))
    engine.session_info.connect(info.append)
    engine.state_changed.connect(states.append)
    task = asyncio.create_task(engine.start(SETTINGS, text="Salut", conversation_id="thread"))
    await asyncio.wait_for(first_chunk.wait(), 3)
    assert not task.done()
    assert received[0][:3] == ("Bonjour", "assistant", False)
    assert engine._backend is None and engine._transport is None
    assert info[0]["mode"] == "text"
    assert info[0]["models"][0]["model"] == "test-chat"
    provider.release.set()
    await asyncio.wait_for(task, 3)
    assert received[-1][:3] == ("Bonjour !", "assistant", True)
    assert sum(bool(item[2]) for item in received) == 1
    assert not provider.closed and engine._kit is not None
    assert states == [
        EngineState.CONNECTING,
        EngineState.ACTIVE,
        EngineState.READY,
    ]
    assert engine.is_text
    assert [m.content for m in provider.contexts[0].messages] == ["Salut"]
    await engine.stop()
    assert provider.closed and engine._kit is None


async def test_typed_turns_run_on_the_text_chats_own_model(setup_text, monkeypatch):
    provider = TestProvider()
    engine = setup_text(provider)
    made = []

    def create(name, settings, **options):
        made.append((name, settings, options))
        return provider

    monkeypatch.setattr("roomkit_ui.engine_text.create_ai_provider", create)
    settings = {
        **SETTINGS,
        "text_llm_provider": "openai",
        "text_openai_model": "gpt-5.5",
        "openai_api_key": "test-only",
    }

    await asyncio.wait_for(engine.start(settings, text="Salut", conversation_id="thread"), 3)

    ((name, used, options),) = made
    assert (name, used["vc_openai_model"], options) == ("openai", "gpt-5.5", {"role": "text"})
    await engine.stop()


async def test_cancel_retains_partial_and_never_emits_late_text(setup_text):
    from roomkit.models.event import TextContent

    provider = TestProvider(pause=True)
    engine = setup_text(provider)
    arrived = asyncio.Event()
    received, stopped = [], []
    engine.transcription.connect(lambda *args: (received.append(args), arrived.set()))
    engine.text_reply_stopped.connect(lambda: stopped.append(True))
    task = asyncio.create_task(engine.start(SETTINGS, text="Salut"))
    await asyncio.wait_for(arrived.wait(), 3)
    old_delivery = engine._channel._connections["desktop"]
    await asyncio.wait_for(engine.stop(), 3)
    await asyncio.wait_for(task, 3)
    provider.release.set()
    await asyncio.sleep(0)
    assert engine.state == EngineState.IDLE
    assert provider.closed
    assert stopped == [True]
    assert received[-1][0] == "Bonjour"
    # Even when a new request is ACTIVE, a retired delivery cannot write to it.
    arrived.clear()
    provider2 = TestProvider(pause=True)
    setup_text(provider2, engine)
    next_task = asyncio.create_task(engine.start(SETTINGS, text="New thread"))
    await asyncio.wait_for(arrived.wait(), 3)
    before = list(received)
    await old_delivery(
        "desktop",
        SimpleNamespace(
            source=SimpleNamespace(channel_id="ai"),
            content=TextContent(body="Late reply"),
        ),
    )
    assert received == before
    await engine.stop()
    await asyncio.wait_for(next_task, 3)


@pytest.mark.parametrize("failure", ["fail", "empty"])
async def test_failure_is_reported_and_next_turn_can_succeed(setup_text, failure):
    failed = TestProvider(**{failure: True})
    engine = setup_text(failed)
    errors = []
    engine.error_occurred.connect(errors.append)
    await asyncio.wait_for(engine.start(SETTINGS, text="Salut"), 5)
    assert engine.state == EngineState.READY
    assert errors and not failed.closed and engine._kit is not None
    failed.fail = failed.empty = False
    await asyncio.wait_for(
        engine.start(SETTINGS, text="Rebonjour", conversation_id=engine._room_id),
        3,
    )
    assert engine.state == EngineState.READY
    assert len(errors) == 1 and not failed.closed


async def test_stop_during_setup_and_refuse_duplicate_send(setup_text, monkeypatch):
    provider = TestProvider()
    engine = setup_text(provider)
    reached = asyncio.Event()

    async def tools(*_):
        reached.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(engine, "_load_vc_tools", tools)
    task = asyncio.create_task(engine.start(SETTINGS, text="First", conversation_id="first"))
    await asyncio.wait_for(reached.wait(), 3)
    await engine.start(SETTINGS, text="Second", conversation_id="second")
    assert engine._room_id == "first"
    await asyncio.wait_for(engine.stop(), 3)
    await asyncio.wait_for(task, 3)
    assert engine.state == EngineState.IDLE and engine._kit is None
    assert provider.contexts == []


async def test_tool_segments_are_finalized_once_without_technical_events(setup_text, monkeypatch):
    from roomkit.providers.ai.base import AIToolCall

    from roomkit_ui.builtin_tools import BUILTIN_TOOLS

    class ToolProvider(TestProvider):
        async def generate(self, context):
            self.contexts.append(context)
            if len(self.contexts) == 1:
                return AIResponse(
                    content="Je vérifie.",
                    tool_calls=[AIToolCall(id="date", name="get_current_date", arguments={})],
                    usage={"input_tokens": 10, "output_tokens": 2},
                )
            return AIResponse(
                content="Voici la date.", usage={"input_tokens": 12, "output_tokens": 3}
            )

    provider = ToolProvider()
    engine = setup_text(provider)
    monkeypatch.setattr(
        engine,
        "_load_vc_tools",
        AsyncMock(
            return_value=(
                ToolSet(BUILTIN_TOOLS, [], []),
                None,
            )
        ),
    )
    received, calls, results, costs = [], [], [], []
    engine.transcription.connect(lambda *args: received.append(args))
    engine.tool_started.connect(calls.append)
    engine.tool_finished.connect(results.append)
    engine.session_cost.connect(costs.append)
    await asyncio.wait_for(engine.start(SETTINGS, text="Quelle date ?"), 3)
    assert engine.state == EngineState.READY
    assert [item[0] for item in received if item[2]] == ["Je vérifie.", "Voici la date."]
    assert len(calls) == len(results) == 1
    assert results[0].status == "completed"
    assert all(tool.name != "end_conversation" for tool in provider.contexts[0].tools)
    assert costs[-1]["input_tokens"] == 22
    assert costs[-1]["output_tokens"] == 5


async def test_saved_room_excludes_old_turns_from_current_request(setup_text):
    from roomkit import RoomKit

    from roomkit_ui.memory import build_store

    first = TestProvider()
    engine = setup_text(first)
    settings = {**SETTINGS, "conversation_memory": True}
    await engine.start(settings, text="Original", conversation_id="saved")
    await engine.stop()
    second = TestProvider()
    setup_text(second, engine)
    await engine.start(
        settings,
        text="Suite",
        conversation_id="saved",
        resume_context="Earlier: Original / Bonjour !",
    )
    assert engine.state == EngineState.READY
    context = second.contexts[0]
    assert "Earlier: Original / Bonjour !" in context.system_prompt
    assert [m.content for m in context.messages] == ["Suite"]
    kit = RoomKit(store=build_store(settings))
    events = await kit.store.list_events("saved")
    text = [e.content.body for e in events if hasattr(e.content, "body")]
    assert text.count("Original") == text.count("Suite") == 1
    assert text.count("Bonjour !") == 2
    assert {b.channel_id for b in await kit.store.list_bindings("saved")} == {"text", "ai"}
    await kit.close()


async def test_recall_finds_other_threads_and_never_this_session(setup_text):
    from roomkit_ui.conversations import Conversation, ConversationStore

    settings = {**SETTINGS, "conversation_memory": True}
    engine = setup_text(TestProvider())
    await engine.start(settings, text="Plant tulips in the garden", conversation_id="garden")
    await engine.stop()
    setup_text(TestProvider(), engine)
    await engine.start(settings, text="What did I say about the garden?", conversation_id="today")
    # The next typed turn reuses the session: what it said first is still this session.
    await engine.start(settings, text="The garden, I mean", conversation_id="today")
    catalogue = ConversationStore()
    for thread, title in (("garden", "Spring planting"), ("today", "Today")):
        entry = {"kind": "message", "role": "user", "text": title, "speaker": ""}
        catalogue.save(Conversation(id=thread, title=title, entries=[entry]))

    found = json.loads(
        await engine._handle_engine_tool("recall_conversations", {"query": "garden"})
    )

    assert [(r["conversation"], r["text"]) for r in found["results"]] == [
        ("Spring planting", "Plant tulips in the garden")
    ]


async def test_cancel_response_can_continue_on_the_same_channel(setup_text):
    provider = TestProvider(pause=True)
    engine = setup_text(provider)
    arrived = asyncio.Event()
    engine.transcription.connect(lambda *_: arrived.set())
    task = asyncio.create_task(engine.start(SETTINGS, text="First", conversation_id="thread"))
    await asyncio.wait_for(arrived.wait(), 3)
    kit = engine._kit
    await engine.cancel_response()
    await task
    assert engine.state == EngineState.READY
    assert engine._kit is kit and not provider.closed
    provider.release.set()
    await engine.start(SETTINGS, text="Continue", conversation_id="thread")
    assert engine.state == EngineState.READY and engine._kit is kit
    assert len(provider.contexts) == 2


async def test_full_stop_can_take_over_a_response_cancellation(setup_text, monkeypatch):
    provider = TestProvider(pause=True)
    engine = setup_text(provider)
    arrived, cancelled, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    engine.transcription.connect(lambda *_: arrived.set())
    task = asyncio.create_task(engine.start(SETTINGS, text="First"))
    await asyncio.wait_for(arrived.wait(), 3)
    cancel_start = engine._cancel_start

    async def delayed_cancel():
        await cancel_start()
        cancelled.set()
        await release.wait()

    monkeypatch.setattr(engine, "_cancel_start", delayed_cancel)
    cancel = asyncio.create_task(engine.cancel_response())
    await asyncio.wait_for(cancelled.wait(), 3)
    close = asyncio.create_task(engine.stop())
    await asyncio.sleep(0)
    release.set()
    await asyncio.wait_for(asyncio.gather(task, cancel, close), 3)
    assert engine.state == EngineState.IDLE and engine._kit is None
    assert provider.closed and not engine.text_session_open


async def test_live_and_changed_configuration_close_the_text_session(setup_text, monkeypatch):
    first = TestProvider()
    engine = setup_text(first)
    await engine.start(SETTINGS, text="First", conversation_id="thread")
    second = TestProvider()
    setup_text(second, engine)
    changed = {**SETTINGS, "system_prompt": "New instructions"}
    await engine.start(changed, text="Second", conversation_id="thread")
    assert first.closed and not second.closed
    assert second.contexts[0].system_prompt == "New instructions"

    async def live(_):
        assert second.closed
        assert engine._kit is None
        engine._enter_active()

    monkeypatch.setattr(engine, "_start_realtime", live)
    await engine.start(SETTINGS, conversation_id="thread", resume_context="Written turns")
    assert not engine.is_text and engine.state == EngineState.ACTIVE
    assert "Written turns" in engine._compose_session_prompt(SETTINGS)
