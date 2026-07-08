"""Tool dispatch mixin for the voice engine.

Owns the unified 0.7.x ``ToolHandler`` (``async (name, arguments) -> str``)
plus the companion attitude/paste/MCP-App call paths.  Pulled out of
``engine.py`` because these are orthogonal to session lifecycle.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

from roomkit_ui.builtin_tools import handle_builtin_tool
from roomkit_ui.cleanup import cleanup_stale_fds

if TYPE_CHECKING:
    from roomkit_ui.mcp_manager import MCPManager

logger = logging.getLogger(__name__)

_ATTITUDE_MARKER = "\n\n# Attitude\n"


def compose_attitude_prompt(base_prompt: str, attitude_description: str) -> str:
    """Build a full system prompt by appending an ``# Attitude`` section.

    * ``attitude_description`` non-empty → append the section to ``base_prompt``.
    * ``attitude_description`` empty → return ``base_prompt`` verbatim.

    Pure function; the VC path feeds the result to ``AIChannel.set_system_prompt``
    and the realtime path to ``RealtimeVoiceChannel.reconfigure_session``.
    """
    base = base_prompt or ""
    if attitude_description:
        return f"{base}{_ATTITUDE_MARKER}{attitude_description}"
    return base


class ToolMixin:
    """Tool / attitude / paste handlers for ``Engine``.

    All state (``_mcp``, ``_watchdog``, ``_end_conv_handle``, ``_attitude``,
    ``_ai_channel``) lives on the concrete ``Engine`` class.  The type
    annotations below are declared on the mixin so mypy can resolve
    ``self._end_conv_handle`` etc. from within mixin methods without
    bouncing through a cross-class ``has-type`` error.
    """

    # Type declarations (attributes are assigned on the concrete Engine)
    _mcp: MCPManager | None
    _watchdog: Any
    _end_conv_handle: asyncio.TimerHandle | None
    _pending_tool_calls: int
    _attitude: str
    _attitude_name: str
    _base_system_prompt: str
    _ai_channel: Any
    _channel: Any
    _session: Any

    async def _handle_tool_call(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> str:
        """Handle built-in tools or forward to MCP manager.

        Unified 0.7.x ToolHandler signature: ``async (name, arguments) -> str``
        — shared by AIChannel and RealtimeVoiceChannel. Use
        ``roomkit.get_current_voice_session()`` if a session handle is ever
        needed here.
        """
        # Check if this is an MCP App tool (has ui:// resource)
        app_info = self._mcp.get_app_tool_info(name) if self._mcp else None  # type: ignore[attr-defined]

        try:
            if app_info is not None:
                self.tool_use_app.emit(  # type: ignore[attr-defined]
                    name,
                    json.dumps(arguments),
                    app_info["uri"],
                    app_info["server"],
                )
            else:
                self.tool_use.emit(name, json.dumps(arguments))  # type: ignore[attr-defined]
        except Exception:
            pass

        # Handle paste_text — copy text to clipboard and simulate paste
        if name == "paste_text":
            return await self._paste_text(arguments.get("text", ""))

        # Handle end_conversation — schedule stop after a delay so the
        # agent's goodbye response can be spoken before disconnecting.
        if name == "end_conversation":
            loop = asyncio.get_running_loop()
            # Cancel any previously scheduled end_conversation to avoid races
            if self._end_conv_handle is not None:  # type: ignore[attr-defined]
                self._end_conv_handle.cancel()  # type: ignore[attr-defined]
            self._end_conv_handle = loop.call_later(  # type: ignore[attr-defined]
                3.0,
                lambda: loop.create_task(self.stop()),  # type: ignore[attr-defined]
            )
            return '{"status": "ok", "message": "Ending conversation in a few seconds."}'

        # Handle attitude changes (needs engine state, not pure builtin)
        if name == "set_attitude":
            return await self._apply_attitude_by_name(arguments.get("name", ""))

        # Try built-in tools first
        builtin_result = handle_builtin_tool(name)
        if builtin_result is not None:
            return builtin_result

        if self._mcp is None:  # type: ignore[attr-defined]
            return '{"error": "Unknown tool"}'

        self._pending_tool_calls += 1  # type: ignore[attr-defined]
        self._watchdog.tool_call_started()  # type: ignore[attr-defined]
        try:
            result = await self._mcp.handle_tool_call(name, arguments)  # type: ignore[attr-defined]
        finally:
            self._pending_tool_calls -= 1  # type: ignore[attr-defined]
            self._watchdog.tool_call_ended()  # type: ignore[attr-defined]
        # MCP/anyio can leak orphaned timer callbacks under qasync when a
        # tool call fails or the server crashes.  Run a lightweight cleanup
        # after every MCP call to prevent 100% CPU spin loops.
        # timers_only=True: don't touch FD notifiers during an active session.
        cleanup_stale_fds(timers_only=True)

        # Notify the UI so the app widget can display the result
        if app_info is not None:
            try:
                self.tool_result_app.emit(name, result)  # type: ignore[attr-defined]
            except Exception:
                pass

        return result

    async def _apply_attitude_by_name(self, name: str) -> str:
        """Look up an attitude by name and apply it. Rejects unknown names."""
        if not name:
            return json.dumps({"error": "Attitude name is required."})

        # Look up in presets
        from roomkit_ui.constants import ATTITUDE_PRESETS

        for pname, ptext in ATTITUDE_PRESETS:
            if pname.lower() == name.lower():
                return await self._apply_attitude(pname, ptext)

        # Look up in custom attitudes
        try:
            from roomkit_ui.settings import load_settings

            settings = load_settings()
            for att in json.loads(settings.get("custom_attitudes", "[]")):
                if att.get("name", "").lower() == name.lower():
                    return await self._apply_attitude(att["name"], att.get("text", ""))
        except (json.JSONDecodeError, TypeError):
            pass

        # Not found — return error with available names
        available = [n for n, _ in ATTITUDE_PRESETS]
        try:
            from roomkit_ui.settings import load_settings

            settings = load_settings()
            for att in json.loads(settings.get("custom_attitudes", "[]")):
                if att.get("name"):
                    available.append(att["name"])
        except (json.JSONDecodeError, TypeError):
            pass
        return json.dumps(
            {
                "error": f"Unknown attitude '{name}'.",
                "available": available,
            }
        )

    async def _apply_attitude(self, name: str, description: str) -> str:
        """Apply a known attitude and update the live system prompt.

        Routing:

        * **Voice-channel mode** (``_ai_channel`` is set) — pushes the full
          prompt via the public ``AIChannel.set_system_prompt``.  ``AIChannel``
          builds context fresh every turn, so the new prompt takes effect on
          the next LLM turn.
        * **Realtime mode** (``_channel`` is a ``RealtimeVoiceChannel``) —
          calls the public ``reconfigure_session(session, system_prompt=…)``.
          That pushes a ``session.update`` to Gemini Live / OpenAI Realtime
          so the attitude changes mid-session without restarting.
        """
        self._attitude = description
        self._attitude_name = name

        new_prompt = compose_attitude_prompt(self._base_system_prompt, description)

        if self._ai_channel is not None:
            # Voice-channel mode: AIChannel rebuilds context per turn, so this
            # takes effect on the next turn without dropping memory/tool state.
            self._ai_channel.set_system_prompt(new_prompt)
        elif self._channel is not None and hasattr(self._channel, "reconfigure_session"):
            # Realtime mode: push to the provider via the public API so the
            # agent switches tone mid-conversation without restarting.
            try:
                await self._channel.reconfigure_session(self._session, system_prompt=new_prompt)
            except Exception:
                logger.exception("reconfigure_session failed for attitude change")

        try:
            self.attitude_changed.emit(self._attitude_name)  # type: ignore[attr-defined]
        except Exception:
            pass
        return json.dumps(
            {
                "status": "ok",
                "attitude": name,
                "instruction": f"Adopt this attitude now: {description}",
            }
        )

    @staticmethod
    async def _paste_text(text: str) -> str:
        """Copy text to clipboard and simulate paste into the focused input."""
        if not text:
            return json.dumps({"error": "No text provided."})
        try:
            from roomkit_ui.paste import _copy_to_clipboard, _simulate_paste

            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, _copy_to_clipboard, text)
            await loop.run_in_executor(None, _simulate_paste)
            logger.info("paste_text: pasted %d chars", len(text))
            return json.dumps({"status": "ok", "chars": len(text)})
        except FileNotFoundError as exc:
            msg = f"Missing helper program: {exc.filename}"
            logger.error("paste_text: %s", msg)
            return json.dumps({"error": msg})
        except Exception as exc:
            msg = f"Paste failed: {exc}"
            logger.error("paste_text: %s", msg)
            return json.dumps({"error": msg})

    async def handle_app_tool_call(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Proxy a tool call initiated by an MCP App back through MCP.

        Delegates to :meth:`_handle_tool_call` so the UI signal surface
        (``tool_use_app`` / ``tool_result_app``) stays consistent no matter
        which side fired the call — the AI provider's tool loop or a user
        clicking inside an MCP App HTML widget.
        """
        if self._mcp is None:
            return json.dumps({"error": "MCP not connected"})
        try:
            return await self._handle_tool_call(tool_name, arguments)
        except Exception as exc:
            logger.exception("MCP App tool call %r failed", tool_name)
            return json.dumps({"error": str(exc)})
