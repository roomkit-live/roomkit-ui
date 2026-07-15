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
    extra_env: dict[str, str] | None = None,
) -> CliResult:
    """Run *argv* to completion. Blocking — call via ``asyncio.to_thread``.

    stdin is closed so a CLI that prompts fails fast instead of hanging until
    the timeout. ``start_new_session`` puts the child in its own process group
    so we can kill grandchildren too (``uv run <cli>`` spawns one).
    """
    env = child_env()
    if extra_env:
        env.update(extra_env)
    try:
        proc = subprocess.Popen(  # nosec B603 — argv list, never shell=True
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
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
        stdout, stderr = proc.communicate()
        return CliResult(
            exit_code=proc.returncode,
            stdout=stdout,
            stderr=stderr,
            timed_out=True,
        )
    finally:
        registry.discard(proc)


def truncate(text: str, limit: int) -> str:
    """Clip *text* to *limit* chars, saying so rather than lying by omission."""
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n… [truncated, {len(text)} chars total]"


def _kill(proc: subprocess.Popen) -> None:
    """Kill *proc*, and the process group around it where there is one.

    ``os.killpg``/``os.getpgid`` are POSIX-only and ``start_new_session`` is
    ignored on Windows, so there is no group to signal there: a wrapper like
    ``uv run <cli>`` can leave its own child running. Killing the process we
    spawned is the most that platform offers here.
    """
    if hasattr(os, "killpg"):
        try:
            os.killpg(os.getpgid(proc.pid), 9)
            return
        except (ProcessLookupError, PermissionError, OSError):
            pass
    try:
        proc.kill()
    except OSError:
        logger.debug("Could not kill pid %s", proc.pid, exc_info=True)


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
