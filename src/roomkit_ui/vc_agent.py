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
on, and its result comes back as a turn the agent speaks.

Both are add-ons: one that cannot run is left out of the session. Speaking
policy problems go to session details and logs; other add-ons explain their
absence in the chat.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
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

# The settings key holding each classifier's API key.
_CLASSIFIER_KEYS = {"openai": "openai_api_key", "jev": "typesafe_api_key"}


@dataclass
class VCAgent:
    """What a session's AIChannel is given beyond its model, and what to close."""

    speak_policy: Any = None
    thinker: Any = None
    # Set up on the kit, not given to the channel (kit.setup_background).
    background: bool = False
    summary: list[dict] = field(default_factory=list)
    decision: SessionModel | None = None
    _closables: list[Any] = field(default_factory=list)

    def channel_options(self) -> dict[str, Any]:
        """``AIChannel`` keyword arguments; empty when nothing is enabled."""
        options = {"speak_policy": self.speak_policy, "thinker": self.thinker}
        return {name: part for name, part in options.items() if part is not None}

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

    from roomkit import ClassifierSpeakPolicy

    classifier = _CLASSIFIER_BUILDERS[policy](settings, ai_provider)
    agent._closables.append(classifier)
    agent.speak_policy = ClassifierSpeakPolicy(classifier, agent_name=agent_name(settings))
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
    agent.summary.append(
        {"name": "Works in the background", "description": "long requests run as tasks"}
    )


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
