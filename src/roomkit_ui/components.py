"""How this install takes a component: an optional backend, one extra of the app.

Settings → Models & components → Components lists them, and a provider marked "not installed" or a
session that could not start offers to install one.  What installing means
depends on how the app itself was installed:

* a frozen build (.app, .exe) carries what it can and cannot be changed, so
  there is nothing to run;
* a source checkout (an editable install) belongs to ``uv sync``, which
  would undo anything pip added: the user gets the command to run there;
* a uv tool environment: the app runs ``uv tool install`` with the extras its
  receipt records plus this one, so ``uv tool upgrade`` keeps it
  (``install_env``);
* any other environment (pip, pipx): the app runs the install, with uv when
  it is on the PATH, else pip, pinned to the running version so the app
  itself never moves.  Only the app's own extras are ever installed.

Pure logic: the runner (``component_installer``) and the pages call in.
"""

from __future__ import annotations

import functools
import importlib.metadata
import importlib.util
import shlex
import shutil
import subprocess  # nosec B404 — list2cmdline only: nothing is run here
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from roomkit_ui.env_extras import kept_extras
from roomkit_ui.features import DISTRIBUTION, EXCLUSIVE_EXTRAS, FEATURES, is_available
from roomkit_ui.install_env import UvToolReceipt, uv_tool_install_argv, uv_tool_receipt, with_extra
from roomkit_ui.install_env import editable_checkout as _editable_checkout

# What a user should know before installing one: its weight.
_NOTES = {
    "mcp-apps": "A large download: Qt WebEngine.",
    "pocket-tts": "A very large download: PyTorch, several GB.",
    "qwen3-tts": "A very large download: PyTorch, several GB.",
    "neutts": "A very large download: PyTorch, several GB.",
    "vui": "A very large download: PyTorch, several GB. Speaks English, on an NVIDIA GPU.",
}

# Components a running app only picks up once restarted: Qt modules it
# probed at start (MCP App views, sounds), and the global hotkeys it set up.
_RESTART = frozenset({"mcp-apps", "camera", "dictation"})


class Installer(StrEnum):
    """Who installs a component in this install."""

    APP = "app"  # the app runs the install
    COMMAND = "command"  # the user runs a command the app gives
    NONE = "none"  # a frozen build: it cannot be changed


@dataclass(frozen=True)
class Component:
    """One extra of the app and the features it brings."""

    extra: str
    features: tuple[str, ...]

    @property
    def title(self) -> str:
        return FEATURES[self.features[0]].label

    @property
    def description(self) -> str:
        """Every feature it brings, for the Components list."""
        return " · ".join(FEATURES[key].label for key in self.features)

    @property
    def note(self) -> str:
        return _NOTES.get(self.extra, "")

    @property
    def needs_restart(self) -> bool:
        return self.extra in _RESTART

    def installed(self) -> bool:
        return all(is_available(key) for key in self.features)


@dataclass(frozen=True)
class InstallPlan:
    """How to install a component here, and what to tell the user first."""

    how: Installer
    argv: tuple[str, ...] = ()  # what the app runs (APP)
    command: str = ""  # what the user runs (COMMAND), or what the app runs, shown
    conflicts: tuple[str, ...] = ()  # installed components it would break
    note: str = ""
    env: tuple[tuple[str, str], ...] = ()  # set for what the app runs (APP)


def components() -> list[Component]:
    """Every extra behind a feature, in the order the features are listed."""
    by_extra: dict[str, list[str]] = {}
    for key, feature in FEATURES.items():
        by_extra.setdefault(feature.extra, []).append(key)
    return [Component(extra, tuple(keys)) for extra, keys in by_extra.items()]


def component_of(feature: str) -> Component:
    """The component that brings *feature* (a key in ``FEATURES``)."""
    extra = FEATURES[feature].extra
    return next(c for c in components() if c.extra == extra)


def _python_refused(component: Component) -> str | None:
    """Why this Python cannot install *component* (vui-tts runs on 3.12 alone)."""
    refused = next(
        (r for key in component.features if (r := FEATURES[key].python_refused()) is not None),
        None,
    )
    return f"It {refused}" if refused is not None else None


def install_plan(component: Component) -> InstallPlan:
    """How this install takes *component*."""
    conflicts = _conflicts(component)
    refused = _python_refused(component)
    if refused is not None:
        return InstallPlan(Installer.NONE, note=refused)
    if getattr(sys, "frozen", False):
        return InstallPlan(
            Installer.NONE,
            note=f"{component.title} is not part of this build: it needs a Python install "
            "of RoomKit UI (see the README).",
        )
    checkout = _checkout()
    if checkout is not None:
        return InstallPlan(
            Installer.COMMAND,
            command=f"uv sync --inexact --extra {component.extra}",
            conflicts=conflicts,
            note=f"A source checkout: run it in {checkout}.",
        )
    receipt = _rebuildable_receipt()
    if receipt is not None:
        return _uv_tool_plan(component, receipt, conflicts)
    spec = _spec(component.extra)
    argv = installer_argv(spec)
    if argv is None:
        return InstallPlan(Installer.COMMAND, command=f"pip install '{spec}'", conflicts=conflicts)
    return InstallPlan(
        Installer.APP,
        argv=argv,
        command=shown_command(argv),
        conflicts=conflicts,
        note=_environment_note(component),
    )


def _rebuildable_receipt() -> UvToolReceipt | None:
    """The receipt a component install goes through, None for ``uv pip``.

    Not on Windows: ``uv tool install`` rewrites roomkit-ui.exe, which Windows
    keeps locked while the app runs, so the install would fail.  There the
    component goes in with ``uv pip`` and the next upgrade leaves it out
    (``_environment_note`` says so).
    """
    if sys.platform == "win32":
        return None
    receipt = uv_tool_receipt()
    return receipt if receipt is not None and receipt.rebuildable else None


def _uv_tool_plan(
    component: Component, receipt: UvToolReceipt, conflicts: tuple[str, ...]
) -> InstallPlan:
    """``uv tool install`` with the receipt's extras and *component*'s: the
    receipt then records it, and ``uv tool upgrade`` keeps it."""
    extras = with_extra(kept_extras(receipt.extras), component.extra)
    uv = uv_path()
    argv = uv_tool_install_argv(uv or "uv", receipt, extras)
    if uv is None:
        return InstallPlan(Installer.COMMAND, command=shown_command(argv), conflicts=conflicts)
    return InstallPlan(
        Installer.APP,
        argv=argv,
        command=shown_command(argv),
        conflicts=conflicts,
        env=receipt.environment(),
    )


def refresh() -> None:
    """Forget what was looked up of this environment: an install ran (an
    update moves the version every component is pinned to)."""
    uv_path.cache_clear()
    _version.cache_clear()
    _checkout.cache_clear()


@functools.cache
def uv_path() -> str | None:
    """uv, looked for where a Dock-started app's PATH does not reach too.

    Looked up once, and again after each install (``refresh``): Settings asks
    for every component, and on Windows each lookup tries each PATH folder
    with each executable extension.
    """
    from roomkit_ui.cli_exec import search_path

    return shutil.which("uv", path=search_path())


def shown_command(argv: tuple[str, ...]) -> str:
    """*argv* as the user would type it in this system's shell."""
    if sys.platform == "win32":
        return subprocess.list2cmdline(argv)
    return shlex.join(argv)


def _conflicts(component: Component) -> tuple[str, ...]:
    """The installed components *component* would break: the exclusive extras
    pin transformers versions no two of them share."""
    if component.extra not in EXCLUSIVE_EXTRAS:
        return ()
    return tuple(
        other.title
        for other in components()
        if other.extra in EXCLUSIVE_EXTRAS and other.extra != component.extra and other.installed()
    )


def _spec(extra: str) -> str:
    """The extra, pinned to the running version: installing it never moves the app."""
    version = _version()
    return f"{DISTRIBUTION}[{extra}]=={version}" if version else f"{DISTRIBUTION}[{extra}]"


@functools.cache
def _version() -> str | None:
    try:
        return importlib.metadata.version(DISTRIBUTION)
    except importlib.metadata.PackageNotFoundError:
        return None


@functools.cache
def _checkout() -> Path | None:
    return _editable_checkout()


def installer_argv(spec: str, *, upgrade: bool = False) -> tuple[str, ...] | None:
    """uv when it is on the PATH (it targets this interpreter's environment),
    else this environment's pip; None when neither is there (a uv-made venv
    carries no pip).  *upgrade* lets the app itself move, and nothing else
    that need not."""
    uv = uv_path()
    if uv:
        flags = ("--upgrade-package", DISTRIBUTION) if upgrade else ()
        return (uv, "pip", "install", "--python", sys.executable, *flags, spec)
    if importlib.util.find_spec("pip") is not None:
        return (sys.executable, "-m", "pip", "install", *(("--upgrade",) if upgrade else ()), spec)
    return None


def _environment_note(component: Component) -> str:
    """What the user should know of an install the app runs here."""
    if (Path(sys.prefix) / "uv-receipt.toml").exists():
        return (
            "Installed with uv tool: a `uv tool upgrade` leaves it out. Reinstall then "
            f"with: uv tool install '{DISTRIBUTION}[{component.extra}]'"
        )
    return ""
