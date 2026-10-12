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
from uuid import uuid4

from PySide6.QtCore import QObject, QTimer, Signal

from roomkit_ui.builtin_tools import BUILTIN_TOOLS
from roomkit_ui.cleanup import cleanup_stale_fds, post_cleanup_monitor, registered_fds
from roomkit_ui.cli_tools import CliToolManager
from roomkit_ui.cli_tools_config import enabled_cli_tools
from roomkit_ui.engine_callbacks import CallbackMixin
from roomkit_ui.engine_realtime import RealtimeMixin
from roomkit_ui.engine_state import EngineState
from roomkit_ui.engine_tools import ToolMixin
from roomkit_ui.engine_vc import VoiceChannelMixin
from roomkit_ui.mcp_config import enabled_mcp_servers
from roomkit_ui.mcp_manager import MCPManager
from roomkit_ui.session_models import SessionModel
from roomkit_ui.skill_approval import SkillApprovals
from roomkit_ui.toolset import ToolSet, reachable_mcp_tools, tool_summaries
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
    # roomkit cut the assistant's voice (barge-in): ms of the reply heard, -1 unknown
    reply_interrupted = Signal(int)
    error_occurred = Signal(str)
    component_missing = Signal(str, str)  # feature key, what the chat says
    tool_started = Signal(object)  # ToolCall
    tool_finished = Signal(object)  # ToolResult, matched by invocation ID
    mcp_status = Signal(str)  # MCP status message
    session_notice = Signal(str)  # non-fatal session info shown in the chat
    loading_status = Signal(str)  # loading progress message
    session_info = Signal(dict)  # {provider, model, tools, failed_servers}
    session_cost = Signal(dict)  # {cost_usd: float|None, input_tokens, output_tokens}
    attitude_changed = Signal(str)  # attitude name (empty string = cleared)
    speaker_named = Signal(str, str)  # voice ("Speaker A"), what it is called now
    skill_approval_requested = Signal(object)  # SkillApproval: may a program run?

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._kit: Any = None
        self._channel: Any = None
        self._ai_channel: Any = None
        self._session: Any = None
        self._transport: Any = None
        self._backend: Any = None  # LocalAudioBackend for voice channel mode
        self._stt: Any = None
        self._tts: Any = None
        self._mcp: MCPManager | None = None
        self._cli: CliToolManager | None = None
        # Questions before a program runs for a skill an MCP server serves.
        self._skill_approvals = SkillApprovals(
            lambda approval: self._safe_emit(self.skill_approval_requested, approval),
            lambda text: self._safe_emit(self.session_notice, text),
        )
        self._mic_muted = False
        self._state = EngineState.IDLE
        self._room_id = f"conversation-{uuid4().hex}"
        self._resume_context = ""
        self._attitude: str = ""  # full description text (injected into prompt)
        self._attitude_name: str = ""  # short display name for the header
        # User's base system prompt (without attitude) — captured at session
        # start so mid-session attitude changes can recompute the full
        # prompt without reaching into channel internals.
        self._base_system_prompt: str = ""
        # Past sessions as the model reads them (memory.memory_recap), between
        # the base prompt and the attitude: an attitude change keeps it.
        self._memory_recap: str = ""
        # The settings the session started with; mid-session lookups read
        # this, never load_settings() and its keyring round-trip.
        self._session_settings: dict = {}
        # Diarization state
        self._diarization: Any = None
        self._primary_speaker_mode: bool = False
        self._primary_speaker_name: str = ""
        # The voices the STT tells apart (Muse); None when it does not.
        self._speakers: Any = None
        # Realtime partial transcription accumulator: Gemini/OpenAI send
        # incremental fragments, but the UI expects full accumulated text.
        self._partial_buffers: dict[str, str] = {}  # role → accumulated text
        # Model cache: persist heavy ONNX models across sessions to avoid
        # reloading STT / TTS / diarization on every conversation start.
        # Maps type → (cache_key_tuple, provider_instance).
        self._cached_models: dict[str, tuple[tuple, Any]] = {}
        self._cleanup_monitor_task: asyncio.Task | None = None
        # FDs the loop watched before the session: the app's own sockets,
        # which the end-of-session FD cleanup must leave alone.
        self._fds_before_session: frozenset[int] = frozenset()
        # The session start in flight, which stop() cancels (see start()).
        self._start_task: asyncio.Task[None] | None = None
        self._end_conv_handle: asyncio.TimerHandle | None = None
        # Tasks explicitly spawned by the engine.  Avoid sweeping
        # asyncio.all_tasks(): UI/settings/dictation tasks may legitimately
        # start while a voice session is active and must not be cancelled by
        # session cleanup.
        self._owned_tasks: set[asyncio.Task[Any]] = set()

        self._pending_tool_calls: int = 0
        # Background tasks the Voice Channel agent started and that have not
        # ended (agent_hooks): the idle hang-up waits for them.
        self._background_tasks: int = 0
        self._watchdog = SessionWatchdog(self)

        # Shared microphone, when one is available: the session subscribes to
        # it instead of taking the device, so speech captured before the
        # session existed can be replayed into it.
        self._capture_source: Any = None
        self._capture_since: Any = None

        # Session usage/cost accounting, both modes.  _ai_pricing is the
        # active LLM's ModelPricing, or None where the offline catalog has no
        # price — every realtime model, whose sessions show tokens only.
        self._ai_pricing: Any = None
        # The Voice Channel agent's parts (speak policy …) and the clients
        # they opened, closed after the kit (vc_agent.VCAgent).
        self._vc_agent: Any = None
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

    def _is_cached_instance(self, model_type: str, provider: Any) -> bool:
        """Whether *provider* is the instance the cache keeps for the next session."""
        entry = self._cached_models.get(model_type)
        if entry is None:
            return False
        cached = entry[1]
        if model_type == "tts":
            cached = cached[0]  # cached with its output sample rate
        return cached is provider

    async def _close_session_models(self) -> None:
        """Close this session's STT and TTS, but never the cached instances.

        The VoiceChannel is built with close_providers=False, so its close()
        leaves STT/TTS alone (avoids a double aclose, e.g. ElevenLabs's httpx
        client hang): the engine closes them.  What the cache holds survives
        for the next session; anything else — a cloud provider, or a local
        one the cache has since replaced — is this session's to close.
        """
        for model_type, provider in (("tts", self._tts), ("stt", self._stt)):
            if provider is None or self._is_cached_instance(model_type, provider):
                continue
            close = getattr(provider, "close", None)
            if close is None:
                continue
            try:
                await close()
            except Exception:
                logger.exception("cleanup: %s.close() failed", model_type)

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
        self._apply_mic_mute(self._session)

    def name_speaker(self, voice: str, name: str) -> None:
        """Put *name* on one of the voices the STT tells apart ("Speaker B");
        an empty name gives it back its label.  No-op outside such a session."""
        from roomkit_ui.speaker_naming import name_voice

        name_voice(self, voice, name)

    def _apply_mic_mute(self, session: Any) -> None:
        """Hold *session*'s microphone to the user's mute.

        Both modes capture through a LocalAudioBackend — the realtime
        transport or the voice channel's backend — and it drops a muted
        session's frames before anything reads them.  A mute pressed while
        connecting has no session to reach yet: each start path applies it
        again as soon as its session exists.
        """
        backend = self._transport or self._backend
        if backend is None or session is None:
            return
        try:
            backend.set_input_muted(session, self._mic_muted)
        except Exception:
            logger.debug("set_input_muted failed", exc_info=True)

    # -- lifecycle dispatcher ------------------------------------------------

    def set_capture_source(self, source: Any) -> None:
        """Use a shared microphone rather than opening the device per session.

        Its lifecycle stays with the caller — the engine only subscribes.
        """
        self._capture_source = source

    async def start(
        self,
        settings: dict,
        capture_since: Any = None,
        *,
        conversation_id: str | None = None,
        resume_context: str = "",
    ) -> None:
        """Open a session.

        Args:
            settings: The configuration snapshot for this session.
            capture_since: Replay mark from the shared source. Set when the
                session was opened by a wake word, so the words already
                spoken reach the provider instead of being lost to the
                handshake.
            conversation_id: Room for this thread; omitted for a fresh one.
            resume_context: Fenced transcript of earlier Live calls in this thread.
        """
        if self._state not in (EngineState.IDLE, EngineState.ERROR):
            return
        self._room_id = conversation_id or f"conversation-{uuid4().hex}"
        self._resume_context = resume_context
        # Claimed before any await: from here a second start() is refused.
        self._set_state(EngineState.CONNECTING)
        self._session_settings = settings
        self._fds_before_session = registered_fds()
        self._capture_since = capture_since
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

        # Its own task, so stop() can cancel it wherever it is waiting.
        task = asyncio.create_task(self._open_session(settings), name="engine_start")
        self._start_task = task
        try:
            await task
        except asyncio.CancelledError:
            if not self._caller_cancelled():
                return  # stop() cancelled the start, and tears it down
            await self.stop()
            raise
        finally:
            self._start_task = None

    async def _open_session(self, settings: dict) -> None:
        mode = settings.get("conversation_mode", "realtime")
        if mode == "voice_channel":
            await self._start_voice_channel(settings)
        else:
            await self._start_realtime(settings)

    @staticmethod
    def _caller_cancelled() -> bool:
        task = asyncio.current_task()
        return task is not None and task.cancelling() > 0

    def _emit_session_info(
        self,
        *,
        provider: str,
        model: str,
        tools: list[dict],
        skills_registry: Any,
        mode: str,
        models: list[SessionModel],
        agent: list[dict] | None = None,
    ) -> None:
        """Tell the UI's session panel what this session runs: models by role,
        tools, skills, the agent's turn-taking, the MCP servers that failed —
        and the attitude."""
        skill_info: list[dict] = []
        if skills_registry and skills_registry.skill_count > 0:
            skill_info = [
                {"name": m.name, "description": m.description}
                for m in skills_registry.all_metadata()
            ]
        info: dict = {
            "provider": provider,
            "model": model,
            "mode": mode,
            "models": models,
            "tools": tool_summaries(tools),
            "skills": skill_info,
        }
        if agent:
            info["agent"] = list(agent)
        if self._mcp and self._mcp.failed_servers:
            info["failed_servers"] = list(self._mcp.failed_servers)
        self.session_info.emit(info)
        if self._attitude_name:
            self.attitude_changed.emit(self._attitude_name)

    def _build_kit(self, kit_cls: type, settings: dict | None) -> tuple[Any, Any]:
        """A RoomKit with the session's telemetry and, when memory is on, its store.

        Returns ``(kit, store)``; ``store`` is None without persistent memory
        (RoomKit then keeps its own in-memory store).
        """
        from roomkit_ui.engine_audio import build_telemetry
        from roomkit_ui.memory import build_store

        telemetry = build_telemetry(settings) if settings else None
        store = build_store(settings) if settings else None
        kit = kit_cls(telemetry=telemetry, store=store) if store else kit_cls(telemetry=telemetry)
        return kit, store

    def _enter_active(self) -> None:
        """Hand the session to the UI — unless stop() took the start over.

        stop() cancels the start task, so the start never gets here; this
        holds if some awaited step swallowed that cancellation.
        """
        if self._state != EngineState.CONNECTING:
            raise asyncio.CancelledError("the session start was stopped")
        self._set_state(EngineState.ACTIVE)

    async def _fail_start(self, message: str, *, missing: str = "") -> None:
        """Tear a failed start down, then report it.

        STOPPING holds through the teardown: nothing — Start, Reset, the wake
        word — can open another session, or run a second teardown, while this
        one's resources are still being released.  ERROR only once they are.
        A start that needed a backend this install lacks (*missing*, a
        feature key) is reported as such: what is missing, not an error.
        """
        self._set_state(EngineState.STOPPING)
        try:
            await self._cleanup()
        except Exception:
            logger.exception("Error during the cleanup of a failed start")
        self._set_state(EngineState.ERROR)
        if missing:
            self.component_missing.emit(missing, message)
        else:
            self.error_occurred.emit(message)

    async def _cancel_start(self) -> None:
        """Cancel a session start still in flight; return once it has unwound."""
        task = self._start_task
        if task is None or task.done() or task is asyncio.current_task():
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def _setup_tools(
        self, settings: dict, *, session_builtins: list[dict] | None = None
    ) -> ToolSet:
        """Connect MCP servers, probe CLI tools, and group both with the built-ins.

        *session_builtins* are built-ins only this session serves (the
        engine handles them), declared before MCP tools claim their names.
        """
        cli_tools = await self._setup_cli_tools(settings)
        mcp_tools = await self._setup_mcp_tools(settings)
        builtin = list(BUILTIN_TOOLS) + list(session_builtins or [])
        # Declared only when a persistent store will actually answer it — a
        # dead tool in the declaration teaches the model to call into a void.
        from roomkit_ui.memory import RECALL_TOOL, memory_active

        if memory_active(settings):
            builtin.append(dict(RECALL_TOOL))
        mcp_tools, dropped = reachable_mcp_tools(builtin, cli_tools, mcp_tools)
        if dropped:
            self.mcp_status.emit(
                f"MCP tools not offered (name taken or invalid): {', '.join(dropped)}"
            )
        return ToolSet(builtin=builtin, cli=cli_tools, mcp=mcp_tools)

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

    async def stop(self) -> None:
        if self._state not in (EngineState.ACTIVE, EngineState.CONNECTING, EngineState.ERROR):
            return
        # Guard re-entrancy immediately — before any await — so a second
        # call (e.g. end_conversation timer + user click) is rejected.
        self._set_state(EngineState.STOPPING)
        # Cancel any pending end_conversation timer to prevent a late fire
        if self._end_conv_handle is not None:
            self._end_conv_handle.cancel()
            self._end_conv_handle = None
        try:
            # A start still connecting is stopped where it waits, and the
            # teardown runs once it has unwound, never alongside it.
            await self._cancel_start()
            await self._cleanup()
        except Exception:
            logger.exception("Error during stop")
        finally:
            self._attitude = ""
            self._attitude_name = ""
            self._log_handler.reset()
            self._set_state(EngineState.IDLE)

    async def _close_unowned_backends(self) -> None:
        """Close the audio backends no kit took over.

        A stop while the session is still being built (MCP servers
        connecting, models loading) lands before the kit exists — and the
        kit's close is what otherwise closes the backend and its AEC.
        """
        for backend in (self._transport, self._backend):
            if backend is None:
                continue
            try:
                await backend.close()
            except Exception:
                logger.exception("cleanup: closing an unowned audio backend failed")

    async def _cleanup(self) -> None:
        """Tear the session down, in the order the fixes below depend on."""
        self._watchdog.stop()
        self._skill_approvals.cancel_all()  # closes a question still open
        self._pending_tool_calls = 0
        self._background_tasks = 0
        self._spk_timer.stop()
        self._spk_rms_queue.clear()
        await self._cancel_cleanup_monitor()
        await self._cancel_owned_tasks()
        await self._end_voice_session()
        await self._close_session_models()
        await self._close_framework()
        await self._close_vc_agent()
        # Remove the voice error log handler to prevent handler accumulation.
        logging.getLogger("roomkit.voice").removeHandler(self._log_handler)
        await self._close_tool_sources()
        # Skip close for cached diarization (extractor survives)
        if self._diarization is not None and "diarization" not in self._cached_models:
            try:
                self._diarization.close()
            except Exception:
                logger.debug("cleanup: diarization close failed", exc_info=True)
        self._forget_session()
        await self._finalize_event_loop()

    async def _cancel_cleanup_monitor(self) -> None:
        """Cancel a post_cleanup_monitor still running from the last session."""
        if self._cleanup_monitor_task is None:
            return
        self._cleanup_monitor_task.cancel()
        try:
            await self._cleanup_monitor_task
        except (asyncio.CancelledError, Exception):
            pass
        self._cleanup_monitor_task = None

    async def _end_voice_session(self) -> None:
        """Stop the mic and end the session: the backend in voice-channel
        mode, the channel in realtime mode."""
        if self._backend and self._session:
            try:
                logger.info("cleanup: disconnecting voice channel backend …")
                await self._backend.stop_listening(self._session)
                await self._backend.disconnect(self._session)
                logger.info("cleanup: backend disconnected")
            except Exception:
                logger.exception("cleanup: backend disconnect failed")
        elif self._channel and self._session and not self._backend:
            try:
                logger.info("cleanup: ending voice session …")
                await self._channel.end_session(self._session)
                logger.info("cleanup: voice session ended")
            except Exception:
                logger.exception("cleanup: end_session failed")

    async def _close_framework(self) -> None:
        """Close roomkit — it cancels in-flight streaming tasks, and
        VoiceChannel.close() closes the backend (close_providers only gates
        STT/TTS).  Without a kit, the backends are closed directly."""
        if not self._kit:
            await self._close_unowned_backends()
            return
        try:
            logger.info("cleanup: closing roomkit …")
            await self._kit.close()
            logger.info("cleanup: roomkit closed")
        except Exception:
            logger.exception("cleanup: kit.close() failed")

    async def _close_vc_agent(self) -> None:
        """Close the speak policy's classifier: roomkit leaves it open, and
        the channel that asked it is closed by now."""
        if self._vc_agent is not None:
            await self._vc_agent.close()

    async def _close_tool_sources(self) -> None:
        """Disconnect the MCP servers and kill any CLI tool still running."""
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

    def _forget_session(self) -> None:
        """Drop every reference the session held.

        ``self._attitude`` is kept across reconnects; stop() clears it when
        the user explicitly ends the session.
        """
        self._channel = None
        self._ai_channel = None
        self._vc_agent = None
        self._session = None
        self._kit = None
        self._transport = None
        self._backend = None
        self._stt = None
        self._tts = None
        self._mcp = None
        self._cli = None
        self._diarization = None
        self._primary_speaker_mode = False
        self._primary_speaker_name = ""
        self._speakers = None
        self._partial_buffers.clear()
        self._base_system_prompt = ""
        self._memory_recap = ""
        self._resume_context = ""

    async def _finalize_event_loop(self) -> None:
        """Let cancelled tasks finish, then clear what MCP/anyio left behind.

        kit.close() cancels VoiceChannel's scheduled tasks, but they need
        event-loop iterations to actually finalize (receive CancelledError).
        Yield first, so cleanup_stale_fds() does not kill the timer handles
        those tasks need — they would stay stuck "cancelling" forever and
        accumulate across sessions.  Only FDs the session registered go: the
        app's own were there before it.
        """
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        keep = self._fds_before_session
        cleanup_stale_fds(keep=keep)
        # The orphaned anyio timers may only appear after the current
        # event-loop iteration completes (they re-create themselves via
        # call_soon).  A delayed second pass catches them without
        # interfering with ongoing task finalization.
        asyncio.get_running_loop().call_later(0.1, lambda: cleanup_stale_fds(keep=keep))
        # Monitor CPU after cleanup to verify the fix worked
        self._cleanup_monitor_task = self._create_owned_task(
            post_cleanup_monitor(),
            name="post_cleanup_monitor",
        )
