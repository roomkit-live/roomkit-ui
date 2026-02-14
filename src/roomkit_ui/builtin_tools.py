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
    {
        "type": "function",
        "name": "list_attitudes",
        "description": (
            "List available attitude presets and custom attitudes. "
            "Call this when the user asks what attitudes or personalities are available."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "type": "function",
        "name": "end_conversation",
        "description": (
            "IMPORTANT: You MUST call this tool whenever the user signals the end "
            "of the conversation. This includes any farewell or closing phrase such as "
            "'bye', 'bye bye', 'goodbye', 'see you', 'see you later', 'that's all', "
            "'thanks bye', 'I'm done', 'good night', 'take care', 'ciao', 'adios', "
            "'au revoir', 'salut', or similar expressions in any language. "
            "Say a brief goodbye FIRST, then ALWAYS call this tool to disconnect."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "type": "function",
        "name": "set_attitude",
        "description": (
            "Switch to an existing attitude preset or custom attitude by name. "
            "Only accepts names returned by list_attitudes. "
            "Call list_attitudes first if you don't know the available names."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "The exact name of an existing attitude (preset or custom).",
                },
            },
            "required": ["name"],
        },
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
    if name == "list_attitudes":
        from roomkit_ui.settings import load_settings
        from roomkit_ui.widgets.settings.constants import ATTITUDE_PRESETS

        settings = load_settings()
        attitudes = [{"name": n, "description": t, "type": "preset"} for n, t in ATTITUDE_PRESETS]
        try:
            custom = json.loads(settings.get("custom_attitudes", "[]"))
            for att in custom:
                if att.get("name"):
                    attitudes.append(
                        {
                            "name": att["name"],
                            "description": att.get("text", ""),
                            "type": "custom",
                        }
                    )
        except (json.JSONDecodeError, TypeError):
            pass
        return json.dumps({"attitudes": attitudes})
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
