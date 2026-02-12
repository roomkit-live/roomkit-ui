"""Event-loop cleanup for qasync state leaked by MCP/anyio."""

from __future__ import annotations

import asyncio
import logging
import os
import resource

logger = logging.getLogger(__name__)


def cleanup_stale_fds() -> None:
    """Purge all qasync event-loop state that MCP/anyio may have leaked.

    qasync has TWO notifier layers that can hold stale FDs:
    1. _QEventLoop._read_notifiers / _write_notifiers  (from _add_reader)
    2. _Selector.__read_notifiers / __write_notifiers   (from register)
    Layer 2 is especially dangerous because its notifier callbacks do NOT
    disable the notifier before invoking the callback, causing a tight
    busy-loop if the FD is always-ready.

    We also purge cancelled timer callbacks and stale asyncio handles.
    """
    loop = asyncio.get_event_loop()
    self_pipe_fd = getattr(getattr(loop, "_ssock", None), "fileno", lambda: -1)()

    removed = 0

    # --- Layer 1: _QEventLoop notifiers (_add_reader / _add_writer) ---
    for attr in ("_read_notifiers", "_write_notifiers"):
        notifiers: dict | None = getattr(loop, attr, None)
        if not notifiers:
            continue
        for fd in list(notifiers):
            if fd == self_pipe_fd:
                continue
            try:
                target = os.readlink(f"/proc/self/fd/{fd}")
            except OSError:
                target = "?"
            logger.warning("cleanup L1: removing %s FD %d → %s", attr, fd, target)
            notifier = notifiers.pop(fd, None)
            if notifier is not None:
                notifier.setEnabled(False)
            removed += 1

    # --- Layer 2: _Selector notifiers (register / unregister) ---------
    selector = getattr(loop, "_selector", None)
    if selector is not None:
        fd_to_key: dict = getattr(selector, "_fd_to_key", {})
        for mangled in (
            "_Selector__read_notifiers",
            "_Selector__write_notifiers",
        ):
            sel_notifiers: dict | None = getattr(selector, mangled, None)
            if not sel_notifiers:
                continue
            for fd in list(sel_notifiers):
                if fd == self_pipe_fd:
                    continue
                logger.warning("cleanup L2: removing %s FD %d", mangled, fd)
                notifier = sel_notifiers.pop(fd, None)
                if notifier is not None:
                    notifier.setEnabled(False)
                removed += 1
        # Clean corresponding selector keys (skip self-pipe)
        for fd in list(fd_to_key):
            if fd == self_pipe_fd:
                continue
            logger.warning("cleanup L2: removing selector key FD %d", fd)
            del fd_to_key[fd]
            removed += 1

    # --- Layer 3: orphaned timer callbacks in _SimpleTimer -------------
    # After MCP/anyio cleanup, two non-cancelled callbacks can get stuck
    # in an infinite 0 ms timer loop:
    #   - CancelScope._deliver_cancellation()  (anyio cancel retry)
    #   - Task.task_wakeup()  (waking an orphaned task)
    # We kill cancelled timers AND these orphaned active ones.
    timer = getattr(loop, "_timer", None)
    if timer is not None:
        cbs: dict = getattr(timer, "_SimpleTimer__callbacks", {})
        live_tasks = asyncio.all_tasks(loop)
        kill_tids: list[int] = []
        for tid, handle in list(cbs.items()):
            if getattr(handle, "_cancelled", False):
                kill_tids.append(tid)
                continue
            # Inspect the callback to detect orphaned anyio/task handles
            cb = getattr(handle, "_callback", None)
            cb_self = getattr(cb, "__self__", None)
            if cb_self is None:
                continue
            # anyio CancelScope stuck in a cancel-delivery retry loop
            if type(cb_self).__name__ == "CancelScope":
                logger.warning(
                    "cleanup L3: killing orphaned CancelScope timer %s",
                    tid,
                )
                handle.cancel()
                kill_tids.append(tid)
                continue
            # Task.task_wakeup for a task no longer tracked by asyncio
            if isinstance(cb_self, asyncio.Task) and cb_self not in live_tasks:
                logger.warning(
                    "cleanup L3: killing orphaned task timer %s → %s",
                    tid,
                    cb_self,
                )
                handle.cancel()
                kill_tids.append(tid)
        for tid in kill_tids:
            timer.killTimer(tid)
            del cbs[tid]
            removed += 1
        if kill_tids:
            logger.info("cleanup L3: killed %d timers", len(kill_tids))

    # --- Layer 4: purge cancelled handles from asyncio _ready queue ---
    ready = getattr(loop, "_ready", None)
    if ready is not None:
        before = len(ready)
        active = [h for h in ready if not h._cancelled]
        ready.clear()
        ready.extend(active)
        dropped = before - len(active)
        if dropped:
            logger.info("cleanup L4: dropped %d cancelled handles", dropped)
            removed += dropped

    # --- Summary -----------------------------------------------------
    r_count = len(getattr(loop, "_read_notifiers", {}) or {})
    w_count = len(getattr(loop, "_write_notifiers", {}) or {})
    tasks = [t for t in asyncio.all_tasks(loop) if not t.done()]
    logger.info(
        "cleanup: removed %d items, %d read + %d write notifiers remain "
        "(self-pipe=%d), %d live tasks",
        removed,
        r_count,
        w_count,
        self_pipe_fd,
        len(tasks),
    )
    for t in tasks:
        logger.info("cleanup: live task: %s", t)


async def post_cleanup_monitor() -> None:
    """Log CPU usage after cleanup to verify the fix worked."""
    loop = asyncio.get_event_loop()
    t0 = resource.getrusage(resource.RUSAGE_SELF)
    for i in range(3):
        await asyncio.sleep(3)
        t1 = resource.getrusage(resource.RUSAGE_SELF)
        cpu = (t1.ru_utime - t0.ru_utime) + (t1.ru_stime - t0.ru_stime)
        logger.info(
            "cpu-monitor[%d]: %.2fs CPU in 3s",
            i,
            cpu,
        )
        if cpu > 1.0:
            # Dump everything that could be spinning
            timer = getattr(loop, "_timer", None)
            if timer is not None:
                cbs = getattr(timer, "_SimpleTimer__callbacks", {})
                logger.warning("cpu-monitor: %d timer callbacks", len(cbs))
                for tid_k, handle in list(cbs.items())[:5]:
                    logger.warning(
                        "  timer %s → %s (cancelled=%s)", tid_k, handle, handle._cancelled
                    )

            ready = getattr(loop, "_ready", None)
            if ready is not None:
                logger.warning("cpu-monitor: %d _ready items", len(ready))
                for h in list(ready)[:5]:
                    logger.warning("  ready → %s (cancelled=%s)", h, h._cancelled)

            # Layer 1 notifiers
            for attr in ("_read_notifiers", "_write_notifiers"):
                notifiers = getattr(loop, attr, {})
                for fd, notifier in list(notifiers.items()):
                    logger.warning(
                        "  L1 %s FD %d enabled=%s",
                        attr,
                        fd,
                        notifier.isEnabled(),
                    )

            # Layer 2 notifiers (Selector)
            selector = getattr(loop, "_selector", None)
            if selector:
                for mangled in ("_Selector__read_notifiers", "_Selector__write_notifiers"):
                    sel_n = getattr(selector, mangled, {})
                    for fd, notifier in list(sel_n.items()):
                        logger.warning(
                            "  L2 %s FD %d enabled=%s",
                            mangled,
                            fd,
                            notifier.isEnabled(),
                        )
                fd_to_key = getattr(selector, "_fd_to_key", {})
                if fd_to_key:
                    logger.warning("  L2 _fd_to_key: %s", list(fd_to_key.keys()))

            tasks = [t for t in asyncio.all_tasks(loop) if not t.done()]
            logger.warning("cpu-monitor: %d live tasks", len(tasks))
            for t in tasks:
                logger.warning("  task: %s", t)
        t0 = t1
