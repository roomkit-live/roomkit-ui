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
    (hook,) = kit.hooks.values()
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
        "typesafe_api_key": "ts",
    }
    assert not page.typesafe_api_key.isHidden()
    assert page.openai_api_key.isHidden()

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
