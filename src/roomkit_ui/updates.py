"""Is a newer RoomKit UI out, and how does this install take it?

The check reads one public endpoint: PyPI's JSON for a Python install (what
pip, pipx and uv install), the latest GitHub release for a built app (what the
releases page and the Homebrew cask carry).  Only a final release counts
(X.Y.Z): a pre-release is never offered.

The update follows how the app was installed (``install_env``): the app runs
it in a Python environment it may change (uv tool, pipx, pip); a source
checkout gets the command; a built app gets the release page, and the
Homebrew command when the cask installed it.  On Windows the user runs the
command once the app has quit: Windows keeps the running program's files
locked.  Components survive: a uv tool update goes through the receipt with
every extra the environment carries.

Pure (no Qt): ``update_check`` schedules the check and runs the plan.
"""

from __future__ import annotations

import importlib.metadata
import re
import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from roomkit_ui.components import Installer, InstallPlan, installer_argv, shown_command, uv_path
from roomkit_ui.env_extras import installed_extras, kept_extras
from roomkit_ui.features import DISTRIBUTION
from roomkit_ui.install_env import (
    InstallKind,
    editable_checkout,
    install_kind,
    uv_tool_install_argv,
    uv_tool_receipt,
)

PYPI_URL = f"https://pypi.org/pypi/{DISTRIBUTION}/json"
GITHUB_LATEST_URL = "https://api.github.com/repos/roomkit-live/roomkit-ui/releases/latest"
RELEASES_URL = "https://github.com/roomkit-live/roomkit-ui/releases"
TIMEOUT = 10.0  # seconds, for each step: connecting, sending, reading

# The kinds whose update is the built app the releases page carries.
_BUILT = frozenset({InstallKind.FROZEN, InstallKind.HOMEBREW})

_RELEASE = re.compile(r"v?(\d+)\.(\d+)(?:\.(\d+))?")
_PRE_RELEASE = re.compile(r"[-_.]?(a|b|c|rc|alpha|beta|pre|preview|dev)\d*", re.IGNORECASE)
_WINDOWS_NOTE = (
    "Quit RoomKit UI first, then run it in PowerShell: Windows keeps the app's files "
    "locked while it runs."
)


def current_version() -> str:
    """The app's version as installed, read from its metadata ("" without):
    after an update, the new one."""
    try:
        return importlib.metadata.version(DISTRIBUTION)
    except importlib.metadata.PackageNotFoundError:
        return ""


def final_version(text: str) -> tuple[int, int, int] | None:
    """X.Y.Z (or X.Y) as numbers; None for anything else: a pre-release, a
    development or local build."""
    match = _RELEASE.fullmatch(text.strip())
    if match is None:
        return None
    return int(match[1]), int(match[2]), int(match[3] or 0)


def is_newer(candidate: str, current: str) -> bool:
    """Whether *candidate*, a final release, is newer than *current*.

    A running pre-release (0.4.0rc1) is older than its final release.
    Nothing is newer than a version that cannot be read.
    """
    new = final_version(candidate)
    match = _RELEASE.match(current.strip())
    if new is None or match is None:
        return False
    now = (int(match[1]), int(match[2]), int(match[3] or 0))
    if new != now:
        return new > now
    return bool(_PRE_RELEASE.match(current.strip()[match.end() :]))


def release_notes_url(version: str) -> str:
    return f"{RELEASES_URL}/tag/v{version}"


def _latest_on_pypi(data: Any) -> str | None:
    info = data.get("info") if isinstance(data, dict) else None
    if not isinstance(info, dict) or info.get("yanked"):
        return None
    version = str(info.get("version") or "")
    return version if final_version(version) else None


def _latest_on_github(data: Any) -> str | None:
    if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
        return None
    version = str(data.get("tag_name") or "").removeprefix("v")
    return version if final_version(version) else None


@dataclass(frozen=True)
class LatestRelease:
    """What one check found."""

    version: str | None  # the latest final release; None when none could be read
    etag: str = ""  # for the next check's If-None-Match
    unchanged: bool = False  # 304: the release the last check found still is the latest


async def fetch_latest(
    kind: InstallKind, etag: str = "", *, transport: httpx.AsyncBaseTransport | None = None
) -> LatestRelease:
    """The latest release this install takes.  Raises httpx's errors (offline,
    a timeout, a server error): the caller stays quiet about them."""
    url, read = (
        (GITHUB_LATEST_URL, _latest_on_github) if kind in _BUILT else (PYPI_URL, _latest_on_pypi)
    )
    headers = {"User-Agent": f"{DISTRIBUTION}/{current_version() or 'dev'}"}
    if etag:
        headers["If-None-Match"] = etag
    async with httpx.AsyncClient(timeout=TIMEOUT, transport=transport) as client:
        response = await client.get(url, headers=headers)
    if response.status_code == 304:
        return LatestRelease(None, etag, unchanged=True)
    response.raise_for_status()
    try:
        data = response.json()
    except ValueError:
        return LatestRelease(None)
    return LatestRelease(read(data), response.headers.get("etag", ""))


def update_plan(kind: InstallKind | None = None) -> InstallPlan:
    """How this install takes the latest release."""
    kind = kind or install_kind()
    plan = _PLANS[kind]()
    if sys.platform == "win32" and plan.how is Installer.APP:
        # The user's shell lacks what the app would have set (UV_TOOL_DIR):
        # without it, uv would update another environment than this one.
        command = shown_command(plan.argv, plan.env)
        return InstallPlan(Installer.COMMAND, command=command, note=_WINDOWS_NOTE)
    return plan


def _frozen_plan() -> InstallPlan:
    return InstallPlan(Installer.NONE, note="Download the new version from the release page.")


def _homebrew_plan() -> InstallPlan:
    return InstallPlan(
        Installer.COMMAND,
        command=f"brew upgrade --cask {DISTRIBUTION}",
        note="Installed with Homebrew: run it in a terminal. It quits RoomKit UI first.",
    )


def _checkout_plan() -> InstallPlan:
    return InstallPlan(
        Installer.COMMAND,
        command="git pull && uv sync --inexact",
        note=f"A source checkout: run it in {editable_checkout()}.",
    )


def _uv_tool_plan() -> InstallPlan:
    """``uv tool upgrade`` when the receipt records every component installed;
    else ``uv tool install --upgrade`` with them all, so none is lost.  A
    receipt the app cannot rebuild (a git source, constraints) is upgraded as
    it stands."""
    receipt = uv_tool_receipt()
    if receipt is None:  # gone since the kind was read
        return _pip_plan()
    uv = uv_path()
    extras = kept_extras(receipt.extras) if receipt.rebuildable else receipt.extras
    if extras != receipt.extras:
        argv = uv_tool_install_argv(uv or "uv", receipt, extras, upgrade=True)
    else:
        argv = (uv or "uv", "tool", "upgrade", DISTRIBUTION)
    return _app_runs(argv, uv is not None, receipt.environment())


def _pipx_plan() -> InstallPlan:
    """pipx keeps what the app added with pip through an upgrade."""
    from roomkit_ui.cli_exec import search_path

    pipx = shutil.which("pipx", path=search_path())
    env: tuple[tuple[str, str], ...] = ()
    venvs = Path(sys.prefix).parent
    if (
        venvs.name == "venvs"
    ):  # <PIPX_HOME>/venvs/roomkit-ui: this very one, whatever PIPX_HOME says
        env = (("PIPX_HOME", str(venvs.parent)),)
    return _app_runs((pipx or "pipx", "upgrade", DISTRIBUTION), pipx is not None, env)


def _pip_plan() -> InstallPlan:
    extras = installed_extras()
    spec = DISTRIBUTION + (f"[{','.join(extras)}]" if extras else "")
    argv = installer_argv(spec, upgrade=True)
    if argv is None:
        return InstallPlan(
            Installer.COMMAND, command=shown_command(("pip", "install", "-U", spec))
        )
    return _app_runs(argv, True)


def _app_runs(
    argv: tuple[str, ...], found: bool, env: tuple[tuple[str, str], ...] = ()
) -> InstallPlan:
    """The app runs *argv*; the user does when its program was not *found*."""
    if not found:
        return InstallPlan(Installer.COMMAND, command=shown_command(argv))
    return InstallPlan(Installer.APP, argv=argv, command=shown_command(argv), env=env)


_PLANS: dict[InstallKind, Callable[[], InstallPlan]] = {
    InstallKind.FROZEN: _frozen_plan,
    InstallKind.HOMEBREW: _homebrew_plan,
    InstallKind.CHECKOUT: _checkout_plan,
    InstallKind.UV_TOOL: _uv_tool_plan,
    InstallKind.PIPX: _pipx_plan,
    InstallKind.PIP: _pip_plan,
}
