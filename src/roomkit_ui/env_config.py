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
    """
    env: dict[str, str] = {}
    for line in str(raw or "").splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip():
            env[key.strip()] = value.strip()
    return env
