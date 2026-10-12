"""Cleaning qasync leftovers must preserve live anyio deadlines/cancellation."""

import asyncio
from types import SimpleNamespace

import anyio

from roomkit_ui import cleanup


class Timer:
    def __init__(self, *handles):
        self._SimpleTimer__callbacks = dict(enumerate(handles))
        self.killed = []

    def killTimer(self, tid):  # noqa: N802
        self.killed.append(tid)


def clean_timer(monkeypatch, timer):
    loop = asyncio.get_running_loop()
    tasks = asyncio.all_tasks(loop)
    fake = SimpleNamespace(_timer=timer)
    with monkeypatch.context() as patch:
        patch.setattr(cleanup.asyncio, "get_running_loop", lambda: fake)
        patch.setattr(cleanup.asyncio, "all_tasks", lambda _: tasks)
        cleanup.cleanup_stale_fds(timers_only=True)
    return loop


async def test_live_request_deadline_still_fires_after_cleanup(monkeypatch):
    with anyio.move_on_after(0.02) as scope:
        handle = scope._timeout_handle
        timer = Timer(handle)
        clean_timer(monkeypatch, timer)
        assert not handle.cancelled() and timer.killed == []
        await asyncio.sleep(0.1)
    assert scope.cancelled_caught


async def test_live_cancellation_retry_is_preserved(monkeypatch):
    with anyio.CancelScope() as scope:
        handle = asyncio.Handle(scope._deliver_cancellation, (scope,), asyncio.get_running_loop())
        timer = Timer(handle)
        clean_timer(monkeypatch, timer)
        assert not handle.cancelled() and timer.killed == []


async def test_only_retired_retry_without_living_tasks_is_removed(monkeypatch):
    holder = []

    async def finished():
        with anyio.CancelScope() as scope:
            holder.append(scope)

    await asyncio.create_task(finished())
    scope = holder[0]
    loop = asyncio.get_running_loop()
    handle = asyncio.Handle(scope._deliver_cancellation, (scope,), loop)
    cancelled = asyncio.Handle(lambda: None, (), loop)
    cancelled.cancel()
    timer = Timer(handle, cancelled)
    clean_timer(monkeypatch, timer)
    assert handle.cancelled() and timer.killed == [0, 1]
