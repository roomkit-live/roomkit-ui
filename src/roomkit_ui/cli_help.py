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


async def probe_help(
    argv: list[str],
    *,
    display: str,
    depth: int,
    timeout: float,
    byte_cap: int,
    registry: ProcessRegistry,
) -> str:
    """Return concatenated ``--help`` output for *argv* down to *depth* levels.

    Probes each level concurrently and stops once *byte_cap* is spent, which
    also bounds the spawn count. Returns "" if the CLI has no usable help —
    the tool stays callable on its description alone.
    """
    if depth < 1:
        return ""

    root = await _help_text(argv, timeout=timeout, registry=registry)
    if not root:
        return ""

    chunks = [root]
    used = len(root)
    # Each level explores the commands the previous level's help text listed.
    frontier: list[tuple[list[str], str]] = [([], root)]

    for _ in range(depth - 1):
        targets = [path + [sub] for path, text in frontier for sub in parse_subcommands(text)]
        if not targets or used >= byte_cap:
            break

        texts = await asyncio.gather(
            *(_help_text([*argv, *path], timeout=timeout, registry=registry) for path in targets)
        )
        frontier = []
        for path, text in zip(targets, texts, strict=True):
            if not text:
                continue
            section = f"\n\n$ {display} {' '.join(path)} --help\n{text}"
            if used + len(section) > byte_cap:
                logger.info("CLI help for %r hit the %d-byte cap", display, byte_cap)
                return "".join(chunks)
            chunks.append(section)
            used += len(section)
            frontier.append((path, text))

    return "".join(chunks)


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


async def _help_text(argv: list[str], *, timeout: float, registry: ProcessRegistry) -> str:
    result = await asyncio.to_thread(
        run_sync,
        [*argv, "--help"],
        timeout=timeout,
        registry=registry,
        extra_env=_PROBE_ENV,
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
