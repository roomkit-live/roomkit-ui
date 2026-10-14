"""How this app was installed: what installing a component or an update builds on.

A uv tool environment is described by its receipt (``uv-receipt.toml``), and
``uv tool upgrade`` re-syncs the environment from it: a component added
behind its back (``uv pip install``) is gone after the next upgrade.  A
component or an update goes through ``uv tool install`` instead, rebuilt from
what the receipt records (:func:`uv_tool_install_argv`).  Which extras an
environment carries beyond its receipt is ``env_extras``' question.

Pure: reads files and package metadata, runs nothing.
"""

from __future__ import annotations

import importlib.metadata
import json
import os
import sys
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from urllib.parse import unquote, urlsplit

from roomkit_ui.env_extras import normalize_name
from roomkit_ui.features import DISTRIBUTION, EXCLUSIVE_EXTRAS

# Where Homebrew keeps what a cask installed, by prefix (Apple silicon, Intel).
_HOMEBREW_PREFIXES = ("/opt/homebrew", "/usr/local")

# What a receipt requirement may carry for `--with` to hand it back: any other
# key is a source of its own (git, url, path, a named index…).
_INDEX_KEYS = frozenset({"name", "extras", "specifier", "marker"})
# Receipt keys `uv tool install` takes from its command line alone.  Any other
# (constraints, overrides, [tool.options] such as an index URL) a reinstall
# drops; the link mode alone changes nothing the app sees.
_REBUILT_KEYS = frozenset({"requirements", "python", "entrypoints"})
_HARMLESS_OPTIONS = frozenset({"link-mode"})


class InstallKind(StrEnum):
    """How the running app was installed."""

    FROZEN = "frozen"  # a .app / .exe from the releases page
    HOMEBREW = "homebrew"  # the macOS app, from the Homebrew cask
    CHECKOUT = "checkout"  # a source tree installed editable (uv sync)
    UV_TOOL = "uv-tool"
    PIPX = "pipx"
    PIP = "pip"  # any other Python environment


def install_kind() -> InstallKind:
    if getattr(sys, "frozen", False):
        if sys.platform == "darwin" and homebrew_cask():
            return InstallKind.HOMEBREW
        return InstallKind.FROZEN
    if editable_checkout() is not None:
        return InstallKind.CHECKOUT
    if uv_tool_receipt() is not None:
        return InstallKind.UV_TOOL
    if pipx_venv():
        return InstallKind.PIPX
    return InstallKind.PIP


def editable_checkout() -> Path | None:
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


def homebrew_cask(prefixes: Iterable[str] | None = None) -> bool:
    """Whether the Homebrew cask installed the app (its Caskroom entry)."""
    if prefixes is None:
        prefixes = [p for p in (os.environ.get("HOMEBREW_PREFIX"), *_HOMEBREW_PREFIXES) if p]
    return any((Path(prefix) / "Caskroom" / DISTRIBUTION).is_dir() for prefix in prefixes)


def pipx_venv(prefix: Path | None = None) -> bool:
    """Whether the running environment is the one pipx made for the app."""
    path = Path(prefix or sys.prefix) / "pipx_metadata.json"
    try:
        package = json.loads(path.read_text(encoding="utf-8"))["main_package"]["package"]
    except (OSError, ValueError, KeyError, TypeError):
        return False
    return str(package) == DISTRIBUTION


@dataclass(frozen=True)
class UvToolReceipt:
    """What ``uv tool install`` recorded for the environment the app runs in."""

    tool_dir: Path  # the tool directory holding the environment
    bin_dir: Path | None  # where its roomkit-ui command was linked
    extras: tuple[str, ...]
    specifier: str  # the user's own constraint on roomkit-ui ("" when none)
    python: str  # the interpreter request it was made with ("" when none)
    with_requirements: tuple[str, ...]  # what `--with` added, as `--with` takes it
    # False when it records what `uv tool install` could not be handed back
    # (a git or path source, constraints, overrides): only `uv tool upgrade` keeps it.
    rebuildable: bool = True

    def environment(self) -> tuple[tuple[str, str], ...]:
        """Points uv at this very environment, whatever the app's own says
        (an app started from the Dock lacks a shell's UV_TOOL_DIR)."""
        env = [("UV_TOOL_DIR", str(self.tool_dir))]
        if self.bin_dir is not None:
            env.append(("UV_TOOL_BIN_DIR", str(self.bin_dir)))
        return tuple(env)


def uv_tool_receipt(prefix: Path | None = None) -> UvToolReceipt | None:
    """The receipt of the uv tool environment the app runs in, or None when
    the app does not run in one (or the receipt names another tool)."""
    env = Path(prefix or sys.prefix)
    try:
        tool = tomllib.loads((env / "uv-receipt.toml").read_text(encoding="utf-8"))["tool"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    # uv names a tool's environment after it: anything else is not ours to rebuild.
    if not isinstance(tool, dict) or normalize_name(env.name) != DISTRIBUTION:
        return None
    requirements = [r for r in tool.get("requirements") or () if isinstance(r, dict)]
    app = next(
        (r for r in requirements if normalize_name(str(r.get("name"))) == DISTRIBUTION), None
    )
    if app is None:
        return None
    others = [r for r in requirements if r is not app]
    python = tool.get("python")
    return UvToolReceipt(
        tool_dir=env.parent,
        bin_dir=_bin_dir(tool.get("entrypoints")),
        # Normalized: "smart_turn" must still be seen as exclusive (with_extra).
        extras=tuple(normalize_name(str(extra)) for extra in app.get("extras") or ()),
        specifier=str(app.get("specifier") or ""),
        python=python if isinstance(python, str) else "",
        with_requirements=tuple(_receipt_requirement(r) for r in others),
        rebuildable=_rebuildable(tool, requirements),
    )


def _rebuildable(tool: dict, requirements: list[dict]) -> bool:
    if not all(set(requirement) <= _INDEX_KEYS for requirement in requirements):
        return False
    options = tool.get("options") or {}
    if not isinstance(options, dict) or set(options) - _HARMLESS_OPTIONS:
        return False
    return not any(value for key, value in tool.items() if key not in _REBUILT_KEYS | {"options"})


def _bin_dir(entrypoints: object) -> Path | None:
    for entry in entrypoints if isinstance(entrypoints, list) else ():
        if isinstance(entry, dict) and entry.get("install-path"):
            return Path(str(entry["install-path"])).parent
    return None


def _receipt_requirement(requirement: dict) -> str:
    extras = requirement.get("extras") or ()
    text = str(requirement["name"]) + (f"[{','.join(extras)}]" if extras else "")
    text += str(requirement.get("specifier") or "")
    marker = requirement.get("marker")
    return f"{text}; {marker}" if marker else text


def uv_tool_install_argv(
    uv: str, receipt: UvToolReceipt, extras: Iterable[str], *, upgrade: bool = False
) -> tuple[str, ...]:
    """``uv tool install`` of the app with *extras*, keeping the rest of the receipt.

    ``--python`` names the environment's own interpreter: without it uv
    rebuilds the environment on the newest Python it finds.  No version pin
    is added: it would go into the receipt and hold back every later
    upgrade.  An update (*upgrade*) drops the user's own constraint too: it
    is what moves the app.
    """
    python = receipt.python or "{}.{}".format(*sys.version_info[:2])
    argv = [uv, "tool", "install", *(["--upgrade"] if upgrade else []), "--python", python]
    for requirement in receipt.with_requirements:
        argv += ["--with", requirement]
    extras = tuple(extras)
    spec = DISTRIBUTION + (f"[{','.join(extras)}]" if extras else "")
    argv.append(spec if upgrade else spec + receipt.specifier)
    return tuple(argv)


def with_extra(extras: Iterable[str], extra: str) -> tuple[str, ...]:
    """*extras* and *extra*; an exclusive extra replaces the exclusive one there
    (two of them pin transformers versions no environment can hold together)."""
    kept = [e for e in extras if not (extra in EXCLUSIVE_EXTRAS and e in EXCLUSIVE_EXTRAS)]
    return tuple(kept) if extra in kept else (*kept, extra)
