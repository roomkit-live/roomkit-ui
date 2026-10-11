"""The Voice Channel agent's speak policy: built from the settings, said in the chat.

The policy is an add-on: one that cannot run leaves the session answering
every turn and says why, never fails the start.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from roomkit import ClassifierSpeakPolicy, MockClassifier
from roomkit.providers.ai.mock import MockAIProvider
from roomkit.speaking import SpeakDecision
from vc_harness import StreamingInputTTS, open_session, until

from roomkit_ui import vc_agent
from roomkit_ui.agent_hooks import FALLBACK_NOTICE, register_agent_hooks, speak_decision_notice
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
    assert notices == [
        "The assistant answers every turn: the speaking decision has no API key "
        "(Settings → AI → Voice Channel → Agent)."
    ]


def test_a_classifier_not_installed_names_its_install(monkeypatch):
    monkeypatch.setattr(vc_agent, "unavailable_reason", lambda key: f"{key} missing: pip …")

    agent, notices = _build({"vc_speak_policy": "jev", "typesafe_api_key": "k"})

    assert agent.channel_options() == {}
    assert notices == ["The assistant answers every turn: typesafe missing: pip …"]


def test_the_conversation_model_decides_only_when_it_answers_under_a_schema():
    agent, notices = _build({"vc_speak_policy": "llm"}, MockAIProvider(response_schema=True))
    assert "speak_policy" in agent.channel_options()
    assert notices == []

    agent, notices = _build({"vc_speak_policy": "llm"}, MockAIProvider())
    assert agent.channel_options() == {}
    assert "cannot answer the speaking decision's questions" in notices[0]


def test_the_assistant_is_called_assistant_unless_named():
    assert agent_name({"vc_agent_name": "  "}) == "Assistant"
    assert agent_name({"vc_agent_name": "Nova"}) == "Nova"


@pytest.mark.parametrize(
    ("decision", "asked_again", "line"),
    [
        (SpeakDecision("silent", "not finished"), False, "Stayed quiet — you had not finished."),
        (
            SpeakDecision("silent", "asked to listen"),
            False,
            "Stayed quiet — listening until spoken to.",
        ),
        (
            SpeakDecision("silent", "a reason of its own"),
            False,
            "Stayed quiet — a reason of its own.",
        ),
        # Each silence of a listening room repeats the one said when it began.
        (SpeakDecision("silent", "listening"), False, None),
        # Taken again once the agent thought: the first decision was shown.
        (SpeakDecision("silent", "not addressed"), True, None),
        (SpeakDecision("speak", "addressed"), False, None),
        (SpeakDecision("offer", "wondered about"), False, None),
    ],
)
def test_the_chat_says_why_the_assistant_stayed_quiet(decision, asked_again, line):
    assert speak_decision_notice(decision, asked_again=asked_again) == line


async def test_a_turn_the_speaker_had_not_finished_gets_no_answer_and_a_line(qapp):
    # The real policy on scripted judgments: the classifier hears an
    # unfinished sentence, the assistant stays quiet and the chat says why.
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
    await until(lambda: bool(notices))
    await vc.kit.close()

    assert notices == ["Stayed quiet — you had not finished."]
    assert vc.ai.contexts == []  # no turn ran
    assert classifier.calls


async def test_a_policy_that_fails_lets_the_assistant_answer_and_says_so(qapp):
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
    await until(lambda: len(vc.ai.contexts) == 1 and bool(notices))
    await vc.kit.close()

    assert notices == [FALLBACK_NOTICE]


class _HookKit:
    def __init__(self):
        self.hooks = {}

    def hook(self, trigger, execution):
        def register(fn):
            self.hooks[str(trigger)] = fn
            return fn

        return register


async def test_a_failing_policy_is_said_once_per_session():
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

    assert said == [FALLBACK_NOTICE]


def test_the_agent_tab_saves_its_choices(qapp):
    from roomkit_ui.widgets.settings.vc_agent_fields import VCAgentPage

    page = VCAgentPage(
        {"vc_speak_policy": "jev", "typesafe_api_key": "ts", "vc_agent_name": "Nova"}
    )

    assert page.get_settings() == {
        "vc_speak_policy": "jev",
        "vc_agent_name": "Nova",
        "vc_thinker": False,
        "vc_background": False,
    }
    assert not page.agent_name.isHidden()

    page.speak_policy.setCurrentIndex(0)  # Always answer
    assert page.agent_name.isHidden()
    assert page.get_settings()["vc_speak_policy"] == "off"


def test_the_info_bar_lists_the_agent(qapp):
    from PySide6.QtWidgets import QLabel

    from roomkit_ui.widgets.session_info import SessionInfoBar

    bar = SessionInfoBar()
    bar.set_session(
        {
            "provider": "anthropic",
            "model": "claude",
            "tools": [],
            "agent": [{"name": "Decides when to speak", "description": "Jev, as Nova"}],
        }
    )

    rows = [label.text() for label in bar.findChildren(QLabel)]
    assert any("Decides when to speak" in row and "Jev, as Nova" in row for row in rows)
    bar.deleteLater()


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
        builtin=[{"name": "get_current_time", "description": "Time.", "parameters": {}}],
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
    assert "Three mails need an answer." in "\n".join(str(m.content) for m in relay.messages)
    assert said[0] == "Working in the background: Summarize this week's mails"
    assert said[1].startswith("Background work done")
    assert engine._background_tasks == 0


def test_the_agent_tab_saves_background_work(qapp):
    from roomkit_ui.widgets.settings.vc_agent_fields import VCAgentPage

    page = VCAgentPage({"vc_background": True})

    assert page.get_settings()["vc_background"] is True
