"""Async engine wrapping roomkit — emits Qt signals for the UI."""

from __future__ import annotations

import asyncio
import collections
import datetime
import json
import logging
import math
import os
import resource
import struct
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal

from room_ui.mcp_manager import MCPManager

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Audio helpers
# ---------------------------------------------------------------------------

# 24 kHz, 16-bit mono → 960 bytes per 20 ms block
_BLOCK_BYTES = 960


def _compute_rms(data: bytes) -> float:
    """Return RMS level 0.0-1.0 from 16-bit PCM audio bytes.

    Uses a square-root curve so quiet mic signals are still clearly visible
    on the VU meter while loud signals don't clip too aggressively.
    """
    if len(data) < 2:
        return 0.0
    n = len(data) // 2
    samples = struct.unpack(f"<{n}h", data)
    rms = math.sqrt(sum(s * s for s in samples) / n) / 32768.0
    # sqrt curve: quiet speech (~0.03) → 0.55, loud speech (~0.15) → 1.0
    return min(1.0, math.sqrt(rms) * 3.2)


# ---------------------------------------------------------------------------
# Built-in tools (always available)
# ---------------------------------------------------------------------------

_BUILTIN_TOOLS = [
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


def _handle_builtin_tool(name: str) -> str | None:
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


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class Engine(QObject):
    """Manages a roomkit voice session and bridges events to Qt signals."""

    state_changed = Signal(str)  # idle / connecting / active / error
    transcription = Signal(str, str, bool)  # text, role, is_final
    mic_audio_level = Signal(float)  # 0.0-1.0
    speaker_audio_level = Signal(float)  # 0.0-1.0
    user_speaking = Signal(bool)
    ai_speaking = Signal(bool)
    error_occurred = Signal(str)
    tool_use = Signal(str, str)  # tool_name, arguments_json
    mcp_status = Signal(str)  # status message
    session_info = Signal(dict)  # {provider, model, tools, failed_servers}

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._kit: Any = None
        self._channel: Any = None
        self._session: Any = None
        self._transport: Any = None
        self._mcp: MCPManager | None = None
        self._mic_muted = False
        self._state = "idle"

        # Speaker RMS queue: audio arrives in bursts from the provider but
        # plays back at a steady 20 ms cadence.  We split incoming chunks
        # into block-sized RMS values and drain them with a timer that
        # matches the real playback rate.
        self._spk_rms_queue: collections.deque[float] = collections.deque()
        self._spk_timer = QTimer(self)
        self._spk_timer.setInterval(20)  # one playback block
        self._spk_timer.timeout.connect(self._drain_speaker_level)

    @property
    def state(self) -> str:
        return self._state

    def set_mic_muted(self, muted: bool) -> None:
        self._mic_muted = muted
        if self._transport is not None and self._session is not None:
            try:
                self._transport.set_input_muted(self._session, muted)
            except Exception:
                pass

    # -- register our own callbacks (roomkit uses append-based lists) --------

    def _register_callbacks(self, provider: Any, transport: Any) -> None:
        provider.on_transcription(self._on_transcription)
        provider.on_audio(self._on_speaker_audio)
        provider.on_speech_start(self._on_speech_start)
        provider.on_speech_end(self._on_speech_end)
        provider.on_response_start(self._on_response_start)
        provider.on_response_end(self._on_response_end)
        provider.on_error(self._on_provider_error)
        transport.on_audio_received(self._on_mic_audio)

    # -- callbacks -----------------------------------------------------------

    def _on_transcription(self, _s: Any, text: str, role: str, is_final: bool) -> None:
        try:
            self.transcription.emit(str(text), str(role), bool(is_final))
        except Exception:
            pass

    def _on_speaker_audio(self, _s: Any, audio: bytes) -> None:
        """Split provider audio into block-sized RMS values and queue them."""
        try:
            offset = 0
            while offset + _BLOCK_BYTES <= len(audio):
                block = audio[offset : offset + _BLOCK_BYTES]
                self._spk_rms_queue.append(_compute_rms(block))
                offset += _BLOCK_BYTES
            if offset < len(audio):
                self._spk_rms_queue.append(_compute_rms(audio[offset:]))
        except Exception:
            pass

    def _drain_speaker_level(self) -> None:
        """Pop one RMS value per timer tick → matches real playback cadence."""
        if self._spk_rms_queue:
            self.speaker_audio_level.emit(self._spk_rms_queue.popleft())

    def _on_mic_audio(self, _s: Any, audio: bytes) -> None:
        try:
            if self._mic_muted:
                self.mic_audio_level.emit(0.0)
            else:
                self.mic_audio_level.emit(_compute_rms(audio))
        except Exception:
            pass

    def _on_speech_start(self, _s: Any) -> None:
        try:
            self.user_speaking.emit(True)
        except Exception:
            pass

    def _on_speech_end(self, _s: Any) -> None:
        try:
            self.user_speaking.emit(False)
        except Exception:
            pass

    def _on_response_start(self, _s: Any) -> None:
        try:
            self.ai_speaking.emit(True)
        except Exception:
            pass

    def _on_response_end(self, _s: Any) -> None:
        try:
            self.ai_speaking.emit(False)
        except Exception:
            pass

    def _on_provider_error(self, _s: Any, code: str, message: str) -> None:
        try:
            self.error_occurred.emit(f"{code}: {message}")
        except Exception:
            pass

    # -- tool calls ----------------------------------------------------------

    async def _handle_tool_call(
        self,
        session: Any,
        name: str,
        arguments: dict[str, Any],
    ) -> str:
        """Handle built-in tools or forward to MCP manager."""
        try:
            self.tool_use.emit(name, json.dumps(arguments))
        except Exception:
            pass

        # Try built-in tools first
        builtin_result = _handle_builtin_tool(name)
        if builtin_result is not None:
            return builtin_result

        if self._mcp is None:
            return '{"error": "Unknown tool"}'
        result = await self._mcp.handle_tool_call(session, name, arguments)
        # MCP/anyio can leak orphaned timer callbacks under qasync when a
        # tool call fails or the server crashes.  Run a lightweight cleanup
        # after every MCP call to prevent 100% CPU spin loops.
        self._cleanup_stale_fds()
        return result

    # -- lifecycle -----------------------------------------------------------

    async def start(self, settings: dict) -> None:
        if self._state not in ("idle", "error"):
            return
        self._mic_muted = False

        self._state = "connecting"
        self.state_changed.emit("connecting")

        try:
            provider_name = settings.get("provider", "gemini")
            system_prompt = settings.get(
                "system_prompt",
                "You are a friendly voice assistant. Be concise and helpful.",
            )
            aec_mode = settings.get("aec_mode", "webrtc")
            denoise_mode = settings.get("denoise", "none")

            from roomkit import RealtimeVoiceChannel, RoomKit
            from roomkit.voice.realtime.local_transport import LocalAudioTransport

            provider: Any
            if provider_name == "openai":
                api_key = settings.get("openai_api_key", "")
                if not api_key:
                    raise ValueError("OpenAI API key is required. Open Settings to enter it.")
                model = settings.get("openai_model", "gpt-4o-realtime-preview")
                voice = settings.get("openai_voice", "alloy")
                from roomkit.providers.openai.realtime import OpenAIRealtimeProvider

                provider = OpenAIRealtimeProvider(api_key=api_key, model=model)
            else:
                api_key = settings.get("api_key", "")
                if not api_key:
                    raise ValueError("Google API key is required. Open Settings to enter it.")
                model = settings.get("model", "gemini-2.5-flash-native-audio-preview-12-2025")
                voice = settings.get("voice", "Aoede")
                from roomkit.providers.gemini.realtime import GeminiLiveProvider

                provider = GeminiLiveProvider(api_key=api_key, model=model)

            sample_rate = 24000
            block_ms = 20
            frame_size = sample_rate * block_ms // 1000

            aec: Any = None
            if aec_mode in ("webrtc", "1"):
                try:
                    from roomkit.voice.pipeline.aec.webrtc import WebRTCAECProvider

                    aec = WebRTCAECProvider(sample_rate=sample_rate)
                except ImportError:
                    logger.warning("WebRTC AEC not available — install aec-audio-processing")
            elif aec_mode == "speex":
                try:
                    from roomkit.voice.pipeline.aec.speex import SpeexAECProvider

                    aec = SpeexAECProvider(
                        frame_size=frame_size,
                        filter_length=frame_size * 10,
                        sample_rate=sample_rate,
                    )
                except ImportError:
                    logger.warning("Speex AEC not available — install libspeexdsp")

            denoiser: Any = None
            if denoise_mode == "rnnoise":
                try:
                    from roomkit.voice.pipeline.denoiser.rnnoise import RNNoiseDenoiserProvider

                    denoiser = RNNoiseDenoiserProvider(sample_rate=sample_rate)
                except ImportError:
                    logger.warning("RNNoise denoiser not available")
            elif denoise_mode == "gtcrn":
                from room_ui.model_manager import gtcrn_model_path, is_gtcrn_downloaded

                if is_gtcrn_downloaded():
                    from roomkit.voice.pipeline.denoiser.sherpa_onnx import (
                        SherpaOnnxDenoiserConfig,
                        SherpaOnnxDenoiserProvider,
                    )

                    denoiser = SherpaOnnxDenoiserProvider(
                        SherpaOnnxDenoiserConfig(model=str(gtcrn_model_path()))
                    )
                else:
                    logger.warning("GTCRN model not downloaded — denoiser disabled")

            mute_mic = aec is None

            input_device = settings.get("input_device")
            output_device = settings.get("output_device")

            transport = LocalAudioTransport(
                input_sample_rate=sample_rate,
                output_sample_rate=sample_rate,
                block_duration_ms=block_ms,
                mute_mic_during_playback=mute_mic,
                aec=aec,
                denoiser=denoiser,
                input_device=input_device,
                output_device=output_device,
            )

            self._transport = transport

            # Log audio pipeline configuration
            aec_label = type(aec).__name__ if aec else "none"
            denoise_label = type(denoiser).__name__ if denoiser else "none"
            logger.info(
                "Audio pipeline: aec=%s, denoiser=%s, rate=%dHz, block=%dms",
                aec_label,
                denoise_label,
                sample_rate,
                block_ms,
            )

            self._register_callbacks(provider, transport)

            # -- MCP tools -------------------------------------------------------
            mcp_servers: list[dict] = []
            try:
                mcp_servers = [
                    s
                    for s in json.loads(settings.get("mcp_servers", "[]"))
                    if s.get("enabled", True)
                ]
            except (json.JSONDecodeError, TypeError):
                pass

            # Always start with built-in tools
            tools: list[dict] = list(_BUILTIN_TOOLS)
            tool_handler = self._handle_tool_call

            if mcp_servers:
                self._mcp = MCPManager(mcp_servers)
                await self._mcp.connect_all()
                discovered = self._mcp.get_tools()

                if self._mcp.failed_servers:
                    failed = ", ".join(self._mcp.failed_servers)
                    self.mcp_status.emit(f"MCP failed: {failed}")

                if discovered:
                    tools.extend(discovered)
                    names = ", ".join(t["name"] for t in discovered)
                    logger.info("MCP tools: %s", names)

            all_names = ", ".join(t["name"] for t in tools)
            logger.info("Tools: %s", all_names)

            has_mcp_tools = len(tools) > len(_BUILTIN_TOOLS)

            self._session = await self._start_session(
                RoomKit,
                RealtimeVoiceChannel,
                provider,
                transport,
                system_prompt,
                voice,
                sample_rate,
                tools,
                tool_handler,
            )
            if self._session is None and has_mcp_tools:
                # MCP tools broke the session — retry without them
                logger.warning("Retrying session without MCP tools")
                self._session = await self._start_session(
                    RoomKit,
                    RealtimeVoiceChannel,
                    provider,
                    transport,
                    system_prompt,
                    voice,
                    sample_rate,
                    list(_BUILTIN_TOOLS),
                    tool_handler,
                )
                if self._session is not None:
                    self.mcp_status.emit("MCP tools disabled — incompatible with this provider")
                    tools = list(_BUILTIN_TOOLS)

            if self._session is None:
                raise RuntimeError("Failed to start voice session")

            self._spk_rms_queue.clear()
            self._spk_timer.start()

            self._state = "active"
            self.state_changed.emit("active")

            # Emit structured session info for the UI info bar
            tool_info = [
                {"name": t.get("name", ""), "description": t.get("description", "")} for t in tools
            ]
            info: dict = {
                "provider": provider_name,
                "model": model,
                "tools": tool_info,
            }
            if self._mcp and self._mcp.failed_servers:
                info["failed_servers"] = list(self._mcp.failed_servers)
            self.session_info.emit(info)

        except Exception as e:
            logger.exception("Failed to start voice session")
            self._state = "error"
            self.state_changed.emit("error")
            self.error_occurred.emit(str(e))
            await self._cleanup()

    async def _start_session(
        self,
        RoomKit: type,  # noqa: N803
        RealtimeVoiceChannel: type,  # noqa: N803
        provider: Any,
        transport: Any,
        system_prompt: str,
        voice: str,
        sample_rate: int,
        tools: list[dict],
        tool_handler: Any,
    ) -> Any:
        """Try to create a room and start a session. Returns None on failure."""
        try:
            self._kit = RoomKit()
            self._channel = RealtimeVoiceChannel(
                "voice",
                provider=provider,
                transport=transport,
                system_prompt=system_prompt,
                voice=voice,
                input_sample_rate=sample_rate,
                tools=tools,
                tool_handler=tool_handler,
            )
            self._kit.register_channel(self._channel)
            await self._kit.create_room(room_id="local-demo")
            await self._kit.attach_channel("local-demo", "voice")
            return await self._channel.start_session(
                "local-demo",
                "local-user",
                connection=None,
            )
        except Exception:
            logger.exception("_start_session failed")
            try:
                await self._kit.close()
            except Exception:
                pass
            self._kit = None
            self._channel = None
            return None

    async def stop(self) -> None:
        if self._state not in ("active", "connecting", "error"):
            return
        try:
            await self._cleanup()
        except Exception:
            logger.exception("Error during stop")
        finally:
            self._state = "idle"
            self.state_changed.emit("idle")

    async def _cleanup(self) -> None:
        self._spk_timer.stop()
        self._spk_rms_queue.clear()
        if self._channel and self._session:
            try:
                logger.info("cleanup: ending voice session …")
                await self._channel.end_session(self._session)
                logger.info("cleanup: voice session ended")
            except Exception:
                logger.exception("cleanup: end_session failed")
        if self._kit:
            try:
                logger.info("cleanup: closing roomkit …")
                await self._kit.close()
                logger.info("cleanup: roomkit closed")
            except Exception:
                logger.exception("cleanup: kit.close() failed")
        if self._mcp:
            try:
                logger.info("cleanup: closing MCP …")
                await self._mcp.close_all()
                logger.info("cleanup: MCP closed")
            except Exception:
                logger.exception("cleanup: mcp.close_all() failed")
        self._channel = None
        self._session = None
        self._kit = None
        self._transport = None
        self._mcp = None
        # Clean up stale event-loop state left by MCP/anyio.
        self._cleanup_stale_fds()
        # The orphaned anyio timers may only appear after the current
        # event-loop iteration completes (they re-create themselves via
        # call_soon).  Schedule a second pass to catch them.
        asyncio.get_event_loop().call_soon(self._cleanup_stale_fds)
        # Monitor CPU after cleanup to verify the fix worked
        asyncio.ensure_future(self._post_cleanup_monitor())

    @staticmethod
    def _cleanup_stale_fds() -> None:
        """Purge all qasync event-loop state that MCP/anyio may have leaked.

        qasync has TWO notifier layers that can hold stale FDs:
        1. _QEventLoop._read_notifiers / _write_notifiers  (from _add_reader)
        2. _Selector.__read_notifiers / __write_notifiers   (from register)
        Layer 2 is especially dangerous because its notifier callbacks do NOT
        disable the notifier before invoking the callback, causing a tight
        busy-loop if the FD is always-ready.

        We also purge cancelled timer callbacks and stale asyncio handles.
        """
        loop = asyncio.get_event_loop()
        self_pipe_fd = getattr(getattr(loop, "_ssock", None), "fileno", lambda: -1)()

        removed = 0

        # --- Layer 1: _QEventLoop notifiers (_add_reader / _add_writer) ---
        for attr in ("_read_notifiers", "_write_notifiers"):
            notifiers: dict | None = getattr(loop, attr, None)
            if not notifiers:
                continue
            for fd in list(notifiers):
                if fd == self_pipe_fd:
                    continue
                try:
                    target = os.readlink(f"/proc/self/fd/{fd}")
                except OSError:
                    target = "?"
                logger.warning("cleanup L1: removing %s FD %d → %s", attr, fd, target)
                notifier = notifiers.pop(fd, None)
                if notifier is not None:
                    notifier.setEnabled(False)
                removed += 1

        # --- Layer 2: _Selector notifiers (register / unregister) ---------
        selector = getattr(loop, "_selector", None)
        if selector is not None:
            fd_to_key: dict = getattr(selector, "_fd_to_key", {})
            for mangled in (
                "_Selector__read_notifiers",
                "_Selector__write_notifiers",
            ):
                sel_notifiers: dict | None = getattr(selector, mangled, None)
                if not sel_notifiers:
                    continue
                for fd in list(sel_notifiers):
                    if fd == self_pipe_fd:
                        continue
                    logger.warning("cleanup L2: removing %s FD %d", mangled, fd)
                    notifier = sel_notifiers.pop(fd, None)
                    if notifier is not None:
                        notifier.setEnabled(False)
                    removed += 1
            # Clean corresponding selector keys (skip self-pipe)
            for fd in list(fd_to_key):
                if fd == self_pipe_fd:
                    continue
                logger.warning("cleanup L2: removing selector key FD %d", fd)
                del fd_to_key[fd]
                removed += 1

        # --- Layer 3: orphaned timer callbacks in _SimpleTimer -------------
        # After MCP/anyio cleanup, two non-cancelled callbacks can get stuck
        # in an infinite 0 ms timer loop:
        #   - CancelScope._deliver_cancellation()  (anyio cancel retry)
        #   - Task.task_wakeup()  (waking an orphaned task)
        # We kill cancelled timers AND these orphaned active ones.
        timer = getattr(loop, "_timer", None)
        if timer is not None:
            cbs: dict = getattr(timer, "_SimpleTimer__callbacks", {})
            live_tasks = asyncio.all_tasks(loop)
            kill_tids: list[int] = []
            for tid, handle in list(cbs.items()):
                if getattr(handle, "_cancelled", False):
                    kill_tids.append(tid)
                    continue
                # Inspect the callback to detect orphaned anyio/task handles
                cb = getattr(handle, "_callback", None)
                cb_self = getattr(cb, "__self__", None)
                if cb_self is None:
                    continue
                # anyio CancelScope stuck in a cancel-delivery retry loop
                if type(cb_self).__name__ == "CancelScope":
                    logger.warning(
                        "cleanup L3: killing orphaned CancelScope timer %s",
                        tid,
                    )
                    handle.cancel()
                    kill_tids.append(tid)
                    continue
                # Task.task_wakeup for a task no longer tracked by asyncio
                if isinstance(cb_self, asyncio.Task) and cb_self not in live_tasks:
                    logger.warning(
                        "cleanup L3: killing orphaned task timer %s → %s",
                        tid,
                        cb_self,
                    )
                    handle.cancel()
                    kill_tids.append(tid)
            for tid in kill_tids:
                timer.killTimer(tid)
                del cbs[tid]
                removed += 1
            if kill_tids:
                logger.info("cleanup L3: killed %d timers", len(kill_tids))

        # --- Layer 4: purge cancelled handles from asyncio _ready queue ---
        ready = getattr(loop, "_ready", None)
        if ready is not None:
            before = len(ready)
            active = [h for h in ready if not h._cancelled]
            ready.clear()
            ready.extend(active)
            dropped = before - len(active)
            if dropped:
                logger.info("cleanup L4: dropped %d cancelled handles", dropped)
                removed += dropped

        # --- Summary -----------------------------------------------------
        r_count = len(getattr(loop, "_read_notifiers", {}) or {})
        w_count = len(getattr(loop, "_write_notifiers", {}) or {})
        tasks = [t for t in asyncio.all_tasks(loop) if not t.done()]
        logger.info(
            "cleanup: removed %d items, %d read + %d write notifiers remain "
            "(self-pipe=%d), %d live tasks",
            removed,
            r_count,
            w_count,
            self_pipe_fd,
            len(tasks),
        )
        for t in tasks:
            logger.info("cleanup: live task: %s", t)

    @staticmethod
    async def _post_cleanup_monitor() -> None:
        """Log CPU usage after cleanup to verify the fix worked."""
        loop = asyncio.get_event_loop()
        t0 = resource.getrusage(resource.RUSAGE_SELF)
        for i in range(3):
            await asyncio.sleep(3)
            t1 = resource.getrusage(resource.RUSAGE_SELF)
            cpu = (t1.ru_utime - t0.ru_utime) + (t1.ru_stime - t0.ru_stime)
            logger.info(
                "cpu-monitor[%d]: %.2fs CPU in 3s",
                i,
                cpu,
            )
            if cpu > 1.0:
                # Dump everything that could be spinning
                timer = getattr(loop, "_timer", None)
                if timer is not None:
                    cbs = getattr(timer, "_SimpleTimer__callbacks", {})
                    logger.warning("cpu-monitor: %d timer callbacks", len(cbs))
                    for tid_k, handle in list(cbs.items())[:5]:
                        logger.warning(
                            "  timer %s → %s (cancelled=%s)", tid_k, handle, handle._cancelled
                        )

                ready = getattr(loop, "_ready", None)
                if ready is not None:
                    logger.warning("cpu-monitor: %d _ready items", len(ready))
                    for h in list(ready)[:5]:
                        logger.warning("  ready → %s (cancelled=%s)", h, h._cancelled)

                # Layer 1 notifiers
                for attr in ("_read_notifiers", "_write_notifiers"):
                    notifiers = getattr(loop, attr, {})
                    for fd, notifier in list(notifiers.items()):
                        logger.warning(
                            "  L1 %s FD %d enabled=%s",
                            attr,
                            fd,
                            notifier.isEnabled(),
                        )

                # Layer 2 notifiers (Selector)
                selector = getattr(loop, "_selector", None)
                if selector:
                    for mangled in ("_Selector__read_notifiers", "_Selector__write_notifiers"):
                        sel_n = getattr(selector, mangled, {})
                        for fd, notifier in list(sel_n.items()):
                            logger.warning(
                                "  L2 %s FD %d enabled=%s",
                                mangled,
                                fd,
                                notifier.isEnabled(),
                            )
                    fd_to_key = getattr(selector, "_fd_to_key", {})
                    if fd_to_key:
                        logger.warning("  L2 _fd_to_key: %s", list(fd_to_key.keys()))

                tasks = [t for t in asyncio.all_tasks(loop) if not t.done()]
                logger.warning("cpu-monitor: %d live tasks", len(tasks))
                for t in tasks:
                    logger.warning("  task: %s", t)
            t0 = t1
