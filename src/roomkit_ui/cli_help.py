"""Seed a CLI's ``--help`` output into its tool description.

A single level of ``--help`` is not enough: it lists command groups and
nothing about arguments, so the model would know the tool exists without
knowing how to call it. Probing one level deeper yields the full command
inventory — enough to *choose* a command. The model then learns a specific
command's arguments by calling ``--help`` through the tool itself, which is
cheap because CLI usage errors are self-correcting.

Command lists are parsed across the layouts in the wild — Click/Typer, Rich
boxes, and Cobra (``gh``, ``kubectl``, ``docker``). A CLI whose help fits
none of them (``git``, ``brew``) just seeds depth 1 and the model explores
from there.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re

from roomkit_ui.cli_exec import ProcessRegistry, run_sync

logger = logging.getLogger(__name__)

# One entry in a command list, across the help styles in the wild:
#   Rich / Typer   "│ pr          Manage pull requests.               │"
#   Plain Click    "  pr          Manage pull requests."
#   Cobra / gh     "  pr:         Manage pull requests"
# Leading "-" is excluded so option lines never look like commands.
_COMMAND_LINE = re.compile(r"^\s*│?\s+([a-z][a-z0-9_-]*):?\s{2,}\S")

_BOX_EDGE = "│"

# Rich wraps at the terminal width, and an 80-column wrap splits enum values
# across lines — "[red|amber|green|sky|violet" / "|pink|slate]" — corrupting
# exactly the text the model has to read. NO_COLOR/TERM are no-ops here:
# Rich already drops ANSI when stdout is not a tty.
_PROBE_ENV = {"COLUMNS": "200"}

# --help probes in flight at once. The byte cap is checked between batches:
# launching a whole level first spawned ~270 processes for gh at depth 3,
# nearly all of them past the cap.
_PROBE_BATCH = 16

# Probe results for the app's lifetime — see probe_help.
_help_cache: dict[tuple, str] = {}


async def probe_help(
    argv: list[str],
    *,
    display: str,
    depth: int,
    timeout: float,
    byte_cap: int,
    registry: ProcessRegistry,
    env: dict[str, str],
) -> str:
    """Return concatenated ``--help`` output for *argv* down to *depth* levels.

    Probes each level in batches of ``_PROBE_BATCH`` and stops once
    *byte_cap* is spent — checked between batches, so it bounds the spawn
    count too. Returns "" if the CLI has no usable help — the tool stays
    callable on its description alone.

    The result is kept for the app's lifetime, keyed by the binary's mtime
    so an upgraded CLI is probed again: every session start used to re-run
    every probe.

    *env* is the tool's declared environment. It applies here too: a CLI run
    with a variable set must be described by the help text it prints with that
    variable set. An explicit declaration wins over our probe defaults.
    """
    if depth < 1:
        return ""

    key = _cache_key(argv, display, depth, byte_cap, env)
    if key is not None and key in _help_cache:
        return _help_cache[key]
    help_text = await _probe(
        argv,
        display=display,
        depth=depth,
        timeout=timeout,
        byte_cap=byte_cap,
        registry=registry,
        env={**_PROBE_ENV, **env},
    )
    # An empty probe may be a timeout this once: try again next session.
    if key is not None and help_text:
        _help_cache[key] = help_text
    return help_text


def clear_help_cache() -> None:
    """Forget every cached ``--help`` probe (tests)."""
    _help_cache.clear()


def _cache_key(
    argv: list[str], display: str, depth: int, byte_cap: int, env: dict[str, str]
) -> tuple | None:
    """What a probe's output depends on; None when the binary cannot be stat'd."""
    try:
        mtime = os.stat(argv[0]).st_mtime_ns
    except (OSError, IndexError):
        return None
    return (tuple(argv), display, depth, byte_cap, tuple(sorted(env.items())), mtime)


async def _probe(
    argv: list[str],
    *,
    display: str,
    depth: int,
    timeout: float,
    byte_cap: int,
    registry: ProcessRegistry,
    env: dict[str, str],
) -> str:
    root = await _help_text(argv, timeout=timeout, registry=registry, env=env)
    if not root:
        return ""

    chunks = [root]
    # Each level explores the commands the previous level's help text listed.
    frontier: list[tuple[list[str], str]] = [([], root)]

    for _ in range(depth - 1):
        targets = [path + [sub] for path, text in frontier for sub in parse_subcommands(text)]
        if not targets or sum(map(len, chunks)) >= byte_cap:
            break
        frontier = []
        for start in range(0, len(targets), _PROBE_BATCH):
            batch = targets[start : start + _PROBE_BATCH]
            texts = await asyncio.gather(
                *(
                    _help_text([*argv, *path], timeout=timeout, registry=registry, env=env)
                    for path in batch
                )
            )
            if not _keep_sections(chunks, frontier, batch, texts, display, byte_cap):
                logger.info("CLI help for %r hit the %d-byte cap", display, byte_cap)
                return "".join(chunks)

    return "".join(chunks)


def _keep_sections(
    chunks: list[str],
    frontier: list[tuple[list[str], str]],
    paths: list[list[str]],
    texts: list[str],
    display: str,
    byte_cap: int,
) -> bool:
    """Append each probed section in order; False once one would pass the cap."""
    used = sum(map(len, chunks))
    for path, text in zip(paths, texts, strict=True):
        if not text:
            continue
        section = f"\n\n$ {display} {' '.join(path)} --help\n{text}"
        if used + len(section) > byte_cap:
            return False
        chunks.append(section)
        used += len(section)
        frontier.append((path, text))
    return True


def parse_subcommands(help_text: str) -> list[str]:
    """Return the subcommand names a ``--help`` block lists.

    Handles Click/Typer ("Commands:", Rich boxes) and Cobra ("Available
    Commands:", and gh's several "CORE COMMANDS" / "ADDITIONAL COMMANDS"
    groups), so a CLI can have more than one command section.

    Best-effort: a parse miss costs seeding depth, not correctness, since the
    model can still discover commands by calling ``--help`` through the tool.
    """
    names: list[str] = []
    in_section = False

    for line in help_text.splitlines():
        if _is_commands_header(line):
            in_section = True
            continue
        if not in_section:
            continue
        if _ends_section(line):
            in_section = False
            continue
        match = _COMMAND_LINE.match(line)
        if match and match.group(1) not in names:
            names.append(match.group(1))

    return names


async def _help_text(
    argv: list[str], *, timeout: float, registry: ProcessRegistry, env: dict[str, str]
) -> str:
    result = await asyncio.to_thread(
        run_sync,
        [*argv, "--help"],
        timeout=timeout,
        registry=registry,
        extra_env=env,
    )
    if result.timed_out or result.exit_code != 0:
        return ""
    return result.stdout.strip()


def _is_commands_header(line: str) -> bool:
    """True for "Commands:", "Available Commands:", "CORE COMMANDS", "╭─ Commands ─╮"."""
    # An entry like "alias:  Create command shortcuts" mentions commands but
    # heads nothing — rule those out before matching on the word.
    if _COMMAND_LINE.match(line):
        return False
    return "COMMANDS" in line.upper()


def _ends_section(line: str) -> bool:
    """True once the command list is over.

    Blank lines do not end it: gh separates its command groups with them, and
    the next heading either re-opens the run or closes it on its own.
    """
    if "╰" in line or "╭" in line:
        # A Rich box closed, or the next one (Options, …) opened.
        return True
    if not line.strip():
        return False
    # A box edge sits at column 0 and is decoration, not a heading — treat it
    # like the indentation it stands in for.
    return not (line[0].isspace() or line[0] in _BOX_EDGE)
