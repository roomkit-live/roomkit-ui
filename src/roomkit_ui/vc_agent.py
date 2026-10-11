"""The Voice Channel agent's turn-taking: whether it speaks on a turn.

roomkit 0.96 gives an AIChannel a speak policy: on each turn it would answer,
the policy says speak, offer (one short sentence of what it could add) or
stay silent.  ``ClassifierSpeakPolicy`` decides on narrow questions a
classifier answers in one call (has the speaker finished, put it off, asked
for quiet, addressed the agent).  This module builds it from the settings.

The policy is an add-on: one that cannot run (backend not installed, no key,
a model that cannot answer under a schema) leaves the session answering
every turn, and the chat says why.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from roomkit_ui.features import SPEAK_POLICY_FEATURES, unavailable_reason

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
    summary: list[dict] = field(default_factory=list)
    _closables: list[Any] = field(default_factory=list)

    def channel_options(self) -> dict[str, Any]:
        """``AIChannel`` keyword arguments; empty when nothing is enabled."""
        if self.speak_policy is None:
            return {}
        return {"speak_policy": self.speak_policy}

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


def build_vc_agent(settings: dict, ai_provider: Any, notice: Callable[[str], None]) -> VCAgent:
    """The session's agent parts from the settings; *notice* tells the chat
    what was left out and why."""
    agent = VCAgent()
    policy = settings.get("vc_speak_policy", "off")
    if policy not in _CLASSIFIER_BUILDERS:
        return agent
    reason = _classifier_unavailable(policy, settings, ai_provider)
    if reason is not None:
        notice(f"The assistant answers every turn: {reason}")
        return agent

    from roomkit import ClassifierSpeakPolicy

    classifier = _CLASSIFIER_BUILDERS[policy](settings, ai_provider)
    agent._closables.append(classifier)
    agent.speak_policy = ClassifierSpeakPolicy(classifier, agent_name=agent_name(settings))
    agent.summary.append(
        {
            "name": "Decides when to speak",
            "description": f"{_CLASSIFIER_NAMES[policy]}, as {agent_name(settings)}",
        }
    )
    return agent


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
