"""Per-view tool responses needed to reopen an MCP App without its server."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

_MAX_RESPONSES = 64


class AppToolResults:
    """Keep the last response for each tool/input pair, including polling reads."""

    def __init__(self) -> None:
        self._entries: dict[str, dict] = {}

    @staticmethod
    def _key(name: str, arguments: dict[str, Any]) -> str:
        return json.dumps([name, arguments], sort_keys=True, separators=(",", ":"))

    def record(self, name: str, arguments: dict[str, Any], result: str) -> bool:
        key = self._key(name, arguments)
        if key in self._entries and self._entries[key]["result"] == result:
            return False
        self._entries.pop(key, None)
        self._entries[key] = {"name": name, "arguments": deepcopy(arguments), "result": result}
        if len(self._entries) > _MAX_RESPONSES:
            self._entries.pop(next(iter(self._entries)))
        return True

    def lookup(self, name: str, arguments: dict[str, Any]) -> str | None:
        entry = self._entries.get(self._key(name, arguments))
        return entry["result"] if entry else None

    def snapshot(self) -> list[dict]:
        return deepcopy(list(self._entries.values()))

    @classmethod
    def restore(cls, values: list[dict]) -> AppToolResults:
        if not isinstance(values, list) or len(values) > _MAX_RESPONSES:
            raise ValueError("Invalid saved app responses")
        state = cls()
        for entry in values:
            if (
                not isinstance(entry, dict)
                or not isinstance(entry.get("name"), str)
                or not isinstance(entry.get("arguments"), dict)
                or not isinstance(entry.get("result"), str)
            ):
                raise ValueError("Invalid saved app response")
            state.record(entry["name"], entry["arguments"], entry["result"])
        return state
