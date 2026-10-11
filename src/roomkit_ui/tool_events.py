"""Per-invocation tool events shared by the engine and conversation UI."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments_json: str
    resource_uri: str = ""
    server_name: str = ""


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    status: Literal["completed", "failed", "cancelled"]
    text: str
