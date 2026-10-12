"""How this install takes a component: an optional backend, one extra of the app.

Settings → Models & components → Components lists them, and a provider marked "not installed" or a
session that could not start offers to install one.  What installing means
depends on how the app itself was installed:

* a frozen build (.app, .exe) carries what it can and cannot be changed, so
  there is nothing to run;
* a source checkout (an editable install) belongs to ``uv sync``, which
  would undo anything pip added: the user gets the command to run there;
* any other environment (pip, pipx, uv tool): the app runs the install, with
  uv when it is on the PATH, else pip, pinned to the running version so the
  app itself never moves.  Only the app's own extras are ever installed.

Pure logic: the runner (``component_installer``) and the pages call in.
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import shutil
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from urllib.parse import unquote, urlsplit

from roomkit_ui.features import DISTRIBUTION, EXCLUSIVE_EXTRAS, FEATURES, is_available

# What a user should know before installing one: its weight.
_NOTES = {
    "mcp-apps": "A large download: Qt WebEngine.",
    "pocket-tts": "A very large download: PyTorch, several GB.",
    "qwen3-tts": "A very large download: PyTorch, several GB.",
    "neutts": "A very large download: PyTorch, several GB.",
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


def install_plan(component: Component) -> InstallPlan:
    """How this install takes *component*."""
    conflicts = _conflicts(component)
    if getattr(sys, "frozen", False):
        return InstallPlan(
            Installer.NONE,
            note=f"{component.title} is not part of this build: it needs a Python install "
            "of RoomKit UI (see the README).",
        )
    checkout = _editable_checkout()
    if checkout is not None:
        return InstallPlan(
            Installer.COMMAND,
            command=f"uv sync --inexact --extra {component.extra}",
            conflicts=conflicts,
            note=f"A source checkout: run it in {checkout}.",
        )
    spec = _spec(component.extra)
    argv = _installer_argv(spec)
    if argv is None:
        return InstallPlan(Installer.COMMAND, command=f"pip install '{spec}'", conflicts=conflicts)
    return InstallPlan(
        Installer.APP,
        argv=argv,
        command=" ".join(argv[:-1] + (f"'{spec}'",)),
        conflicts=conflicts,
        note=_environment_note(component),
    )


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
    try:
        version = importlib.metadata.version(DISTRIBUTION)
    except importlib.metadata.PackageNotFoundError:
        return f"{DISTRIBUTION}[{extra}]"
    return f"{DISTRIBUTION}[{extra}]=={version}"


def _installer_argv(spec: str) -> tuple[str, ...] | None:
    """uv when it is on the PATH (it targets this interpreter's environment),
    else this environment's pip; None when neither is there (a uv-made venv
    carries no pip)."""
    from roomkit_ui.cli_exec import search_path

    uv = shutil.which("uv", path=search_path())
    if uv:
        return (uv, "pip", "install", "--python", sys.executable, spec)
    if importlib.util.find_spec("pip") is not None:
        return (sys.executable, "-m", "pip", "install", spec)
    return None


def _editable_checkout() -> Path | None:
    """The source tree the app runs from, when it is installed editable."""
    try:
        raw = importlib.metadata.distribution(DISTRIBUTION).read_text("direct_url.json")
    except importlib.metadata.PackageNotFoundError:
        return None
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not (data.get("dir_info") or {}).get("editable"):
        return None
    url = urlsplit(str(data.get("url") or ""))
    return Path(unquote(url.path)) if url.scheme == "file" else None


def _environment_note(component: Component) -> str:
    """What the user should know of an install the app runs here."""
    if (Path(sys.prefix) / "uv-receipt.toml").exists():
        return (
            "Installed with uv tool: a `uv tool upgrade` leaves it out. Reinstall then "
            f"with: uv tool install '{DISTRIBUTION}[{component.extra}]'"
        )
    return ""
