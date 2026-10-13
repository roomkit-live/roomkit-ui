"""Log turn-taking diagnostics; show only background-task progress in the chat.

Speaking decisions and thoughts are internal diagnostics. Background work
still announces when it starts and ends, and updates the engine's task count
so idle hang-up can wait for it.
"""

from __future__ import annotations

import logging
from typing import Any

from roomkit_ui.engine_state import EngineState

logger = logging.getLogger(__name__)

_TASK_LABEL_MAX = 120


def _task_label(meta: dict) -> str:
    """What a task was asked, on one line and shortened."""
    task = " ".join(str(meta.get("task_input") or "").split())
    if len(task) > _TASK_LABEL_MAX:
        task = task[: _TASK_LABEL_MAX - 1] + "…"
    return task


def task_started_notice(event: Any) -> str:
    """The chat line for a task the agent started: what it was asked."""
    task = _task_label(getattr(event, "metadata", None) or {})
    return f"Working in the background: {task}" if task else "Working in the background."


def task_ended_notice(event: Any) -> str:
    """The chat line for a task that ended.  A failure's error stays in the
    log: it is the framework's, not words for the user."""
    meta = getattr(event, "metadata", None) or {}
    status = str(meta.get("task_status") or "")
    if status == "completed":
        took = meta.get("duration_ms")
        return (
            f"Background work done in {round(took / 1000)} s." if took else "Background work done."
        )
    if status == "cancelled":
        return "Background work cancelled."
    return "Background work failed."


def register_agent_hooks(kit: Any, engine: Any) -> None:
    """Log policy decisions and thoughts; report background-task progress."""
    _register_speaking_hooks(kit)
    _register_task_hooks(kit, engine)


def _register_speaking_hooks(kit: Any) -> None:
    from roomkit.models.enums import HookExecution, HookTrigger

    @kit.hook(HookTrigger.ON_SPEAK_DECISION, HookExecution.ASYNC)
    async def _on_speak_decision(event, context):
        decision = event.decision
        log = logger.warning if decision.reason == "fallback" else logger.info
        log(
            "Speak decision: %s (%s, %d ms%s)",
            decision.mode,
            decision.reason,
            event.duration_ms,
            ", asked again" if event.asked_again else "",
        )

    @kit.hook(HookTrigger.ON_THOUGHT, HookExecution.ASYNC)
    async def _on_thought(event, context):
        thought = event.thought
        took = f"{event.duration_ms} ms" if event.duration_ms is not None else "emptied"
        logger.info(
            "Thought (%s): %s | wants to say: %s", took, thought.text, list(thought.want_to_say)
        )


def _register_task_hooks(kit: Any, engine: Any) -> None:
    from roomkit.models.enums import HookExecution, HookTrigger

    @kit.hook(HookTrigger.ON_TASK_DELEGATED, HookExecution.ASYNC)
    async def _on_task_started(event, context):
        engine._background_tasks += 1
        meta = event.metadata or {}
        # agent_id: the channel doing it, "background" on a model of its own.
        logger.info(
            "Background task %s started on %s: %s",
            meta.get("task_id"),
            meta.get("agent_id"),
            _task_label(meta),
        )
        _notify(engine, task_started_notice(event))

    @kit.hook(HookTrigger.ON_TASK_COMPLETED, HookExecution.ASYNC)
    async def _on_task_ended(event, context):
        engine._background_tasks = max(0, engine._background_tasks - 1)
        meta = event.metadata or {}
        if meta.get("error"):
            logger.warning("Background task %s failed: %s", meta.get("task_id"), meta["error"])
        else:
            logger.info(
                "Background task %s %s in %.1f s",
                meta.get("task_id"),
                meta.get("task_status"),
                (meta.get("duration_ms") or 0) / 1000,
            )
        _notify(engine, task_ended_notice(event))


def _notify(engine: Any, notice: str) -> None:
    if engine._state != EngineState.ACTIVE:
        return
    try:
        engine.session_notice.emit(notice)
    except Exception:
        pass
