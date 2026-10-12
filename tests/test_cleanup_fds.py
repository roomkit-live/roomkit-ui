"""Session cleanup removes the session's stale FDs, not the rest of the app's.

cleanup_stale_fds() removed every FD notifier but the self-pipe when a
session closed: an MCP OAuth callback server or httpx call running in
Settings, a skill install or a model download lost its socket mid-transfer.
"""

import asyncio
from types import SimpleNamespace

from roomkit_ui import cleanup
from roomkit_ui import engine as engine_module
from roomkit_ui.cleanup import cleanup_stale_fds, registered_fds
from roomkit_ui.engine import Engine


class _Notifier:
    def __init__(self):
        self.enabled = True

    def setEnabled(self, enabled):  # noqa: N802 — Qt's name
        self.enabled = enabled


class _Selector:
    pass


def _qasync_like_loop(app_fd, session_fd, self_pipe_fd=3):
    """The two notifier layers qasync keeps, holding one app and one session FD."""
    selector = _Selector()
    selector._fd_to_key = {self_pipe_fd: "pipe", app_fd: "app", session_fd: "session"}
    selector._Selector__read_notifiers = {app_fd: _Notifier(), session_fd: _Notifier()}
    selector._Selector__write_notifiers = {}
    return SimpleNamespace(
        _ssock=SimpleNamespace(fileno=lambda: self_pipe_fd),
        _read_notifiers={self_pipe_fd: _Notifier(), app_fd: _Notifier(), session_fd: _Notifier()},
        _write_notifiers={},
        _selector=selector,
    )


def test_fds_registered_before_the_session_survive_its_cleanup(monkeypatch):
    loop = _qasync_like_loop(app_fd=10, session_fd=11)
    monkeypatch.setattr(cleanup.asyncio, "get_running_loop", lambda: loop)
    selector_notifiers = loop._selector._Selector__read_notifiers
    app_notifier = loop._read_notifiers[10]
    session_notifier = loop._read_notifiers[11]

    cleanup_stale_fds(keep={10})

    assert set(loop._read_notifiers) == {3, 10}  # the self-pipe always stays
    assert app_notifier.enabled
    assert not session_notifier.enabled
    assert set(selector_notifiers) == {10}
    assert set(loop._selector._fd_to_key) == {3, 10}


def test_registered_fds_reads_both_notifier_layers(monkeypatch):
    loop = _qasync_like_loop(app_fd=10, session_fd=11)
    monkeypatch.setattr(cleanup.asyncio, "get_running_loop", lambda: loop)

    assert registered_fds() == frozenset({3, 10, 11})


async def test_a_session_spares_what_was_registered_when_it_started(qapp, monkeypatch):
    calls: list[frozenset] = []
    monkeypatch.setattr(engine_module, "registered_fds", lambda: frozenset({10}))
    monkeypatch.setattr(
        engine_module, "cleanup_stale_fds", lambda **kw: calls.append(frozenset(kw["keep"]))
    )
    eng = Engine()

    async def opened(settings):
        pass

    monkeypatch.setattr(eng, "_start_realtime", opened)
    await eng.start({"conversation_mode": "realtime"})
    await eng.stop()
    await asyncio.sleep(0.15)  # the delayed second pass
    eng._cleanup_monitor_task.cancel()

    assert calls == [frozenset({10}), frozenset({10})]


async def test_previous_cleanup_cannot_remove_a_new_turns_sockets(qapp, monkeypatch):
    calls = []
    fds = {10}
    monkeypatch.setattr(engine_module, "registered_fds", lambda: frozenset(fds))
    monkeypatch.setattr(engine_module, "cleanup_stale_fds", lambda **kw: calls.append(kw["keep"]))
    eng = Engine()

    async def opened(_settings):
        eng._enter_active()

    monkeypatch.setattr(eng, "_start_realtime", opened)
    await eng.start({})
    await eng.stop()
    # Another socket and a complete new turn appear before the delayed pass.
    fds.add(20)
    await eng.start({})
    await eng.stop()
    await asyncio.sleep(0.15)
    eng._cleanup_monitor_task.cancel()
    assert calls == [frozenset({10}), frozenset({10, 20}), frozenset({10, 20})]
