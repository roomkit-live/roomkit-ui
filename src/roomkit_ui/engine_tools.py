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
    from roomkit_ui.cli_tools import CliToolManager
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


_DEFAULT_SYSTEM_PROMPT = "You are a friendly voice assistant. Be concise and helpful."


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
    _cli: CliToolManager | None
    _watchdog: Any
    _end_conv_handle: asyncio.TimerHandle | None
    _pending_tool_calls: int
    _attitude: str
    _attitude_name: str
    _base_system_prompt: str
    _memory_recap: str
    _session_settings: dict
    _ai_channel: Any
    _channel: Any
    _session: Any

    def _compose_session_prompt(self, settings: dict) -> str:
        """The session's system prompt: the user's, plus the attitude section.

        The user's base prompt is kept apart so set_attitude can rebuild the
        full prompt mid-session (AIChannel.set_system_prompt in the voice
        channel, reconfigure_session in realtime) without stripping the old
        attitude out of it.
        """
        from roomkit_ui.engine_audio import resolve_attitude

        self._base_system_prompt = settings.get("system_prompt", _DEFAULT_SYSTEM_PROMPT)
        self._memory_recap = ""  # known once the kit opens its store
        attitude = self._attitude or resolve_attitude(settings)
        if attitude:
            self._attitude = attitude
            if not self._attitude_name:
                self._attitude_name = settings.get("selected_attitude", "") or attitude
        return self._session_prompt()

    def _session_prompt(self) -> str:
        """The user's prompt, the memory recap, then the attitude section."""
        base = self._base_system_prompt
        if self._memory_recap:
            base = f"{base}\n\n{self._memory_recap}"
        return compose_attitude_prompt(base, self._attitude)

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
        self._show_tool_use(name, arguments, app_info)

        engine_result = await self._handle_engine_tool(name, arguments)
        if engine_result is not None:
            return engine_result

        builtin_result = handle_builtin_tool(name)
        if builtin_result is not None:
            return builtin_result

        # CLI tools before MCP. Both can take seconds, so both bracket the
        # watchdog — but CLI needs no cleanup_stale_fds, which exists for
        # anyio timers that only the MCP path leaks.
        if self._cli is not None and self._cli.has_tool(name):  # type: ignore[attr-defined]
            self._pending_tool_calls += 1  # type: ignore[attr-defined]
            self._watchdog.tool_call_started()  # type: ignore[attr-defined]
            try:
                return await self._cli.handle_tool_call(name, arguments)  # type: ignore[attr-defined]
            finally:
                self._pending_tool_calls -= 1  # type: ignore[attr-defined]
                self._watchdog.tool_call_ended()  # type: ignore[attr-defined]

        if self._mcp is None:  # type: ignore[attr-defined]
            # roomkit reads this envelope as "not served here", not a result.
            return '{"error": "Unknown tool"}'

        return await self._call_mcp_tool(self._mcp, name, arguments, app_info)

    def _show_tool_use(self, name: str, arguments: dict[str, Any], app_info: Any) -> None:
        """Show the call in the chat — as an MCP App when it has one."""
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

    async def _handle_engine_tool(self, name: str, arguments: dict[str, Any]) -> str | None:
        """The built-ins that need the engine's state; None for any other tool."""
        if name == "paste_text":
            return await self._paste_text(arguments.get("text", ""))
        if name == "end_conversation":
            return self._schedule_end_conversation()
        if name == "set_attitude":
            return await self._apply_attitude_by_name(arguments.get("name", ""))
        if name == "name_speaker":
            from roomkit_ui.speaker_naming import name_speaker_tool

            return name_speaker_tool(self, arguments)
        if name == "recall_conversations":
            # Past-conversation search needs the session's kit and store.
            from roomkit_ui.memory import recall_conversations

            return await recall_conversations(getattr(self, "_kit", None), arguments)
        return None

    def _schedule_end_conversation(self) -> str:
        """Stop the session after a delay, so the goodbye is spoken first.

        A second end_conversation replaces the first rather than racing it.
        """
        loop = asyncio.get_running_loop()
        if self._end_conv_handle is not None:  # type: ignore[attr-defined]
            self._end_conv_handle.cancel()  # type: ignore[attr-defined]
        self._end_conv_handle = loop.call_later(  # type: ignore[attr-defined]
            3.0,
            lambda: self._create_owned_task(  # type: ignore[attr-defined]
                self.stop(),  # type: ignore[attr-defined]
                name="engine_stop_from_tool",
            ),
        )
        return '{"status": "ok", "message": "Ending conversation in a few seconds."}'

    async def _call_mcp_tool(
        self,
        mcp: MCPManager,
        name: str,
        arguments: dict[str, Any],
        app_info: dict[str, str] | None,
    ) -> str:
        """Run an MCP tool for the model; a failure raises ``ToolFailedError``.

        The app widget shows the outcome either way, so a failure is handed
        to it as the ``{"error": ...}`` envelope it reads before it is raised.
        """
        from roomkit import ToolFailedError

        self._pending_tool_calls += 1
        self._watchdog.tool_call_started()
        try:
            result = await mcp.handle_tool_call(name, arguments)
        except ToolFailedError as failure:
            self._show_app_result(app_info, name, json.dumps({"error": failure.message}))
            raise
        finally:
            self._pending_tool_calls -= 1
            self._watchdog.tool_call_ended()
            # MCP/anyio can leak orphaned timer callbacks under qasync when a
            # tool call fails or the server crashes.  Run a lightweight cleanup
            # after every MCP call to prevent 100% CPU spin loops.
            # timers_only=True: don't touch FD notifiers during an active session.
            cleanup_stale_fds(timers_only=True)
        self._show_app_result(app_info, name, result)
        return result

    def _show_app_result(self, app_info: dict[str, str] | None, name: str, result: str) -> None:
        """Hand an MCP App tool's result to its widget; no-op for other tools."""
        if app_info is None:
            return
        try:
            self.tool_result_app.emit(name, result)  # type: ignore[attr-defined]
        except Exception:
            pass

    async def _apply_attitude_by_name(self, name: str) -> str:
        """Look up an attitude by name and apply it.

        A missing or unknown name is refused (``ToolRefusedError``) with the
        names the model can pick from: Gemini reads any returned body as a
        success.
        """
        from roomkit import ToolRefusedError

        if not name:
            raise ToolRefusedError("Attitude name is required.")

        # Look up in presets
        from roomkit_ui.constants import ATTITUDE_PRESETS

        for pname, ptext in ATTITUDE_PRESETS:
            if pname.lower() == name.lower():
                return await self._apply_attitude(pname, ptext)

        custom = self._custom_attitudes()
        for att in custom:
            if att.get("name", "").lower() == name.lower():
                return await self._apply_attitude(att["name"], att.get("text", ""))

        available = [n for n, _ in ATTITUDE_PRESETS]
        available += [att["name"] for att in custom if att.get("name")]
        raise ToolRefusedError(f"Unknown attitude '{name}'. Available: {', '.join(available)}.")

    def _custom_attitudes(self) -> list[dict]:
        """The user's custom attitudes, from the session's settings snapshot.

        Never ``load_settings()`` here: it reads every secret from the OS
        keyring, synchronously on the event loop (and may prompt the macOS
        Keychain) — mid-conversation, for one JSON list the session has.
        """
        try:
            attitudes = json.loads(self._session_settings.get("custom_attitudes", "[]"))
        except (json.JSONDecodeError, TypeError):
            return []
        if not isinstance(attitudes, list):
            return []
        return [att for att in attitudes if isinstance(att, dict)]

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

        new_prompt = self._session_prompt()

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
        """Copy text to clipboard and simulate paste into the focused input.

        A refusal or failure raises (``ToolRefusedError`` / ``ToolFailedError``):
        Gemini reads any returned body as a success.
        """
        from roomkit import ToolFailedError, ToolRefusedError

        from roomkit_ui.paste import PasteError, paste_into_focused

        if not text:
            raise ToolRefusedError("No text provided.")
        try:
            await paste_into_focused(text)
        except PasteError as exc:
            logger.warning("paste_text: %s", exc)
            raise ToolFailedError(str(exc)) from exc
        logger.info("paste_text: pasted %d chars", len(text))
        return json.dumps({"status": "ok", "chars": len(text)})

    async def handle_app_tool_call(
        self,
        origin_server: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> str:
        """Proxy a tool call initiated by an MCP App back through MCP.

        MCP App UIs are trusted only for their owning MCP server.  They cannot
        call built-in tools or tools registered by other MCP servers.
        """
        if self._mcp is None:
            return json.dumps({"error": "MCP not connected"})
        try:
            self._pending_tool_calls += 1
            self._watchdog.tool_call_started()
            try:
                return await self._mcp.handle_app_tool_call(origin_server, tool_name, arguments)
            finally:
                self._pending_tool_calls -= 1
                self._watchdog.tool_call_ended()
                cleanup_stale_fds(timers_only=True)
        except Exception as exc:
            logger.exception("MCP App tool call %r failed", tool_name)
            return json.dumps({"error": str(exc)})
