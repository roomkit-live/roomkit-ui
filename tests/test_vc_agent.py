"""The Voice Channel agent's speak policy and its diagnostic reporting.

The policy is an add-on: one that cannot run leaves the session answering
every turn with details available outside the chat, never fails the start.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest
from roomkit import ClassifierSpeakPolicy, MockClassifier
from roomkit.providers.ai.mock import MockAIProvider
from roomkit.speaking import SpeakDecision
from vc_harness import StreamingInputTTS, open_session, until

from roomkit_ui import vc_agent
from roomkit_ui.agent_hooks import register_agent_hooks
from roomkit_ui.vc_agent import agent_name, build_vc_agent


def _build(settings: dict, provider=None):
    notices: list[str] = []
    agent = build_vc_agent(settings, provider or MockAIProvider(), notices.append)
    return agent, notices


def test_always_answer_gives_the_channel_nothing():
    agent, notices = _build({"vc_speak_policy": "off"})

    assert agent.channel_options() == {}
    assert agent.summary == []
    assert notices == []


async def test_a_classifier_with_its_key_decides_as_the_named_assistant():
    agent, notices = _build(
        {"vc_speak_policy": "openai", "openai_api_key": "sk-test", "vc_agent_name": "Nova"}
    )

    assert isinstance(agent.channel_options()["speak_policy"], ClassifierSpeakPolicy)
    assert agent.summary == [
        {"name": "Decides when to speak", "description": "OpenAI Decisions, as Nova"}
    ]
    assert notices == []
    await agent.close()  # the OpenAI client it opened


@pytest.mark.parametrize("policy", ["openai", "jev"])
def test_a_classifier_without_its_key_leaves_the_assistant_answering(policy):
    agent, notices = _build({"vc_speak_policy": policy, "openai_api_key": ""})

    assert agent.channel_options() == {}
    assert notices == []
    assert agent.summary[0]["name"] == "Answers every turn"
    assert "no API key" in agent.summary[0]["description"]


def test_a_classifier_not_installed_names_its_install(monkeypatch):
    monkeypatch.setattr(vc_agent, "unavailable_reason", lambda key: f"{key} missing: pip …")

    agent, notices = _build({"vc_speak_policy": "jev", "typesafe_api_key": "k"})

    assert agent.channel_options() == {}
    assert notices == []
    assert "typesafe missing: pip …" in agent.summary[0]["description"]


def test_the_conversation_model_decides_only_when_it_answers_under_a_schema():
    agent, notices = _build({"vc_speak_policy": "llm"}, MockAIProvider(response_schema=True))
    assert "speak_policy" in agent.channel_options()
    assert notices == []

    agent, notices = _build({"vc_speak_policy": "llm"}, MockAIProvider())
    assert agent.channel_options() == {}
    assert notices == []
    assert "cannot answer the speaking decision's questions" in agent.summary[0]["description"]


def test_the_assistant_is_called_assistant_unless_named():
    assert agent_name({"vc_agent_name": "  "}) == "Assistant"
    assert agent_name({"vc_agent_name": "Nova"}) == "Nova"


async def test_an_unfinished_turn_gets_no_answer_or_technical_chat_line(qapp, caplog):
    # The real policy on scripted judgments: the classifier hears an
    # unfinished sentence: the assistant stays quiet without a technical chat row.
    caplog.set_level(logging.INFO, logger="roomkit_ui.agent_hooks")
    classifier = MockClassifier({"unfinished": 0.9})
    vc = await open_session(
        tts=StreamingInputTTS(),
        reply=["Sure."],
        transcripts=["So I was thinking that"],
        ai_options={"speak_policy": ClassifierSpeakPolicy(classifier, agent_name="Nova")},
    )
    notices: list[str] = []
    vc.engine.session_notice.connect(notices.append)
    register_agent_hooks(vc.kit, vc.engine)

    await vc.speak()
    await until(lambda: "Speak decision: silent" in caplog.text)
    await vc.kit.close()

    assert notices == []
    assert "not finished" in caplog.text
    assert vc.ai.contexts == []  # no turn ran
    assert classifier.calls


async def test_a_failed_policy_still_answers_and_logs_the_fallback(qapp, caplog):
    from roomkit.speaking import MockSpeakPolicy

    vc = await open_session(
        tts=StreamingInputTTS(),
        reply=["Sure."],
        ai_options={"speak_policy": MockSpeakPolicy(error=RuntimeError("down"))},
    )
    notices: list[str] = []
    vc.engine.session_notice.connect(notices.append)
    register_agent_hooks(vc.kit, vc.engine)

    await vc.speak()
    await until(lambda: len(vc.ai.contexts) == 1 and "Speak decision: speak" in caplog.text)
    await vc.kit.close()

    assert notices == []
    assert "fallback" in caplog.text


class _HookKit:
    def __init__(self):
        self.hooks = {}

    def hook(self, trigger, execution):
        def register(fn):
            self.hooks[str(trigger)] = fn
            return fn

        return register


async def test_repeated_decisions_stay_in_logs(caplog):
    from roomkit_ui.engine_state import EngineState

    kit, said = _HookKit(), []
    engine = SimpleNamespace(
        _state=EngineState.ACTIVE, session_notice=SimpleNamespace(emit=said.append)
    )
    register_agent_hooks(kit, engine)
    hook = next(fn for key, fn in kit.hooks.items() if key.lower().endswith("speak_decision"))
    event = SimpleNamespace(
        decision=SpeakDecision("speak", "fallback"), duration_ms=2000, asked_again=False
    )

    await hook(event, None)
    await hook(event, None)

    assert said == []
    assert caplog.text.count("Speak decision: speak") == 2


def test_the_agent_tab_saves_its_choices(qapp):
    from roomkit_ui.widgets.settings.vc_agent_fields import VCAgentPage

    page = VCAgentPage(
        {"vc_speak_policy": "jev", "typesafe_api_key": "ts", "vc_agent_name": "Nova"}
    )

    assert page.get_settings() == {
        "vc_speak_policy": "jev",
        "vc_agent_name": "Nova",
        "vc_agent_role": "",
        "vc_thinker": False,
        "vc_background": False,
        "vc_background_model": "",
    }
    assert not page.agent_name.isHidden()

    page.speak_policy.setCurrentIndex(0)  # Always answer
    assert page.agent_name.isHidden()
    assert page.get_settings()["vc_speak_policy"] == "off"


def test_the_session_drawer_lists_the_agent(qtbot):
    from PySide6.QtWidgets import QLabel, QWidget

    from roomkit_ui.widgets.session_drawer import SessionDrawer

    surface = QWidget()
    qtbot.addWidget(surface)
    drawer = SessionDrawer(surface)
    drawer.set_session(
        {
            "provider": "anthropic",
            "model": "claude",
            "tools": [],
            "agent": [{"name": "Decides when to speak", "description": "Jev, as Nova"}],
        }
    )

    rows = [label.text() for label in drawer.findChildren(QLabel)]
    assert "Decides when to speak" in rows
    assert "Jev, as Nova" in rows


def test_the_thinker_thinks_with_the_conversation_model_beside_a_policy():
    agent, notices = _build(
        {"vc_speak_policy": "llm", "vc_thinker": True}, MockAIProvider(response_schema=True)
    )

    assert set(agent.channel_options()) == {"speak_policy", "thinker"}
    assert [part["name"] for part in agent.summary] == [
        "Decides when to speak",
        "Thinks while listening",
    ]
    assert notices == []


def test_without_a_policy_there_is_nothing_to_think_on():
    # roomkit refuses a thinker without a speak policy; a policy left out has
    # already said why, so the thinker adds no second line.
    for settings in (
        {"vc_speak_policy": "off", "vc_thinker": True},
        {"vc_speak_policy": "openai", "openai_api_key": "", "vc_thinker": True},
    ):
        agent, notices = _build(settings, MockAIProvider(response_schema=True))
        assert "thinker" not in agent.channel_options()
        assert len(notices) <= 1


async def test_a_model_without_a_schema_decides_but_does_not_think():
    agent, notices = _build(
        {"vc_speak_policy": "openai", "openai_api_key": "sk-test", "vc_thinker": True},
        MockAIProvider(),
    )

    assert set(agent.channel_options()) == {"speak_policy"}
    assert notices == [
        "The assistant does not think while it listens: the conversation model "
        "cannot answer under a schema."
    ]
    await agent.close()


async def test_a_quiet_turn_is_thought_about_and_logged(qapp, caplog):
    from roomkit.speaking import MockSpeakPolicy, MockThinker, Thought

    thinker = MockThinker([Thought("They plan the meeting.", ("Shall I draft an agenda?",))])
    vc = await open_session(
        tts=StreamingInputTTS(),
        reply=["Sure."],
        transcripts=["I need to prepare tomorrow's meeting."],
        ai_options={
            "speak_policy": MockSpeakPolicy([SpeakDecision("silent", "not addressed")]),
            "thinker": thinker,
            "think_wait": 0.2,
        },
    )
    register_agent_hooks(vc.kit, vc.engine)
    caplog.set_level("INFO", logger="roomkit_ui.agent_hooks")

    await vc.speak()
    await until(lambda: "Thought (" in caplog.text)
    await vc.kit.close()

    assert "They plan the meeting." in caplog.text
    assert "Shall I draft an agenda?" in caplog.text
    assert vc.ai.contexts == []


def test_thinking_waits_for_a_speaking_decision_in_the_tab(qapp):
    from roomkit_ui.widgets.settings.vc_agent_fields import VCAgentPage

    page = VCAgentPage({"vc_speak_policy": "off", "vc_thinker": True})
    assert not page.thinker.isEnabled()

    page.speak_policy.setCurrentIndex(3)  # the conversation model
    assert page.thinker.isEnabled()
    assert page.get_settings()["vc_thinker"] is True


def test_background_work_needs_a_model_given_tools():
    agent, notices = _build({"vc_background": True})
    assert agent.background
    assert agent.summary == [
        {"name": "Works in the background", "description": "long requests run as tasks"}
    ]
    assert agent.channel_options() == {}  # set up on the kit, not the channel

    notices: list[str] = []
    agent = build_vc_agent({"vc_background": True}, MockAIProvider(), notices.append, tools=False)
    assert not agent.background
    assert "set without tool use" in notices[0]


@pytest.mark.parametrize(
    ("metadata", "line"),
    [
        ({"task_status": "completed", "duration_ms": 41_600}, "Background work done in 42 s."),
        ({"task_status": "completed"}, "Background work done."),
        ({"task_status": "failed", "error": "Traceback …"}, "Background work failed."),
        ({"task_status": "cancelled"}, "Background work cancelled."),
    ],
)
def test_the_chat_says_how_background_work_ended(metadata, line):
    from roomkit_ui.agent_hooks import task_ended_notice

    assert task_ended_notice(SimpleNamespace(metadata=metadata)) == line


def test_a_long_task_is_shortened_in_the_chat():
    from roomkit_ui.agent_hooks import task_started_notice

    line = task_started_notice(SimpleNamespace(metadata={"task_input": "word " * 60}))

    assert line.startswith("Working in the background: word word")
    assert line.endswith("…")
    assert len(line) < 160


async def test_a_background_task_works_with_the_session_tools_and_comes_back():
    # The agent itself is the worker, in a room of its own attached without
    # the session room's metadata: the tools reach it through the turn config.
    from roomkit import ChannelCategory, RoomKit, SMSChannel
    from roomkit.channels.ai import AIChannel
    from roomkit.providers.sms.mock import MockSMSProvider

    from roomkit_ui.engine_state import EngineState
    from roomkit_ui.toolset import ToolSet

    tools = ToolSet(
        builtin=[
            {"name": "get_current_time", "description": "Time.", "parameters": {}},
            {"name": "end_conversation", "description": "Hang up.", "parameters": {}},
        ],
        cli=[],
        mcp=[],
    )
    provider = MockAIProvider(responses=["Three mails need an answer.", "You have three."])
    ai = AIChannel("ai", provider=provider, config_provider=tools.turn_config())
    kit = RoomKit()
    kit.register_channel(ai)
    kit.register_channel(SMSChannel("sms", provider=MockSMSProvider()))
    kit.setup_background(ai)
    await kit.create_room(room_id="main")
    await kit.attach_channel("main", "sms")
    await kit.attach_channel("main", "ai", category=ChannelCategory.INTELLIGENCE)
    said: list[str] = []
    engine = SimpleNamespace(
        _state=EngineState.ACTIVE,
        _background_tasks=0,
        session_notice=SimpleNamespace(emit=said.append),
    )
    register_agent_hooks(kit, engine)

    await kit.start_task("main", "ai", "Summarize this week's mails")
    await until(lambda: len(said) == 2 and len(provider.calls) == 2)
    await kit.close()

    worker, relay = provider.calls
    assert "get_current_time" in {t.name for t in worker.tools}
    # Away from the conversation, a task cannot hang it up.
    assert "end_conversation" not in {t.name for t in worker.tools}
    assert "Three mails need an answer." in "\n".join(str(m.content) for m in relay.messages)
    assert said[0] == "Working in the background: Summarize this week's mails"
    assert said[1].startswith("Background work done")
    assert engine._background_tasks == 0


def test_the_agent_tab_saves_background_work(qapp):
    from roomkit_ui.widgets.settings.vc_agent_fields import VCAgentPage

    page = VCAgentPage({"vc_background": True})

    assert page.get_settings()["vc_background"] is True


# -- a model of its own for the tasks -----------------------------------------------------


@pytest.fixture
def made(monkeypatch):
    """The llama.cpp providers the agent creates for its tasks: mocks, with
    the settings and role each was made from."""
    created: list[tuple[dict, str, MockAIProvider]] = []

    def create(settings, *, role="conversation"):
        provider = MockAIProvider(responses=["done"])
        created.append((settings, role, provider))
        return provider

    monkeypatch.setattr("roomkit_ui.providers.llamacpp.create", create)
    return created


def test_tasks_run_on_the_llamacpp_model_set_for_them(made):
    from roomkit_ui.settings import _DEFAULTS

    agent, notices = _build(
        {
            **_DEFAULTS,
            "vc_background": True,
            "vc_background_model": "llamacpp",
            "vc_background_llamacpp_model": "/models/b.gguf",
            "vc_llm_provider": "anthropic",
        }
    )

    ((settings, role, provider),) = made
    assert agent.background
    assert agent.worker is provider
    assert agent.worker_provider == "llamacpp"
    assert role == "background"
    assert settings["vc_llamacpp_model"] == "/models/b.gguf"
    assert settings["vc_llamacpp_thinking"] is True  # nobody waits on a task
    assert agent.summary == [
        {"name": "Works in the background", "description": "long requests run as tasks, on mock"}
    ]
    assert notices == []


def test_otherwise_the_conversation_model_is_its_own_worker(made):
    agent, _ = _build({"vc_background": True, "vc_background_model": ""})

    assert agent.background
    assert agent.worker is None
    assert made == []


def test_tasks_run_on_a_cloud_model_at_its_own_reasoning():
    from roomkit_ui.engine_vc_helpers import reasoning_options
    from roomkit_ui.providers import llm_settings

    settings = {
        "vc_background": True,
        "vc_background_model": "anthropic",
        "vc_background_anthropic_model": "claude-opus-5-5",
        "anthropic_api_key": "k",
        "vc_llm_provider": "local",
        # Set for spoken replies: quick, no thinking.
        "vc_anthropic_thinking": "off",
        "vc_anthropic_effort": "low",
    }
    agent, notices = _build(settings)

    assert agent.worker_provider == "anthropic"
    assert agent.worker.model_name == "claude-opus-5-5"
    assert agent.worker_note == (
        "Runs the background tasks, reasoning as its model does by default."
    )
    assert reasoning_options(llm_settings(settings, "background"), "anthropic") == {
        "max_tokens": 16_000
    }
    assert notices == []


def test_a_cloud_model_without_its_key_leaves_the_tasks_on_the_conversation_model():
    agent, notices = _build(
        {"vc_background": True, "vc_background_model": "openai", "openai_api_key": ""}
    )

    assert agent.background and agent.worker is None
    assert notices == [
        "Background tasks run on the conversation model: "
        "OpenAI API key is required. Open Settings to enter it."
    ]


def test_a_model_that_cannot_run_leaves_the_tasks_on_the_conversation_model(monkeypatch):
    from roomkit_ui.features import FeatureUnavailableError

    def create(_settings, *, role):
        raise FeatureUnavailableError("llama.cpp is not installed.", "llamacpp")

    monkeypatch.setattr("roomkit_ui.providers.llamacpp.create", create)
    agent, notices = _build({"vc_background": True, "vc_background_model": "llamacpp"})

    assert agent.background
    assert agent.worker is None
    assert notices == [
        "Background tasks run on the conversation model: llama.cpp is not installed."
    ]


def test_a_gguf_is_named_by_its_file():
    model = SimpleNamespace(model_name="/models/Ornith-1.5-35B-Q8_0.gguf")

    assert vc_agent._model_label(model) == "Ornith-1.5-35B-Q8_0.gguf"


def test_the_agent_tab_sets_the_tasks_model(qapp):
    from roomkit_ui.widgets.settings.vc_agent_fields import VCAgentPage

    page = VCAgentPage(
        {
            "vc_background": False,
            "vc_background_model": "llamacpp",
            "vc_llamacpp_model": "/models/a.gguf",
        }
    )

    tasks = page.tasks_llm
    gguf = tasks.fields["llamacpp_model"]
    assert tasks.provider.currentText() == "llama.cpp (local GGUF)"
    assert not tasks.provider.isEnabled()  # waits for background work
    assert not gguf.isHidden()
    assert "a.gguf" in gguf.placeholderText()  # Think · LLM's, until set
    page.background.setChecked(True)
    assert tasks.provider.isEnabled() and gguf.isEnabled()
    gguf.setText(" /models/b.gguf ")
    tasks.fields["llamacpp_context"].setText("32768")
    tasks.fields["llamacpp_thinking"].setChecked(False)
    out = page.get_settings()
    assert out["vc_background_model"] == "llamacpp"
    assert out["vc_background_llamacpp_model"] == "/models/b.gguf"
    assert out["vc_background_llamacpp_context"] == "32768"
    assert out["vc_background_llamacpp_thinking"] is False

    tasks.provider.setCurrentIndex(0)  # the conversation model
    assert gguf.isHidden()
    assert page.get_settings()["vc_background_model"] == ""


def test_the_agent_tab_offers_every_llm_for_the_tasks(qapp):
    from roomkit_ui.providers import LLM_PROVIDERS
    from roomkit_ui.widgets.settings.vc_agent_fields import VCAgentPage

    page = VCAgentPage(
        {
            "vc_background": True,
            "vc_background_openai_model": "gpt-5.5",
            "vc_gemini_model": "gemini-3.8-pro",
        }
    )
    tasks = page.tasks_llm
    choices = [tasks.provider.itemText(i) for i in range(tasks.provider.count())]

    assert choices == ["The conversation model", *(label for label, _ in LLM_PROVIDERS)]
    tasks.provider.setCurrentIndex(choices.index("Google Gemini"))
    gemini = tasks.fields["gemini_model"]
    assert not gemini.isHidden() and tasks.fields["openai_model"].isHidden()
    assert gemini.currentText() == "gemini-3.8-pro"  # starts on Think · LLM's

    out = page.get_settings()
    assert out["vc_background_model"] == "gemini"
    assert out["vc_background_gemini_model"] == "gemini-3.8-pro"
    # Another provider's model is kept, not overwritten by what its field shows.
    assert out["vc_background_openai_model"] == "gpt-5.5"
    assert "vc_background_anthropic_model" not in out


async def test_a_task_runs_on_its_own_model_with_the_session_tools(qapp, monkeypatch):
    from roomkit import ChannelCategory, RoomKit, SMSChannel
    from roomkit.providers.ai.base import AIResponse, AIToolCall
    from roomkit.providers.sms.mock import MockSMSProvider
    from vc_harness import FakeEngine

    from roomkit_ui.engine import Engine
    from roomkit_ui.hooks import register_vc_hooks
    from roomkit_ui.settings import _DEFAULTS
    from roomkit_ui.toolset import ToolSet

    class Worker(MockAIProvider):
        started = False

        async def start(self):
            self.started = True

    hang_up = AIToolCall(id="c1", name="end_conversation", arguments={})
    worker = Worker(
        ai_responses=[
            AIResponse(content="", tool_calls=[hang_up], usage={"input_tokens": 800}),
            AIResponse(content="Three mails.", usage={"input_tokens": 900}),
        ]
    )
    conversation = MockAIProvider(
        ai_responses=[AIResponse(content="You have three.", usage={"input_tokens": 7})]
    )
    monkeypatch.setattr("roomkit_ui.providers.llamacpp.create", lambda _s, *, role: worker)
    engine = Engine()

    async def tools(_settings, _provider):
        builtin = [
            {"name": "get_current_time", "description": "Time.", "parameters": {}},
            {"name": "end_conversation", "description": "Hang up.", "parameters": {}},
        ]
        return ToolSet(builtin=builtin, cli=[], mcp=[]), None

    monkeypatch.setattr(engine, "_load_vc_tools", tools)
    settings = {
        **_DEFAULTS,
        "vc_llm_provider": "anthropic",
        "vc_background": True,
        "vc_background_model": "llamacpp",
    }
    ai, _, _ = await engine._build_vc_ai_channel(settings, conversation, "anthropic", "Be brief.")
    background = engine._vc_agent.worker_channel
    # A local model: every tool in its prompt, as for a local conversation model.
    assert background._tool_search is False
    await until(lambda: worker.started)  # loaded while the session opens

    kit = RoomKit()
    kit.register_channel(SMSChannel("sms", provider=MockSMSProvider()))
    kit.register_channel(ai)
    engine._vc_agent.setup_background(kit, ai)
    await kit.create_room(room_id="main")
    await kit.attach_channel("main", "sms")
    await kit.attach_channel("main", "ai", category=ChannelCategory.INTELLIGENCE)

    class Usage(FakeEngine):
        def __init__(self):
            super().__init__()
            self.usage: list[dict] = []

        def _accumulate_usage(self, usage, *, task=False):
            self.usage.append((usage["input_tokens"], task))

    hooks = Usage()
    register_vc_hooks(kit, hooks)

    await kit.start_task("main", "ai", "Summarize this week's mails")
    await until(lambda: len(worker.calls) == 2 and conversation.calls and len(hooks.usage) == 2)
    await kit.close()

    assert "get_current_time" in {t.name for t in worker.calls[0].tools}
    assert "end_conversation" not in {t.name for t in worker.calls[0].tools}
    # Called anyway, roomkit refuses it: never run.
    told = "\n".join(str(m.content) for m in worker.calls[1].messages)
    assert "end_conversation" in told and "is not declared" in told
    relay = "\n".join(str(m.content) for m in conversation.calls[0].messages)
    assert "Three mails." in relay
    # Never attached to the session room, where it would answer every turn.
    assert await kit.store.get_binding("main", "background") is None
    # Its tokens (both its calls) are another model's: priced as that model's.
    assert sorted(hooks.usage) == [(7, False), (1700, True)]


async def test_a_spoken_turn_is_offered_background_work_beside_tool_search(
    qapp, monkeypatch, caplog
):
    # Tool Search hides the MCP tools behind find_tools: the agent must still
    # see work_in_background to start a task.
    from roomkit import ChannelCategory, RoomKit, SMSChannel, TextContent
    from roomkit.models.delivery import InboundMessage
    from roomkit.providers.sms.mock import MockSMSProvider

    from roomkit_ui.engine import Engine
    from roomkit_ui.settings import _DEFAULTS
    from roomkit_ui.toolset import ToolSet

    many = [
        {"name": f"tool_{i}", "description": "Does one thing. " * 30, "parameters": {}}
        for i in range(150)
    ]

    async def tools(_settings, _provider):
        builtin = [{"name": "get_current_time", "description": "Time.", "parameters": {}}]
        return ToolSet(builtin=builtin, cli=[], mcp=many), None

    engine = Engine()
    monkeypatch.setattr(engine, "_load_vc_tools", tools)
    conversation = MockAIProvider(responses=["On it."])
    settings = {
        **_DEFAULTS,
        "vc_llm_provider": "anthropic",
        "vc_background": True,
        "tool_search_mode": "on",
    }
    ai, _, _ = await engine._build_vc_ai_channel(settings, conversation, "anthropic", "Be brief.")
    kit = RoomKit()
    kit.register_channel(SMSChannel("sms", provider=MockSMSProvider()))
    kit.register_channel(ai)
    with caplog.at_level(logging.INFO, logger="roomkit_ui.vc_agent"):
        engine._vc_agent.setup_background(kit, ai)
    await kit.create_room(room_id="main")
    await kit.attach_channel("main", "sms")
    await kit.attach_channel("main", "ai", category=ChannelCategory.INTELLIGENCE)

    await kit.process_inbound(
        InboundMessage(channel_id="sms", sender_id="u", content=TextContent(body="Go on"))
    )
    await kit.close()

    declared = {t.name for t in conversation.calls[0].tools}
    assert "tool_7" not in declared  # behind find_tools
    assert "work_in_background" in declared
    assert "Background work: tasks run on the conversation model" in caplog.text


async def test_the_tasks_model_loads_while_the_session_opens_and_says_if_it_cannot():
    class Server:
        def __init__(self, error=None):
            self.error = error

        async def start(self):
            if self.error:
                raise self.error

    said: list[str] = []
    await vc_agent.warm_up_worker(Server(), said.append)
    assert said == []

    await vc_agent.warm_up_worker(Server(RuntimeError("no space left")), said.append)
    assert said == ["The background tasks' model did not start: no space left"]


def test_the_session_details_list_the_tasks_model(monkeypatch):
    from roomkit_ui.session_models import voice_channel_models

    gguf = "/private/models/Ornith-Q8_0.gguf"
    monkeypatch.setattr(
        "roomkit_ui.providers.llamacpp.create",
        lambda _settings, *, role: SimpleNamespace(model_name=gguf),
    )
    settings = {
        "vc_background": True,
        "vc_background_model": "llamacpp",
        "vc_background_llamacpp_thinking": False,
    }
    agent, _ = _build(settings)

    row = voice_channel_models(
        settings,
        stt=SimpleNamespace(),
        stt_provider="local",
        llm=MockAIProvider(),
        tts=SimpleNamespace(),
        agent=agent,
    )[-1]

    assert row == {
        "role": "Background tasks · LLM",
        "provider": "llamacpp",
        "model": "Ornith-Q8_0.gguf",  # no private path in the details
        "description": "Runs the background tasks. Thinking off.",
    }


async def test_the_role_reaches_the_deciding_model():
    from roomkit.models.enums import ChannelType
    from roomkit.models.event import EventSource, RoomEvent, TextContent
    from roomkit.speaking.base import SpeakTurn

    agent, _ = _build(
        {
            "vc_speak_policy": "openai",
            "openai_api_key": "sk-test",
            "vc_agent_name": "Nova",
            "vc_agent_role": "  Sylvain's assistant during his calls  ",
        }
    )
    event = RoomEvent(
        room_id="r",
        source=EventSource(channel_id="voice", channel_type=ChannelType.VOICE),
        content=TextContent(body="Nova?"),
    )
    state = agent.channel_options()["speak_policy"].state(SpeakTurn(event=event))
    assert state["agent"] == {"name": "Nova", "role": "Sylvain's assistant during his calls"}
    await agent.close()


def test_what_the_deciding_model_is_asked_is_roomkits_own():
    import json

    from roomkit.speaking.classifier import QUESTIONS, RESUME, THOUGHT_QUESTIONS
    from roomkit.speaking.listening import ASKED_ME, LIFT, LISTEN_REQUEST

    brief = vc_agent.speak_policy_brief(
        {"vc_agent_name": "Nova", "vc_agent_role": "Sylvain's assistant", "user_name": "Sylvain"}
    )

    example = json.loads(brief.split("\n\n")[1])  # what it reads, as roomkit builds it
    assert example["agent"] == {"name": "Nova", "role": "Sylvain's assistant"}
    assert example["last_turn"] == {"speaker": "Sylvain", "text": "Nova, where were we exactly?"}
    assert example["people"] == ["Sylvain", "Speaker B"]
    asked = [*QUESTIONS.items(), *THOUGHT_QUESTIONS.items()]
    asked += [("listen_request", LISTEN_REQUEST), ("asked_me", ASKED_ME), ("lift", LIFT)]
    asked += [("resume", RESUME)]
    for name, question in asked:
        assert f"\n{name} — " in brief
        assert " ".join(question.instructions.split()) in " ".join(brief.split())


def test_the_agent_tab_shows_what_it_is_asked_with_the_role_typed(qapp, monkeypatch):
    from roomkit_ui.widgets.settings import vc_agent_fields
    from roomkit_ui.widgets.settings.vc_agent_fields import VCAgentPage

    shown: list[str] = []
    monkeypatch.setattr(
        vc_agent_fields._BriefDialog, "exec", lambda d: shown.append(d.text.toPlainText())
    )
    page = VCAgentPage({"vc_speak_policy": "jev", "vc_agent_role": "Saved role"})
    assert page.agent_role.toPlainText() == "Saved role" and not page.show_brief.isHidden()

    page.agent_name.setText("Nova")
    page.agent_role.setPlainText("For the D&D table")
    page.show_brief.click()
    assert '"name": "Nova"' in shown[0] and '"role": "For the D&D table"' in shown[0]
    assert page.get_settings()["vc_agent_role"] == "For the D&D table"

    page.speak_policy.setCurrentIndex(0)  # Always answer: nothing is asked
    assert page.agent_role.isHidden() and page.show_brief.isHidden()
