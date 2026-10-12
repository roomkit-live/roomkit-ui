"""Typed turns through RoomKit's AIChannel, without audio devices or voice models.

The selected thread owns a kit across requests, keeping MCP Apps connected.
Earlier context seeds the session; RoomKit remembers subsequent turns in its room.
WebSocketChannel delivers through in-process callbacks, with no socket opened.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from roomkit_ui.engine_state import EngineState
from roomkit_ui.engine_vc import LOCAL_LLMS, _model_pricing
from roomkit_ui.engine_vc_helpers import reasoning_options, start_local_llm
from roomkit_ui.features import FeatureUnavailableError
from roomkit_ui.providers import create_ai_provider
from roomkit_ui.text_chat import text_chat_unavailable
from roomkit_ui.toolset import tool_search_options

logger = logging.getLogger(__name__)


class TextMixin:
    _kit: Any
    _ai_channel: Any
    _channel: Any
    _ai_pricing: Any
    _room_id: str
    _text_ready: bool
    _cancelling_text_response: bool

    async def _start_text(self, settings: dict, text: str) -> None:
        from roomkit import RoomKit
        from roomkit.channels.ai import AIChannel
        from roomkit.channels.websocket import WebSocketChannel
        from roomkit.models import RetryPolicy
        from roomkit.models.enums import ChannelCategory, HookExecution, HookTrigger

        from roomkit_ui.memory import ensure_room, session_window

        try:
            if reason := text_chat_unavailable(settings):
                raise ValueError(reason)
            provider_name = settings.get("vc_llm_provider", "anthropic")
            prompt = self._compose_session_prompt(settings)  # type: ignore[attr-defined]
            kit, _store = self._build_kit(RoomKit, settings)  # type: ignore[attr-defined]
            self._kit = kit
            toolset, skills = await self._load_vc_tools(settings, provider_name)  # type: ignore[attr-defined]
            # Hangup is a voice action. It must not cut off a written goodbye.
            toolset = type(toolset)(
                builtin=[t for t in toolset.builtin if t["name"] != "end_conversation"],
                cli=toolset.cli,
                mcp=toolset.mcp,
            )
            provider = create_ai_provider(provider_name, settings)
            try:
                ai = AIChannel(
                    "ai",
                    provider=provider,
                    system_prompt=prompt,
                    memory=session_window(datetime.now(UTC)),
                    tool_handler=self._handle_tool_call,  # type: ignore[attr-defined]
                    config_provider=toolset.turn_config(),
                    skills=skills,
                    retry_policy=RetryPolicy(
                        max_retries=2, base_delay_seconds=0.5, max_delay_seconds=4.0
                    ),
                    **reasoning_options(settings, provider_name),
                    **toolset.channel_options(),
                    **tool_search_options(
                        settings, realtime=False, local_model=provider_name in LOCAL_LLMS
                    ),
                )
            except BaseException:
                await provider.close()
                raise
            self._ai_channel = ai
            kit.register_channel(ai)  # kit owns the provider before the next await
            self._ai_pricing = _model_pricing(provider)
            await start_local_llm(provider, self.loading_status.emit)  # type: ignore[attr-defined]
            channel = WebSocketChannel("text")
            kit.register_channel(channel)
            self._channel = channel
            await ensure_room(kit, self._room_id, channels=("text", "ai"))
            await kit.attach_channel(self._room_id, "text")
            await kit.attach_channel(self._room_id, "ai", category=ChannelCategory.INTELLIGENCE)

            @kit.hook(HookTrigger.ON_AI_RESPONSE, HookExecution.ASYNC)
            async def usage(event: Any, _context: Any) -> None:
                if event.usage:
                    self._accumulate_usage(dict(event.usage))  # type: ignore[attr-defined]

            self._text_ready = True
            self._emit_session_info(  # type: ignore[attr-defined]
                provider=provider_name,
                model=provider.model_name,
                mode="text",
                models=[
                    {
                        "role": "Conversation · LLM",
                        "provider": provider_name,
                        "model": provider.model_name,
                        "description": "",
                    }
                ],
                tools=toolset.all,
                skills_registry=skills,
            )
            await self._send_text_turn(text)
        except asyncio.CancelledError:
            raise  # stop() owns the teardown of an unfinished setup
        except Exception as exc:
            logger.warning("Text session setup failed: %s", exc)
            await self._fail_start(  # type: ignore[attr-defined]
                str(exc), missing=exc.feature if isinstance(exc, FeatureUnavailableError) else ""
            )

    async def _send_text_turn(self, text: str) -> None:
        from roomkit.models.delivery import InboundMessage
        from roomkit.models.event import TextContent

        delivery = _TextDelivery(self)
        self._channel.register_connection(
            "desktop",
            delivery.event,
            room_id=self._room_id,
            stream_send_fn=delivery.stream,
        )
        self._enter_active()  # type: ignore[attr-defined]
        try:
            result = await self._kit.process_inbound(
                InboundMessage(
                    channel_id="text", sender_id="user", content=TextContent(body=text)
                ),
                room_id=self._room_id,
            )
            if result.blocked or result.error:
                raise RuntimeError(
                    str(result.error or result.reason or "Message could not be sent.")
                )
            if delivery.error:
                raise RuntimeError(delivery.error)
            if not delivery.received:
                raise RuntimeError("No text response was received. Please try again.")
        except asyncio.CancelledError:
            self._safe_emit(self.text_reply_stopped)  # type: ignore[attr-defined]
            raise
        except Exception as exc:
            self._safe_emit(self.text_reply_stopped)  # type: ignore[attr-defined]
            logger.warning("Text response failed: %s", exc)
            self._safe_emit(self.error_occurred, str(exc))  # type: ignore[attr-defined]
        # Reply completion is not a session teardown: apps may still load or run tools.
        if self.state == EngineState.ACTIVE:  # type: ignore[attr-defined]
            self._set_state(EngineState.READY)  # type: ignore[attr-defined]

    async def cancel_response(self) -> None:
        """Stop only this reply. Keep the thread's tools and apps available."""
        if not self._text_ready:
            await self.stop()  # type: ignore[attr-defined]
            return
        if self.state not in (EngineState.CONNECTING, EngineState.ACTIVE):  # type: ignore[attr-defined]
            return
        self._cancelling_text_response = True
        self._set_state(EngineState.STOPPING)  # type: ignore[attr-defined]
        await self._cancel_start()  # type: ignore[attr-defined]
        # A full stop (window close, for example) can take over while cancelling.
        if self._cancelling_text_response:
            self._cancelling_text_response = False
            self._set_state(EngineState.READY)  # type: ignore[attr-defined]


class _TextDelivery:
    """Separate text segments around tools, ignoring technical room events."""

    def __init__(self, engine: Any) -> None:
        self.engine = engine
        self.generation = engine._session_generation
        self.partial = ""
        self.received = False
        self.error = ""

    def _emit(self, text: str, final: bool) -> None:
        if (
            text
            and self.engine.state == EngineState.ACTIVE
            and self.engine._session_generation == self.generation
        ):
            self.received = True
            self.engine._safe_emit(self.engine.transcription, text, "assistant", final, "")

    async def event(self, _connection: str, event: Any) -> None:
        from roomkit.models.event import TextContent

        if event.source.channel_id == "ai" and isinstance(event.content, TextContent):
            self._emit(event.content.body, True)
            self.partial = ""

    async def stream(self, _connection: str, message: Any) -> None:
        if message.type == "stream_chunk":
            self.partial += message.delta
            self._emit(self.partial, False)
        elif message.type == "stream_end":
            if not message.event.metadata.get("_segmented"):
                self._emit(message.event.content.body, True)
            self.partial = ""
        elif message.type == "stream_error":
            self.error = message.error
