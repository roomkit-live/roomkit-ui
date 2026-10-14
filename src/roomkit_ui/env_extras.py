"""Which of the app's extras an environment carries, read from its distributions.

Where no receipt records them — a pip venv, or components an older version
added to a uv tool environment with ``uv pip`` — the extras are judged from
the installed distributions and each extra's own requirements, never from
module probes: a probe says whether a feature works, not which extra brought
it.  No marker but ``extra == ...`` is evaluated (``packaging`` is not a
dependency): a requirement bound to a platform or a Python version is left
out, which only ever makes an extra look lighter than it is.

Pure: reads package metadata, runs nothing.
"""

from __future__ import annotations

import importlib.metadata
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from functools import cache

from roomkit_ui.features import DISTRIBUTION, EXCLUSIVE_EXTRAS, FEATURES

# An installed distribution's requirements (as its metadata lists them), None
# when it is not installed.  Injected by the tests.
Requires = Callable[[str], "tuple[str, ...] | None"]

_REQUIREMENT = re.compile(
    r"\s*(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[(?P<extras>[^\]]*)\])?"
    r"[^;]*(?:;(?P<marker>.*))?"
)
_ONLY_EXTRA = re.compile(r"""\(?\s*extra\s*==\s*["']([^"']+)["']\s*\)?""")


@dataclass(frozen=True)
class _Requirement:
    name: str  # normalized
    extras: tuple[str, ...]  # normalized
    text: str  # the requirement without its marker
    marker: str


def normalize_name(name: str) -> str:
    """PEP 503 / 685: one spelling for a distribution or extra name."""
    return re.sub(r"[-_.]+", "-", name).lower().strip()


def _parse(line: str) -> _Requirement | None:
    match = _REQUIREMENT.fullmatch(line)
    if match is None:
        return None
    extras = tuple(normalize_name(e) for e in (match["extras"] or "").split(",") if e.strip())
    text = line.split(";", 1)[0].strip()
    return _Requirement(
        normalize_name(match["name"]), extras, text, (match["marker"] or "").strip()
    )


@cache
def _installed_requires(name: str) -> tuple[str, ...] | None:
    try:
        return tuple(importlib.metadata.distribution(name).requires or ())
    except importlib.metadata.PackageNotFoundError:
        return None


def refresh() -> None:
    """Forget the metadata read: a component or an update was installed."""
    _installed_requires.cache_clear()


def _requirements(name: str, extra: str, requires: Requires) -> list[_Requirement]:
    """What *name* requires for *extra* alone ("" for its own requirements)."""
    found = []
    for line in requires(name) or ():
        requirement = _parse(line)
        if requirement is None:
            continue
        match = _ONLY_EXTRA.fullmatch(requirement.marker)
        wanted = normalize_name(match[1]) if match else (None if requirement.marker else "")
        if wanted == extra:
            found.append(requirement)
    return found


def _reach(
    requirements: Iterable[_Requirement], requires: Requires, *, transitive: bool
) -> set[str]:
    """The distributions *requirements* name, through the extras they ask for;
    *transitive*: and everything those require in turn."""
    names: set[str] = set()
    pending = list(requirements)
    seen: set[tuple[str, str]] = set()
    while pending:
        requirement = pending.pop()
        names.add(requirement.name)
        for extra in ("", *requirement.extras) if transitive else requirement.extras:
            if (requirement.name, extra) not in seen:
                seen.add((requirement.name, extra))
                pending.extend(_requirements(requirement.name, extra, requires))
    return names


def _leaves(extra: str, requires: Requires) -> set[str]:
    """The distributions the app's *extra* names."""
    return _reach(_requirements(DISTRIBUTION, extra, requires), requires, transitive=False)


def _app_extras() -> tuple[str, ...]:
    """The extras behind the app's components, in the order features list them."""
    return tuple(dict.fromkeys(feature.extra for feature in FEATURES.values()))


def installed_extras(requires: Requires = _installed_requires) -> tuple[str, ...]:
    """The app's extras this environment carries, read from its distributions.

    One counts when every distribution it names is installed and one of them
    is not pulled in anyway (by the core, or for an exclusive extra by the
    others found): an extra whose distributions the core already brings
    tells nothing.  At most one exclusive extra is kept.
    """
    core = {DISTRIBUTION} | _reach(
        _requirements(DISTRIBUTION, "", requires), requires, transitive=True
    )
    leaves = {extra: _leaves(extra, requires) for extra in _app_extras()}
    found = [
        extra
        for extra, names in leaves.items()
        if names and all(requires(n) is not None for n in names) and names - core
    ]
    exclusive = [extra for extra in found if extra in EXCLUSIVE_EXTRAS]
    if len(exclusive) < 2:
        return tuple(found)
    keep = _one_exclusive(exclusive, found, core, requires) or sorted(exclusive)[0]
    return tuple(e for e in found if e not in EXCLUSIVE_EXTRAS or e == keep)


def _one_exclusive(
    exclusive: list[str], found: list[str], core: set[str], requires: Requires
) -> str | None:
    """The exclusive extra the others found do not explain: Smart Turn names
    transformers, onnxruntime and numpy, which a voice-cloning TTS installs too."""
    for extra in sorted(exclusive):
        others = [r for e in found if e != extra for r in _requirements(DISTRIBUTION, e, requires)]
        if _leaves(extra, requires) - core - _reach(others, requires, transitive=True):
            return extra
    return None


def _brought(extra: str, requires: Requires, seen: frozenset[str] = frozenset()) -> set[str]:
    """The requirements *extra* brings, the app's own extras it names expanded."""
    texts: set[str] = set()
    for requirement in _requirements(DISTRIBUTION, normalize_name(extra), requires):
        if requirement.name != DISTRIBUTION:
            texts.add(requirement.text)
            continue
        for inner in requirement.extras:
            if inner not in seen:
                texts |= _brought(inner, requires, seen | {extra})
    return texts


def kept_extras(
    recorded: Iterable[str], requires: Requires = _installed_requires
) -> tuple[str, ...]:
    """*recorded* (a receipt's extras), and what the environment carries beyond
    them: components an older version added with ``uv pip``, which the next
    ``uv tool install`` or ``upgrade`` would otherwise remove.

    "all" records every extra it gathers.  The receipt's own exclusive extra
    wins over one found installed.
    """
    recorded = tuple(recorded)
    brought: set[str] = set()
    for extra in recorded:
        brought |= _brought(extra, requires)
    has_exclusive = any(normalize_name(e) in EXCLUSIVE_EXTRAS for e in recorded)
    extra_found = [
        extra
        for extra in installed_extras(requires)
        if not _brought(extra, requires) <= brought
        and not (has_exclusive and extra in EXCLUSIVE_EXTRAS)
    ]
    return (*recorded, *extra_found)
