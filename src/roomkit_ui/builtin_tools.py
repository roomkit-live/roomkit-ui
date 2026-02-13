"""Built-in tools that are always available regardless of MCP servers."""

from __future__ import annotations

import datetime
import json

BUILTIN_TOOLS: list[dict] = [
    {
        "type": "function",
        "name": "get_current_date",
        "description": "Get today's date and day of the week.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "type": "function",
        "name": "get_current_time",
        "description": "Get the current local time.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "type": "function",
        "name": "get_roomkit_info",
        "description": "Get information about RoomKit and RoomKit UI.",
        "parameters": {"type": "object", "properties": {}},
    },
]


def handle_builtin_tool(name: str) -> str | None:
    """Handle a built-in tool call. Returns JSON string or None if not built-in."""
    now = datetime.datetime.now()
    if name == "get_current_date":
        return json.dumps(
            {
                "date": now.strftime("%Y-%m-%d"),
                "day": now.strftime("%A"),
            }
        )
    if name == "get_current_time":
        return json.dumps(
            {
                "time": now.strftime("%H:%M:%S"),
                "timezone": now.astimezone().tzname(),
            }
        )
    if name == "get_roomkit_info":
        return json.dumps(
            {
                "roomkit": (
                    "RoomKit is an open-source Python framework for building "
                    "real-time voice AI applications. It provides a high-level API "
                    "for managing voice sessions with AI providers like Google Gemini "
                    "and OpenAI Realtime, handling audio input/output, echo cancellation, "
                    "noise suppression, and tool calling via the Model Context Protocol (MCP). "
                    "RoomKit is designed to be provider-agnostic and extensible."
                ),
                "roomkit_ui": (
                    "RoomKit UI is a desktop voice assistant built with RoomKit and PySide6 (Qt). "
                    "It lets you have real-time voice conversations with AI, configure multiple "
                    "AI providers, connect MCP servers to give the assistant external tools, "
                    "and includes a system-wide speech-to-text dictation feature. "
                    "It runs on Linux and macOS."
                ),
                "website": "https://www.roomkit.live",
            }
        )
    return None
