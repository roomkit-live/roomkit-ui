"""Child-process primitives for CLI tools.

Leaf module: both ``cli_help`` (``--help`` probing) and ``cli_tools`` (the
manager) need to spawn binaries, so the machinery cannot live in either.

Uses blocking ``subprocess`` on a worker thread rather than
``asyncio.create_subprocess_exec`` — the app runs on qasync, and every other
child-process path here does the same (``skill_manager.clone_repo``,
``engine_tools._paste_text``).
"""

from __future__ import annotations

import logging
import os
import shlex
import shutil
import subprocess  # nosec B404 — argv lists only, never shell=True
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# A macOS .app launched from Finder inherits only /usr/bin:/bin:/usr/sbin:/sbin,
# so user-installed CLIs are invisible unless we look here explicitly.
_EXTRA_PATH_DIRS = ("~/.local/bin", "/usr/local/bin", "/opt/homebrew/bin", "~/bin")

# PyInstaller's bootloader repoints these at _MEIPASS and stashes the real
# values in *_ORIG. A child inheriting them loads our bundled libs instead of
# its own and dies in confusing ways.
_PYI_LIBRARY_VARS = ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH", "DYLD_FRAMEWORK_PATH")

# How long to wait, after a kill, for the output pipes to close — and for
# taskkill to finish. A grandchild the kill missed can hold them open forever.
_DRAIN_TIMEOUT = 2.0


@dataclass(frozen=True)
class CliResult:
    """Outcome of one child process run."""

    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False


def search_path() -> str:
    """Return PATH augmented with the usual user-install locations."""
    parts = [p for p in os.environ.get("PATH", "").split(os.pathsep) if p]
    for extra in _EXTRA_PATH_DIRS:
        resolved = str(Path(extra).expanduser())
        if resolved not in parts and Path(resolved).is_dir():
            parts.append(resolved)
    return os.pathsep.join(parts)


def child_env() -> dict[str, str]:
    """Return an environment safe to hand a child process."""
    env = dict(os.environ)
    for var in _PYI_LIBRARY_VARS:
        original = env.pop(f"{var}_ORIG", None)
        if original is not None:
            env[var] = original
        elif getattr(sys, "frozen", False):
            env.pop(var, None)
    env.pop("_MEIPASS2", None)
    env["PATH"] = search_path()
    return env


def resolve_command(command: str) -> list[str] | None:
    """Split *command* and resolve its binary to an absolute path.

    ``shlex`` so quoted paths survive, and so ``uv run <cli>`` works as a
    prefix — same convention as ``mcp_manager._parse_stdio_config``.
    Returns None when the binary cannot be found.
    """
    parts = shlex.split(command or "")
    if not parts:
        return None
    binary = shutil.which(parts[0], path=search_path())
    if binary is None:
        return None
    return [binary, *parts[1:]]


def run_sync(
    argv: list[str],
    *,
    timeout: float,
    registry: ProcessRegistry,
    extra_env: Mapping[str, str | None] | None = None,
) -> CliResult:
    """Run *argv* to completion. Blocking — call via ``asyncio.to_thread``.

    *extra_env* is layered over :func:`child_env`; a ``None`` value removes
    that variable from the child's environment.

    stdin is closed so a CLI that prompts fails fast instead of hanging until
    the timeout. ``start_new_session`` puts the child in its own process group
    so we can kill grandchildren too (``uv run <cli>`` spawns one).

    Output is decoded as UTF-8 with replacement: one stray byte must not turn
    a result — or a ``--help`` probe at session start — into an exception.
    """
    env = child_env()
    for key, value in (extra_env or {}).items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    try:
        proc = subprocess.Popen(  # nosec B603 — argv list, never shell=True
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            encoding="utf-8",
            errors="replace",
            env=env,
            start_new_session=True,
        )
    except OSError as exc:
        return CliResult(exit_code=-1, stdout="", stderr=f"Failed to launch: {exc}")

    registry.add(proc)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        return CliResult(exit_code=proc.returncode, stdout=stdout, stderr=stderr)
    except subprocess.TimeoutExpired:
        _kill(proc)
        stdout, stderr = _drain(proc)
        return CliResult(
            exit_code=proc.returncode if proc.returncode is not None else -1,
            stdout=stdout,
            stderr=stderr,
            timed_out=True,
        )
    finally:
        registry.discard(proc)


def _drain(proc: subprocess.Popen) -> tuple[str, str]:
    """Collect what a killed child wrote, without waiting on its grandchildren.

    A grandchild the kill missed — one that left our process group, a node.exe
    behind a Windows ``.cmd`` shim if ``taskkill`` failed — still holds the
    output pipes, and reading them to EOF would wait for it to exit. Past
    ``_DRAIN_TIMEOUT`` the partial output is dropped and the pipes closed.
    """
    try:
        return proc.communicate(timeout=_DRAIN_TIMEOUT)
    except subprocess.TimeoutExpired:
        logger.warning("pid %s: a child process still holds its output open", proc.pid)
    for pipe in (proc.stdout, proc.stderr):
        try:
            if pipe is not None:
                pipe.close()
        except OSError:
            pass
    try:
        proc.wait(timeout=_DRAIN_TIMEOUT)
    except subprocess.TimeoutExpired:
        pass
    return "", ""


def truncate(text: str, limit: int) -> str:
    """Clip *text* to *limit* chars, saying so rather than lying by omission."""
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n… [truncated, {len(text)} chars total]"


def _kill(proc: subprocess.Popen) -> None:
    """Kill *proc* and the processes it started.

    POSIX: the process group ``start_new_session`` created. Windows has no
    group to signal (``start_new_session`` is ignored there), so the tree is
    killed with ``taskkill /T`` — otherwise an npm ``.cmd`` shim's node.exe
    or ``uv run``'s CLI outlives the kill and keeps the output pipes open.
    """
    if sys.platform == "win32":
        _kill_windows_tree(proc.pid)
    elif hasattr(os, "killpg"):
        try:
            os.killpg(os.getpgid(proc.pid), 9)
            return
        except (ProcessLookupError, PermissionError, OSError):
            pass
    try:
        proc.kill()
    except OSError:
        logger.debug("Could not kill pid %s", proc.pid, exc_info=True)


def _kill_windows_tree(pid: int) -> None:
    """``taskkill /T /F`` *pid* and its descendants. Run before killing *pid*
    itself: the tree is found through parent ids."""
    system_root = os.environ.get("SYSTEMROOT", r"C:\Windows")
    taskkill = os.path.join(system_root, "System32", "taskkill.exe")
    try:
        subprocess.run(  # nosec B603 — fixed argv, never shell=True
            [taskkill, "/T", "/F", "/PID", str(pid)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=_DRAIN_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        logger.debug("taskkill failed for pid %s", pid, exc_info=True)


class ProcessRegistry:
    """Live child processes, so a session teardown can kill them.

    Needed because ``main_window.closeEvent`` fires ``Engine.stop()`` without
    awaiting it: cancelling the future abandons the worker thread, and the
    child would otherwise outlive the app.
    """

    def __init__(self) -> None:
        self._live: set[subprocess.Popen] = set()

    def add(self, proc: subprocess.Popen) -> None:
        self._live.add(proc)

    def discard(self, proc: subprocess.Popen) -> None:
        self._live.discard(proc)

    def terminate_all(self) -> None:
        for proc in list(self._live):
            if proc.poll() is None:
                _kill(proc)
        self._live.clear()
