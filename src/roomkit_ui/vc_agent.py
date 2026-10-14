"""The Voice Channel agent's turn-taking: whether it speaks on a turn, what
it thinks while it listens, and the work it runs in the background.

roomkit 0.96 gives an AIChannel a speak policy: on each turn it would answer,
the policy says speak, offer (one short sentence of what it could add) or
stay silent.  ``ClassifierSpeakPolicy`` decides on narrow questions a
classifier answers in one call (has the speaker finished, put it off, asked
for quiet, addressed the agent).  A thinker keeps the agent's thought on the
turns it stays silent on; back with something worth saying, the policy
decides again and the agent may offer.  A thinker needs a speak policy.
roomkit 0.97's ``setup_background`` gives the agent ``work_in_background``:
long work runs as a task, in a room of its own, while the conversation goes
on, and its result comes back as a turn the agent speaks.  The task runs on
the agent itself, or on a worker channel with a model of its own: any LLM
Think · LLM offers, llama.cpp on this computer included.

Both are add-ons: one that cannot run is left out of the session. Speaking
policy problems go to session details and logs; other add-ons explain their
absence in the chat.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from roomkit_ui.features import SPEAK_POLICY_FEATURES, unavailable_reason
from roomkit_ui.session_models import SessionModel, decision_model

logger = logging.getLogger(__name__)

# vc_speak_policy → the classifier that answers the policy's questions.
_CLASSIFIER_NAMES = {
    "openai": "OpenAI Decisions",
    "jev": "TypeSafe Jev",
    "llm": "the conversation model",
}

# (label, vc_speak_policy) — the Agent tab's "Speaking" combo.
SPEAK_POLICIES: list[tuple[str, str]] = [
    ("Always answer", "off"),
    *((f"Decide — {name}", policy) for policy, name in _CLASSIFIER_NAMES.items()),
]

DEFAULT_AGENT_NAME = "Assistant"

# The channel background tasks run on when they have a model of their own.
# Registered on the kit, never attached to the session room: there it would
# answer every turn.
BACKGROUND_WORKER = "background"

# A local model's thinking switch: the Agent tab sets it for the tasks.
_THINKING_FIELDS = {"llamacpp": "vc_llamacpp_thinking", "local": "vc_local_thinking"}

# The settings key holding each classifier's API key.
_CLASSIFIER_KEYS = {"openai": "openai_api_key", "jev": "typesafe_api_key"}


@dataclass
class VCAgent:
    """What a session's AIChannel is given beyond its model, and what to close."""

    speak_policy: Any = None
    thinker: Any = None
    # Set up on the kit, not given to the channel (kit.setup_background).
    background: bool = False
    # The model background tasks run on, when not the conversation's: its
    # provider name and provider; the engine builds its channel.
    worker_provider: str = ""
    worker: Any = None
    worker_channel: Any = None
    worker_model: str = ""  # its model as the session details name it
    worker_note: str = ""
    summary: list[dict] = field(default_factory=list)
    decision: SessionModel | None = None
    _closables: list[Any] = field(default_factory=list)

    def channel_options(self) -> dict[str, Any]:
        """``AIChannel`` keyword arguments; empty when nothing is enabled."""
        options = {"speak_policy": self.speak_policy, "thinker": self.thinker}
        return {name: part for name, part in options.items() if part is not None}

    def setup_background(self, kit: Any, ai_channel: Any) -> None:
        """Give *ai_channel* ``work_in_background`` on *kit*, its tasks run on
        the worker channel when there is one (the kit then closes it)."""
        if not self.background:
            return
        worker = self.worker_channel
        if worker is not None:
            kit.register_channel(worker)
        kit.setup_background(ai_channel, worker=None if worker is None else worker.channel_id)
        logger.info(
            "Background work: tasks run on %s",
            "the conversation model"
            if worker is None
            else f"{self.worker_provider} ({self.worker_model})",
        )

    async def close(self) -> None:
        """Close the clients this agent opened (roomkit closes none of them)."""
        for part in self._closables:
            try:
                await part.close()
            except Exception:
                logger.debug("closing %s failed", type(part).__name__, exc_info=True)
        self._closables.clear()


def agent_name(settings: dict) -> str:
    """What people call the assistant: the speak policy hears it addressed by it."""
    return str(settings.get("vc_agent_name") or "").strip() or DEFAULT_AGENT_NAME


def agent_role(settings: dict) -> str:
    """What the assistant is there for, in the user's words: the speak policy's
    classifier reads it with every turn, to judge whether a turn is for it."""
    return str(settings.get("vc_agent_role") or "").strip()


def _speak_policy(classifier: Any, settings: dict) -> Any:
    from roomkit import ClassifierSpeakPolicy

    return ClassifierSpeakPolicy(
        classifier, agent_name=agent_name(settings), agent_role=agent_role(settings)
    )


def speak_policy_brief(settings: dict) -> str:
    """What the speaking classifier reads and is asked on a turn, written out from
    roomkit's own policy (never a copy): an example of what it reads, each question
    word for word, and how the answers decide."""
    import json
    import textwrap

    from roomkit.classifiers.base import ChoiceQuestion, ScoreQuestion
    from roomkit.models.enums import ChannelType
    from roomkit.models.event import EventSource, RoomEvent, TextContent
    from roomkit.speaking.base import SpeakTurn
    from roomkit.speaking.classifier import RESUME, THOUGHT_QUESTIONS, compose
    from roomkit.speaking.listening import ASKED_ME, LIFT

    policy = _speak_policy(None, settings)
    name = agent_name(settings)
    you = str(settings.get("user_name") or "").strip() or "You"

    def said(body: str, channel: str = "voice") -> RoomEvent:
        kind = ChannelType.AI if channel == "ai" else ChannelType.VOICE
        return RoomEvent(
            room_id="example",
            source=EventSource(channel_id=channel, channel_type=kind),
            content=TextContent(body=body),
        )

    recent = (
        said("Shall we pick the campaign up tonight?"),
        said("Yes. The last session stopped at the door of the crypt.", "ai"),
        said("Sounds good to me."),
    )
    last = said(f"{name}, where were we exactly?")
    speakers = {recent[0].id: you, recent[2].id: "Speaker B", last.id: you}
    turn = SpeakTurn(
        event=last,
        recent=recent,
        people=(you, "Speaker B"),
        channel_id="ai",
        speakers=speakers,
    )

    def question(key: str, q: Any) -> str:
        if isinstance(q, ScoreQuestion):
            kind = f"a score from 0 to {len(q.levels) - 1}"
            extra = [f"{i}: {level}" for i, level in enumerate(q.levels)]
        elif isinstance(q, ChoiceQuestion):
            kind, extra = "a choice", [f"{k}: {v}" for k, v in q.options.items()]
        else:
            kind, extra = "yes or no (a probability)", []
        lines = [
            f"{key} — {kind}",
            textwrap.fill(q.instructions, 88, initial_indent="  ", subsequent_indent="  "),
        ]
        lines += [
            textwrap.fill(e, 88, initial_indent="    ", subsequent_indent="      ") for e in extra
        ]
        return "\n".join(lines)

    sections = [
        "WHAT IT READS ON EVERY TURN (an example)",
        json.dumps(policy.state(turn), indent=2, ensure_ascii=False),
        "THE QUESTIONS IT ANSWERS",
        *(question(k, q) for k, q in policy.questions(turn).items()),
        "WHILE ASKED TO ONLY LISTEN (instead of listen_request)",
        question("asked_me", ASKED_ME),
        question("lift", LIFT),
        "RIGHT AFTER IT WAS CUT OFF",
        question("resume", RESUME),
        "WHEN IT HAS SOMETHING TO ADD (Think while listening)",
        *(question(k, q) for k, q in THOUGHT_QUESTIONS.items()),
        "HOW THE ANSWERS DECIDE",
        textwrap.fill(" ".join((compose.__doc__ or "").split()), 88),
    ]
    return "\n\n".join(sections)


def build_vc_agent(
    settings: dict, ai_provider: Any, notice: Callable[[str], None], *, tools: bool = True
) -> VCAgent:
    """The session's agent parts from the settings; *notice* tells the chat
    what was left out and why.  *tools* is False when the model is given
    none (a local model without tool use)."""
    agent = VCAgent()
    _add_speak_policy(agent, settings, ai_provider)
    _add_thinker(agent, settings, ai_provider, notice)
    _add_background(agent, settings, notice, tools=tools)
    return agent


def _add_speak_policy(agent: VCAgent, settings: dict, ai_provider: Any) -> None:
    policy = settings.get("vc_speak_policy", "off")
    if policy not in _CLASSIFIER_BUILDERS:
        return
    reason = _classifier_unavailable(policy, settings, ai_provider)
    if reason is not None:
        logger.warning("Speaking policy unavailable: %s", reason)
        agent.summary.append({"name": "Answers every turn", "description": reason})
        return

    classifier = _CLASSIFIER_BUILDERS[policy](settings, ai_provider)
    agent._closables.append(classifier)
    agent.speak_policy = _speak_policy(classifier, settings)
    agent.decision = decision_model(
        policy, classifier, ai_provider, settings.get("vc_llm_provider", "anthropic")
    )
    agent.summary.append(
        {
            "name": "Decides when to speak",
            "description": f"{_CLASSIFIER_NAMES[policy]}, as {agent_name(settings)}",
        }
    )


def _add_thinker(
    agent: VCAgent, settings: dict, ai_provider: Any, notice: Callable[[str], None]
) -> None:
    """The conversation model thinks on the turns the policy leaves silent.

    Without a policy there is no silent turn to think on: the setting waits
    for one (the Agent tab greys it out), and a policy left out has said why.
    """
    if not settings.get("vc_thinker") or agent.speak_policy is None:
        return
    if not getattr(ai_provider, "supports_response_schema", False):
        notice(
            "The assistant does not think while it listens: the conversation model "
            "cannot answer under a schema."
        )
        return

    from roomkit import LLMThinker

    # The session's provider: the thinker leaves it open on close().
    agent.thinker = LLMThinker(ai_provider)
    agent._closables.append(agent.thinker)
    agent.summary.append(
        {"name": "Thinks while listening", "description": "the conversation model"}
    )


def _add_background(
    agent: VCAgent, settings: dict, notice: Callable[[str], None], *, tools: bool
) -> None:
    """Background work is a tool call: a model given no tool cannot start it."""
    if not settings.get("vc_background"):
        return
    if not tools:
        notice(
            "The assistant does not work in the background: the local model is set "
            "without tool use (Settings → AI → Voice Channel → LLM)."
        )
        return
    agent.background = True
    description = "long requests run as tasks"
    _add_worker(agent, settings, notice)
    if agent.worker is not None:
        description += f", on {agent.worker_model}"
    agent.summary.append({"name": "Works in the background", "description": description})


def _add_worker(agent: VCAgent, settings: dict, notice: Callable[[str], None]) -> None:
    """The model the tasks run on when it is not the conversation's (Agent
    tab → Tasks run on).  One that cannot run leaves them on the conversation
    model, and the chat says why."""
    from roomkit_ui.providers import create_ai_provider, has_own_llm, llm_settings

    if not has_own_llm(settings, "background"):
        return
    own = llm_settings(settings, "background")
    name = own["vc_llm_provider"]
    try:
        agent.worker = create_ai_provider(name, own, role="background")
    except Exception as exc:  # not installed, no key, a bad setting: said in the chat
        logger.warning("Background model unavailable: %s", exc)
        notice(f"Background tasks run on the conversation model: {exc}")
        return
    agent.worker_provider = name
    agent.worker_model = _model_label(agent.worker)
    if name in _THINKING_FIELDS:
        thinking = "on" if own.get(_THINKING_FIELDS[name]) else "off"
        agent.worker_note = f"Runs the background tasks. Thinking {thinking}."
    else:
        agent.worker_note = "Runs the background tasks, reasoning as its model does by default."


async def warm_up_worker(worker: Any, notice: Callable[[str], None]) -> None:
    """Start the tasks' model while the conversation goes on, so the first
    task finds it loaded: llama.cpp loads it at each server start, and
    downloads it on a first run.  A failure is said in the chat: the tasks
    would fail on it too."""
    start = getattr(worker, "start", None)
    if start is None:  # a model with nothing to load
        return
    started = time.monotonic()
    try:
        await start()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.warning("Background model did not start: %s", exc)
        notice(f"The background tasks' model did not start: {exc}")
        return
    logger.info("Background model ready in %.1f s", time.monotonic() - started)


def _model_label(provider: Any) -> str:
    """A model as the session details name it: a GGUF file by its name."""
    model = str(getattr(provider, "model_name", "") or "")
    return Path(model).name if model.endswith(".gguf") else model or "another model"


def _classifier_unavailable(policy: str, settings: dict, ai_provider: Any) -> str | None:
    """Why *policy*'s classifier cannot run in this session, or None."""
    feature = SPEAK_POLICY_FEATURES.get(policy)
    reason = unavailable_reason(feature) if feature else None
    if reason is not None:
        return reason
    key = _CLASSIFIER_KEYS.get(policy)
    if key is not None and not str(settings.get(key) or "").strip():
        return "the speaking decision has no API key (Settings → AI → Voice Channel → Agent)."
    if policy == "llm" and not getattr(ai_provider, "supports_response_schema", False):
        return "the conversation model cannot answer the speaking decision's questions."
    return None


def _openai_classifier(settings: dict, _ai_provider: Any) -> Any:
    from roomkit import OpenAIClassifier

    return OpenAIClassifier(settings["openai_api_key"])


def _jev_classifier(settings: dict, _ai_provider: Any) -> Any:
    from roomkit import JevClassifier

    return JevClassifier(settings["typesafe_api_key"])


def _llm_classifier(_settings: dict, ai_provider: Any) -> Any:
    # The session's provider: the classifier leaves it open on close().
    from roomkit import LLMClassifier

    return LLMClassifier(ai_provider)


_CLASSIFIER_BUILDERS: dict[str, Callable[[dict, Any], Any]] = {
    "openai": _openai_classifier,
    "jev": _jev_classifier,
    "llm": _llm_classifier,
}
