"""Parse a ``KEY=VALUE`` block declared in settings.

Leaf module: MCP servers and CLI tools both let you declare environment
variables in a free-text field, and the format belongs to neither.
"""

from __future__ import annotations

from typing import Any


def parse_env_block(raw: Any) -> dict[str, str]:
    """Return the ``KEY=VALUE`` pairs in *raw*, one per line.

    Splits on the first ``=`` only, so a value may contain one. Never raises:
    a malformed line is dropped rather than sinking the whole declaration.
    Pair with ``invalid_env_lines`` wherever someone can see the result — a
    dropped line is a variable that never reaches the child.
    """
    pairs = (_split_pair(line) for line in str(raw or "").splitlines())
    return dict(pair for pair in pairs if pair is not None)


def invalid_env_lines(raw: Any) -> list[str]:
    """Return the non-blank lines of *raw* that are not ``KEY=VALUE``.

    ``parse_env_block`` drops these. Whoever typed one has to be told which,
    or a mistyped variable fails as a CLI that quietly behaves wrong.
    """
    return [
        line.strip()
        for line in str(raw or "").splitlines()
        if line.strip() and _split_pair(line) is None
    ]


def _split_pair(line: str) -> tuple[str, str] | None:
    """Return the ``KEY=VALUE`` halves of *line*, or None if it is neither.

    The single definition of what counts as a declaration, so the parser and
    the reporting above it can never disagree about a given line.
    """
    key, sep, value = line.partition("=")
    if not sep or not key.strip():
        return None
    return key.strip(), value.strip()
