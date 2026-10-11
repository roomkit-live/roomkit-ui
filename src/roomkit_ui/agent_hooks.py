"""Chat lines for the Voice Channel agent's turn-taking.

A speak policy that keeps the assistant quiet leaves the user facing
silence; the chat says why, in a quiet line.  A policy that failed or missed
its bound lets the assistant speak (roomkit's fallback): said once, since a
broken classifier fails every turn the same way.  The thinker's thoughts go
to the log only: they are the agent's notes, and what it wants to say
reaches the chat when the policy lets it speak.
"""

from __future__ import annotations

import logging
from typing import Any

from roomkit_ui.engine_state import EngineState

logger = logging.getLogger(__name__)

# ClassifierSpeakPolicy's reasons for a silence → what the chat says.
_QUIET_REASONS = {
    "not finished": "you had not finished",
    "postponed": "you put it off for later",
    "asked to keep quiet": "you asked for quiet",
    "not addressed": "it was not spoken to",
    "asked to listen": "listening until spoken to",
}

# Each silence of a room the agent was asked to listen to: said once already.
_SILENT_LISTENING = "listening"

_FALLBACK = "fallback"  # roomkit's reason when the policy failed or timed out
FALLBACK_NOTICE = (
    "Could not decide whether to speak (the speaking decision failed or took too "
    "long) — the assistant answers every turn it cannot decide."
)


def speak_decision_notice(decision: Any, *, asked_again: bool = False) -> str | None:
    """The chat line for one decision, or None when it needs none."""
    if decision.mode != "silent" or asked_again or decision.reason == _SILENT_LISTENING:
        # A decision taken again after a thought repeats one already shown.
        return None
    why = _QUIET_REASONS.get(decision.reason, decision.reason or "no reason given")
    return f"Stayed quiet — {why}."


def register_agent_hooks(kit: Any, engine: Any) -> None:
    """Say in the chat what the speak policy decided, when it stays quiet;
    log what the thinker thinks."""
    from roomkit.models.enums import HookExecution, HookTrigger

    fallback_told = False

    @kit.hook(HookTrigger.ON_SPEAK_DECISION, HookExecution.ASYNC)
    async def _on_speak_decision(event, context):
        nonlocal fallback_told
        decision = event.decision
        logger.info(
            "Speak decision: %s (%s, %d ms%s)",
            decision.mode,
            decision.reason,
            event.duration_ms,
            ", asked again" if event.asked_again else "",
        )
        if engine._state != EngineState.ACTIVE:
            return
        notice = speak_decision_notice(decision, asked_again=event.asked_again)
        if decision.reason == _FALLBACK and not fallback_told:
            fallback_told = True
            notice = FALLBACK_NOTICE
        if notice is None:
            return
        try:
            engine.session_notice.emit(notice)
        except Exception:
            pass

    @kit.hook(HookTrigger.ON_THOUGHT, HookExecution.ASYNC)
    async def _on_thought(event, context):
        thought = event.thought
        took = f"{event.duration_ms} ms" if event.duration_ms is not None else "emptied"
        logger.info(
            "Thought (%s): %s | wants to say: %s", took, thought.text, list(thought.want_to_say)
        )
