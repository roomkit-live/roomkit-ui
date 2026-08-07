"""Async engine wrapping roomkit — emits Qt signals for the UI.

The heavy lifting lives in sibling modules:

* :mod:`roomkit_ui.engine_audio` — pure-function pipeline builders.
* :mod:`roomkit_ui.engine_callbacks` — provider / transport callback mixin.
* :mod:`roomkit_ui.engine_tools` — tool dispatch + attitude + paste mixin.
* :mod:`roomkit_ui.engine_realtime` — Gemini / OpenAI realtime startup mixin.
* :mod:`roomkit_ui.engine_vc` — classic STT → LLM → TTS startup mixin.

This file keeps only the Engine class shell: signals, state, session
dispatcher, teardown, and the roomkit-voice error-log bridge.
"""

from __future__ import annotations

import asyncio
import collections
import logging
import weakref
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal

from roomkit_ui.builtin_tools import BUILTIN_TOOLS
from roomkit_ui.cleanup import cleanup_stale_fds, post_cleanup_monitor
from roomkit_ui.cli_tools import CliToolManager
from roomkit_ui.cli_tools_config import enabled_cli_tools
from roomkit_ui.engine_callbacks import CallbackMixin
from roomkit_ui.engine_realtime import RealtimeMixin
from roomkit_ui.engine_state import EngineState
from roomkit_ui.engine_tools import ToolMixin
from roomkit_ui.engine_vc import VoiceChannelMixin
from roomkit_ui.mcp_config import enabled_mcp_servers
from roomkit_ui.mcp_manager import MCPManager
from roomkit_ui.toolset import ToolSet
from roomkit_ui.watchdog import SessionWatchdog

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Voice error log handler — surfaces roomkit errors in the chat
# ---------------------------------------------------------------------------


class _VoiceErrorLogHandler(logging.Handler):
    """Intercept ERROR logs from roomkit.voice and emit on the engine signal.

    This lets the UI show STT/TTS connection errors (e.g. "insufficient
    credits") that roomkit catches internally and retries silently.
    Debounces repeated identical messages.
    """

    def __init__(self, engine: Engine) -> None:
        super().__init__(level=logging.ERROR)
        self._engine_ref: weakref.ref = weakref.ref(engine)
        self._last_msg = ""

    def reset(self) -> None:
        """Clear the debounce state so the next error is guaranteed to emit.

        Called by ``Engine.stop()`` so errors from a new session aren't
        debounced against stale messages from the previous one.
        """
        self._last_msg = ""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            engine = self._engine_ref()
            if engine is None or engine._state != EngineState.ACTIVE:
                return
            msg = record.getMessage()
            # Extract the root cause from the traceback if present
            if record.exc_info and record.exc_info[1]:
                cause = str(record.exc_info[1])
                # Use the exception message — more user-friendly
                msg = cause
            # Debounce identical messages
            if msg == self._last_msg:
                return
            self._last_msg = msg
            engine.error_occurred.emit(msg)
            # Voice errors (especially TTS WebSocket disconnects) can leave
            # orphaned anyio timer callbacks in qasync → 100% CPU.
            # Schedule a lightweight cleanup (timers only — FDs still needed).
            try:
                loop = asyncio.get_running_loop()
                loop.call_later(0.5, lambda: cleanup_stale_fds(timers_only=True))
            except RuntimeError:
                pass  # no running loop (called from non-main thread)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class Engine(CallbackMixin, ToolMixin, RealtimeMixin, VoiceChannelMixin, QObject):
    """Manages a roomkit voice session and bridges events to Qt signals."""

    state_changed = Signal(str)  # idle / connecting / active / error
    transcription = Signal(str, str, bool, str)  # text, role, is_final, speaker_name
    speaker_identified = Signal(str, float)  # speaker_name, confidence
    mic_audio_level = Signal(float)  # 0.0-1.0
    speaker_audio_level = Signal(float)  # 0.0-1.0
    user_speaking = Signal(bool)
    ai_speaking = Signal(bool)
    error_occurred = Signal(str)
    tool_use = Signal(str, str)  # tool_name, arguments_json
    tool_use_app = Signal(str, str, str, str)  # name, args_json, resource_uri, server_name
    tool_result_app = Signal(str, str)  # name, result_json
    mcp_status = Signal(str)  # MCP status message
    session_notice = Signal(str)  # non-fatal session info shown in the chat
    loading_status = Signal(str)  # loading progress message
    session_info = Signal(dict)  # {provider, model, tools, failed_servers}
    session_cost = Signal(dict)  # {cost_usd: float|None, input_tokens, output_tokens}
    attitude_changed = Signal(str)  # attitude name (empty string = cleared)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._kit: Any = None
        self._channel: Any = None
        self._ai_channel: Any = None
        self._session: Any = None
        self._transport: Any = None
        self._backend: Any = None  # LocalAudioBackend for voice channel mode
        self._tts: Any = None
        self._mcp: MCPManager | None = None
        self._cli: CliToolManager | None = None
        self._mic_muted = False
        self._state = EngineState.IDLE
        self._attitude: str = ""  # full description text (injected into prompt)
        self._attitude_name: str = ""  # short display name for the header
        # User's base system prompt (without attitude) — captured at session
        # start so mid-session attitude changes can recompute the full
        # prompt without reaching into channel internals.
        self._base_system_prompt: str = ""
        # Diarization state
        self._diarization: Any = None
        self._current_speaker_id: str = ""
        self._primary_speaker_mode: bool = False
        self._primary_speaker_name: str = ""
        # Realtime partial transcription accumulator: Gemini/OpenAI send
        # incremental fragments, but the UI expects full accumulated text.
        self._partial_buffers: dict[str, str] = {}  # role → accumulated text
        self._partial_speakers: dict[str, str] = {}  # role → best speaker ID this utterance
        # Duplicate-final guard: xAI's realtime server can emit the
        # input-transcription-completed event twice for one utterance.
        self._last_finals: dict[str, tuple[str, float]] = {}  # role → (text, monotonic)
        # xAI streaming-final debounce (see hooks._debounce_user_final):
        # the active realtime provider name gates it, the handle/pending
        # pair carries the held user final.
        self._realtime_provider_name: str = ""
        self._xai_final_handle: asyncio.TimerHandle | None = None
        self._xai_pending_final: tuple[str, str] | None = None
        # Model cache: persist heavy ONNX models across sessions to avoid
        # reloading STT / TTS / diarization on every conversation start.
        # Maps type → (cache_key_tuple, provider_instance).
        self._cached_models: dict[str, tuple[tuple, Any]] = {}
        self._cleanup_monitor_task: asyncio.Task | None = None
        self._end_conv_handle: asyncio.TimerHandle | None = None
        # Tasks explicitly spawned by the engine.  Avoid sweeping
        # asyncio.all_tasks(): UI/settings/dictation tasks may legitimately
        # start while a voice session is active and must not be cancelled by
        # session cleanup.
        self._owned_tasks: set[asyncio.Task[Any]] = set()

        self._pending_tool_calls: int = 0
        self._watchdog = SessionWatchdog(self)

        # Session usage/cost accounting (VC mode — realtime APIs report no
        # usage through roomkit).  _ai_pricing is the active LLM's
        # ModelPricing, or None for models the offline catalog doesn't carry.
        self._ai_pricing: Any = None
        self._usage_cost: float = 0.0
        self._usage_in: int = 0
        self._usage_out: int = 0

        # Log handler to surface roomkit voice errors in the UI
        self._log_handler = _VoiceErrorLogHandler(self)
        logging.getLogger("roomkit.voice").addHandler(self._log_handler)

        # Speaker RMS queue: audio arrives in bursts from the provider but
        # plays back at a steady 20 ms cadence.  We split incoming chunks
        # into block-sized RMS values and drain them with a timer that
        # matches the real playback rate.
        self._spk_rms_queue: collections.deque[float] = collections.deque(maxlen=200)
        self._spk_timer = QTimer(self)
        self._spk_timer.setInterval(20)  # one playback block
        self._spk_timer.timeout.connect(self._drain_speaker_level)

    # -- model cache ---------------------------------------------------------

    def _get_cached(self, model_type: str, cache_key: tuple) -> Any | None:
        """Return a cached provider if the key matches, else None."""
        entry = self._cached_models.get(model_type)
        if entry is not None and entry[0] == cache_key:
            return entry[1]
        return None

    def _set_cached(self, model_type: str, cache_key: tuple, provider: Any) -> None:
        self._cached_models[model_type] = (cache_key, provider)

    def clear_model_cache(self) -> None:
        """Release all cached models (call on app quit)."""
        self._cached_models.clear()

    def _create_owned_task(
        self,
        coro: Any,
        *,
        name: str | None = None,
    ) -> asyncio.Task[Any]:
        """Create an asyncio task owned by the engine lifecycle."""
        task = asyncio.create_task(coro, name=name)
        self._owned_tasks.add(task)
        task.add_done_callback(self._owned_tasks.discard)
        return task

    async def _cancel_owned_tasks(self) -> None:
        """Cancel engine-owned background tasks without touching unrelated tasks."""
        current = asyncio.current_task()
        tasks = [task for task in self._owned_tasks if task is not current and not task.done()]
        if not tasks:
            return
        for task in tasks:
            logger.info("cleanup: cancelling owned task: %s", task.get_name() or task)
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    @property
    def state(self) -> EngineState:
        return self._state

    def _set_state(self, state: EngineState) -> None:
        """Assign the session state and notify the UI."""
        self._state = state
        self.state_changed.emit(state)

    def set_mic_muted(self, muted: bool) -> None:
        self._mic_muted = muted
        if self._transport is not None and self._session is not None:
            try:
                self._transport.set_input_muted(self._session, muted)
            except Exception:
                pass
        # Voice channel mode uses LocalAudioBackend (no set_input_muted)

    # -- lifecycle dispatcher ------------------------------------------------

    async def start(self, settings: dict) -> None:
        if self._state not in (EngineState.IDLE, EngineState.ERROR):
            return
        self._mic_muted = False
        # Re-attach the log handler (removed during cleanup)
        voice_logger = logging.getLogger("roomkit.voice")
        if self._log_handler not in voice_logger.handlers:
            self._log_handler._engine_ref = weakref.ref(self)
            voice_logger.addHandler(self._log_handler)

        self._ai_pricing = None
        self._usage_cost = 0.0
        self._usage_in = 0
        self._usage_out = 0

        mode = settings.get("conversation_mode", "realtime")
        if mode == "voice_channel":
            await self._start_voice_channel(settings)
        else:
            await self._start_realtime(settings)

    async def _setup_tools(self, settings: dict) -> ToolSet:
        """Connect MCP servers, probe CLI tools, and group both with the built-ins."""
        cli_tools = await self._setup_cli_tools(settings)
        mcp_tools = await self._setup_mcp_tools(settings)
        self._warn_shadowed_mcp_tools(cli_tools, mcp_tools)
        return ToolSet(builtin=list(BUILTIN_TOOLS), cli=cli_tools, mcp=mcp_tools)

    async def _setup_cli_tools(self, settings: dict) -> list[dict]:
        """Build tools for each declared CLI binary."""
        declared = enabled_cli_tools(settings.get("cli_tools", "[]"))
        if not declared:
            return []
        self.loading_status.emit("Reading CLI tools…")
        self._cli = CliToolManager(declared)
        await self._cli.probe_all()
        if self._cli.failed_tools:
            # A declared tool that never reaches the model must say so — a log
            # line alone reads as "it worked" from the chat.
            failed = ", ".join(self._cli.failed_tools)
            self.mcp_status.emit(f"CLI tools unavailable: {failed}")
        return self._cli.get_tools()

    async def _setup_mcp_tools(self, settings: dict) -> list[dict]:
        """Connect MCP servers and return the tools they expose."""
        mcp_servers = enabled_mcp_servers(settings.get("mcp_servers", "[]"))
        if not mcp_servers:
            return []

        self._mcp = MCPManager(mcp_servers)
        await self._mcp.connect_all()
        discovered = self._mcp.get_tools()

        if self._mcp.failed_servers:
            failed = ", ".join(self._mcp.failed_servers)
            self.mcp_status.emit(f"MCP failed: {failed}")

        if discovered:
            names = ", ".join(t["name"] for t in discovered)
            logger.info("MCP tools: %s", names)

        # MCP connection failures (especially aborts) leak anyio
        # CancelScope timers that spin at 0ms → 100% CPU.
        # Clean immediately + delayed pass for timers that re-create
        # themselves via call_soon.
        cleanup_stale_fds(timers_only=True)
        asyncio.get_running_loop().call_later(0.5, lambda: cleanup_stale_fds(timers_only=True))

        return discovered

    @staticmethod
    def _warn_shadowed_mcp_tools(cli_tools: list[dict], mcp_tools: list[dict]) -> None:
        """Log MCP tools a CLI tool hides — dispatch tries CLI first."""
        cli_names = {t["name"] for t in cli_tools}
        shadowed = [t["name"] for t in mcp_tools if t["name"] in cli_names]
        if shadowed:
            logger.warning("CLI tools shadow same-named MCP tools: %s", ", ".join(shadowed))

    async def stop(self) -> None:
        if self._state not in (EngineState.ACTIVE, EngineState.CONNECTING, EngineState.ERROR):
            return
        # Guard re-entrancy immediately — before any await — so a second
        # call (e.g. end_conversation timer + user click) is rejected.
        self._state = EngineState.STOPPING
        # Cancel any pending end_conversation timer to prevent a late fire
        if self._end_conv_handle is not None:
            self._end_conv_handle.cancel()
            self._end_conv_handle = None
        try:
            await self._cleanup()
        except Exception:
            logger.exception("Error during stop")
        finally:
            self._attitude = ""
            self._attitude_name = ""
            self._log_handler.reset()
            self._set_state(EngineState.IDLE)

    async def _cleanup(self) -> None:
        self._watchdog.stop()
        self._pending_tool_calls = 0
        self._spk_timer.stop()
        self._spk_rms_queue.clear()
        # Cancel any lingering post_cleanup_monitor from previous session
        if self._cleanup_monitor_task is not None:
            self._cleanup_monitor_task.cancel()
            try:
                await self._cleanup_monitor_task
            except (asyncio.CancelledError, Exception):
                pass
            self._cleanup_monitor_task = None
        await self._cancel_owned_tasks()
        # Voice channel mode: disconnect backend
        if self._backend and self._session:
            try:
                logger.info("cleanup: disconnecting voice channel backend …")
                await self._backend.stop_listening(self._session)
                await self._backend.disconnect(self._session)
                logger.info("cleanup: backend disconnected")
            except Exception:
                logger.exception("cleanup: backend disconnect failed")
        # Realtime mode: end session via channel
        elif self._channel and self._session and not self._backend:
            try:
                logger.info("cleanup: ending voice session …")
                await self._channel.end_session(self._session)
                logger.info("cleanup: voice session ended")
            except Exception:
                logger.exception("cleanup: end_session failed")
        # Close TTS ourselves — the channel was built with close_providers=False
        # so VoiceChannel.close() won't touch STT/TTS (avoids a double aclose,
        # e.g. ElevenLabs's httpx client hang).  Skip close for cached TTS
        # (model survives for the next session).
        if (
            self._tts is not None
            and hasattr(self._tts, "close")
            and "tts" not in self._cached_models
        ):
            try:
                await self._tts.close()
            except Exception:
                logger.exception("cleanup: tts.close() failed")
        # Close roomkit — cancels in-flight streaming tasks; VoiceChannel.close()
        # closes the backend (close_providers only gates STT/TTS).
        if self._kit:
            try:
                logger.info("cleanup: closing roomkit …")
                await self._kit.close()
                logger.info("cleanup: roomkit closed")
            except Exception:
                logger.exception("cleanup: kit.close() failed")
        # Remove the voice error log handler to prevent handler accumulation.
        logging.getLogger("roomkit.voice").removeHandler(self._log_handler)
        if self._mcp:
            try:
                logger.info("cleanup: closing MCP …")
                await self._mcp.close_all()
                logger.info("cleanup: MCP closed")
            except Exception:
                logger.exception("cleanup: mcp.close_all() failed")
        if self._cli:
            # closeEvent fires stop() without awaiting it, so a child mid-call
            # would otherwise outlive the app.
            try:
                self._cli.terminate_all()
            except Exception:
                logger.exception("cleanup: cli.terminate_all() failed")
        # Skip close for cached diarization (extractor survives)
        if self._diarization is not None and "diarization" not in self._cached_models:
            try:
                self._diarization.close()
            except Exception:
                pass
        self._channel = None
        self._ai_channel = None
        self._session = None
        self._kit = None
        self._transport = None
        self._backend = None
        self._tts = None
        self._mcp = None
        self._cli = None
        self._diarization = None
        self._current_speaker_id = ""
        self._primary_speaker_mode = False
        self._primary_speaker_name = ""
        self._partial_buffers.clear()
        self._partial_speakers.clear()
        self._last_finals.clear()
        if self._xai_final_handle is not None:
            self._xai_final_handle.cancel()
            self._xai_final_handle = None
        self._xai_pending_final = None
        self._realtime_provider_name = ""
        self._base_system_prompt = ""
        # Note: self._attitude is preserved across reconnects and only
        # cleared in stop() when the user explicitly ends the session.

        # --- Task finalization ---
        # kit.close() cancels VoiceChannel's scheduled tasks, but they
        # need event-loop iterations to actually finalize (receive
        # CancelledError).  Yield here so they can complete before we
        # run cleanup_stale_fds() — otherwise cleanup kills the timer
        # handles those tasks need, leaving them stuck in "cancelling"
        # state forever and accumulating across sessions.
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        # Now safe to clean up stale event-loop state left by MCP/anyio.
        cleanup_stale_fds()
        # The orphaned anyio timers may only appear after the current
        # event-loop iteration completes (they re-create themselves via
        # call_soon).  Schedule a delayed second pass to catch them
        # without interfering with ongoing task finalization.
        asyncio.get_running_loop().call_later(0.1, cleanup_stale_fds)
        # Monitor CPU after cleanup to verify the fix worked
        self._cleanup_monitor_task = self._create_owned_task(
            post_cleanup_monitor(),
            name="post_cleanup_monitor",
        )
