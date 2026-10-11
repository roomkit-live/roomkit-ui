"""Git operations for skill sources: clone, pull, remove.

git runs like any other child process (``cli_exec``): resolved on the
user's PATH, bundle library paths stripped, bounded in time, never
prompting — and isolated from any repository the app's environment points
at.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path

from roomkit_ui import skill_manager
from roomkit_ui.cli_exec import CliResult, ProcessRegistry, resolve_command, run_sync

logger = logging.getLogger(__name__)

_GIT_CLONE_TIMEOUT = 180.0
_GIT_PULL_TIMEOUT = 120.0
# Variables that point git at another repository, index or object store.
_GIT_REDIRECTS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_NAMESPACE",
    "GIT_PREFIX",
)


def _run_git(args: list[str], *, timeout: float, ceiling: Path | None = None) -> CliResult:
    """Run git like any other child process: resolved on the user's PATH,
    with the bundle's library paths stripped (``cli_exec``), bounded in time,
    and never prompting — a credential prompt would wait for the timeout.

    *ceiling* stops git from looking above that directory for a repository,
    so ``-C`` on a folder that is not a clone fails instead of acting on an
    enclosing one (a home directory kept in git, say).

    Git's repository-redirecting variables are dropped: an app started from
    a git hook or a terminal inside ``git rebase --exec`` inherits GIT_DIR,
    and every skill clone or pull would act on that repository instead.
    """
    git = resolve_command("git")
    if git is None:
        raise RuntimeError("git is not installed or not on PATH")
    env: dict[str, str | None] = dict.fromkeys(_GIT_REDIRECTS)
    env["GIT_TERMINAL_PROMPT"] = "0"
    if ceiling is not None:
        env["GIT_CEILING_DIRECTORIES"] = str(ceiling)
    return run_sync([*git, *args], timeout=timeout, registry=ProcessRegistry(), extra_env=env)


def _git_error(action: str, result: CliResult) -> RuntimeError:
    if result.timed_out:
        return RuntimeError(f"git {action} timed out")
    detail = result.stderr.strip().splitlines()[-1:] or [f"exit code {result.exit_code}"]
    return RuntimeError(f"git {action} failed: {detail[0]}")


async def clone_repo(url: str) -> Path:
    """Shallow-clone a git repo into the repos directory. Returns the clone path.

    Clones next to the destination and swaps it in only once the clone
    succeeded: a network error must not cost the skills already installed.
    """
    import asyncio

    # Through the module, not names bound at import: the skills root is one
    # place, and a test (or a future setting) that moves it moves it here too.
    dest = skill_manager.get_repos_dir() / skill_manager.repo_dir_name(url)
    staging = Path(tempfile.mkdtemp(prefix=".clone-", dir=skill_manager.get_skills_dir()))
    try:
        # "--" ends the options: a URL starting with "-" is a URL, not a flag.
        result = await asyncio.to_thread(
            _run_git,
            ["clone", "--depth", "1", "--", url, str(staging / "repo")],
            timeout=_GIT_CLONE_TIMEOUT,
        )
        if result.exit_code != 0 or result.timed_out:
            raise _git_error("clone", result)
        _swap_in(staging / "repo", dest)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    logger.info("Cloned %s → %s", url, dest)
    return dest


def _swap_in(new: Path, dest: Path) -> None:
    """Replace *dest* with *new*, keeping the old copy until the move succeeded."""
    old = new.with_name("previous")
    if dest.exists():
        dest.rename(old)
    try:
        new.rename(dest)
    except OSError:
        if old.exists():
            old.rename(dest)
        raise


async def pull_repo(repo_path: Path) -> bool:
    """Pull latest changes (fast-forward only). Returns True on success."""
    import asyncio

    if not (repo_path / ".git").exists():
        logger.warning("Pull skipped: %s is not a git clone", repo_path)
        return False
    try:
        result = await asyncio.to_thread(
            _run_git,
            ["-C", str(repo_path), "pull", "--ff-only"],
            timeout=_GIT_PULL_TIMEOUT,
            ceiling=repo_path.parent,
        )
    except RuntimeError:
        logger.warning("Pull failed for %s", repo_path, exc_info=True)
        return False
    ok = result.exit_code == 0 and not result.timed_out
    if ok:
        logger.info("Pulled %s", repo_path)
    else:
        logger.warning("Pull failed for %s: %s", repo_path, _git_error("pull", result))
    return ok


def remove_repo(repo_path: Path) -> None:
    """Remove a cloned repo directory."""
    if repo_path.exists():
        shutil.rmtree(repo_path)
        logger.info("Removed %s", repo_path)
