"""Realtime speech-to-speech session mixin for ``Engine``.

Contains the realtime startup path (Gemini Live, OpenAI Realtime, OpenAI
GPT-Live, Deepgram Voice Agent, ElevenLabs Conversational AI, xAI Grok): build the
provider, wire audio pipeline + transport, connect MCP tools, register
hooks, and hand off to the UI by populating ``engine._session``.

The 2-step retry (with → without MCP tools) lets a provider that refuses
the MCP schemas still deliver a working session; it runs on freshly built
media, and only on such a refusal (``_open_realtime_session``).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from roomkit_ui.engine_audio import (
    DSP_THREADS,
    build_audio_processing,
    build_debug_taps,
    build_recorder,
    notify_missing_aec,
    usable_capture_source,
)
from roomkit_ui.engine_state import EngineState
from roomkit_ui.hooks import register_realtime_hooks
from roomkit_ui.mcp_config import has_enabled_mcp_servers
from roomkit_ui.realtime_providers import (
    build_provider_config,
    build_realtime_provider,
    deepgram_half_duplex,
    realtime_sample_rate,
    transport_audio_profile,
)
from roomkit_ui.toolset import ToolSet, tool_summaries

logger = logging.getLogger(__name__)

_BLOCK_MS = 20

# Diarization is a voice-channel feature: under roomkit 0.96.1 a realtime
# session cannot run it.  RealtimeVoiceChannel registers no handler for the
# pipeline's speaker changes and fires no ON_SPEAKER_CHANGE, so no label ever
# reached the app; the 16 kHz pipeline the models need was forwarded to the
# provider as if it were the 24 kHz transport audio; and primary-speaker
# gating (LocalAudioBackend.set_input_gated) drops frames before the
# pipeline, so diarization could never hear the primary speaker again.
REALTIME_DIARIZATION_NOTICE = (
    "Speaker diarization works in Voice Channel mode only — this realtime "
    "session runs without speaker labels or primary-speaker mode."
)


@dataclass(frozen=True)
class _RealtimeMedia:
    """What one start attempt connects; a failed attempt closes all of it."""

    provider: Any
    voice: str
    model: str
    transport: Any
    pipeline: Any
    aec: Any
    sample_rate: int


class RealtimeMixin:
    """Realtime (speech-to-speech) session setup for ``Engine``.

    Attribute annotations mirror the concrete ``Engine`` so mypy can type
    ``self._attitude`` and friends from inside mixin methods.
    """

    _state: EngineState
    _attitude: str
    _attitude_name: str
    _base_system_prompt: str
    _transport: Any
    _kit: Any
    _channel: Any
    _session: Any
    _pending_tool_calls: int

    async def _start_realtime(self, settings: dict) -> None:
        try:
            provider_name = settings.get("provider", "gemini")
            system_prompt = self._compose_session_prompt(settings)  # type: ignore[attr-defined]
            # Half-duplex (Deepgram escape hatch): the mic is muted while the
            # agent speaks, so there is no echo to cancel — no AEC, and its
            # absence arms the playback gate (see _build_realtime_media).
            aec_mode = settings.get("aec_mode", "webrtc")
            if deepgram_half_duplex(provider_name, settings):
                logger.info("Deepgram half-duplex: mic muted during playback, AEC skipped")
                aec_mode = "none"
            denoise_mode = settings.get("denoise", "none")
            if denoise_mode != "none":
                logger.info("Denoiser (%s) not applied in realtime mode", denoise_mode)
            provider_config = build_provider_config(provider_name, settings)

            if settings.get("diarization_enabled"):
                self.session_notice.emit(REALTIME_DIARIZATION_NOTICE)  # type: ignore[attr-defined]

            # Provider, transport and pipeline are built once per attempt: a
            # failed attempt's kit.close() closes all three (the transport's
            # AEC with it), so a retry must not reuse any of them.
            def build_media() -> _RealtimeMedia:
                return self._build_realtime_media(settings, provider_name, aec_mode)

            # Built before the tools: a missing key fails before MCP connects.
            media = build_media()
            notify_missing_aec(aec_mode, media.aec, self.session_notice.emit)  # type: ignore[attr-defined]

            # -- MCP tools -------------------------------------------------------
            if has_enabled_mcp_servers(settings.get("mcp_servers", "[]")):
                self.loading_status.emit("Connecting MCP servers…")  # type: ignore[attr-defined]
            toolset = await self._setup_tools(settings)  # type: ignore[attr-defined]

            # Agent Skills — same registry the VC path loads.  The channel
            # resolves delivery per provider: reconfigurable sessions (Gemini,
            # OpenAI) get the skill list in the prompt plus an activate_skill
            # tool; fixed sessions get every body inlined at connect.
            skills_registry = self._load_skills(settings)  # type: ignore[attr-defined]

            logger.info("Tools: %s", ", ".join(t["name"] for t in toolset.all))
            self.loading_status.emit("Connecting to provider…")  # type: ignore[attr-defined]
            if provider_config:
                logger.debug("provider_config: %s", provider_config)
            media, tools = await self._open_realtime_session(
                media,
                build_media,
                system_prompt,
                toolset,
                settings=settings,
                provider_config=provider_config or None,
                skills=skills_registry,
            )

            register_realtime_hooks(self._kit, self)  # type: ignore[attr-defined]

            self._spk_rms_queue.clear()  # type: ignore[attr-defined]
            self._spk_timer.start()  # type: ignore[attr-defined]
            self._pending_tool_calls = 0  # type: ignore[attr-defined]
            self._watchdog.start()  # type: ignore[attr-defined]

            self._enter_active()  # type: ignore[attr-defined]

            # Emit structured session info for the UI info bar
            skill_info: list[dict] = []
            if skills_registry and skills_registry.skill_count > 0:
                skill_info = [
                    {"name": m.name, "description": m.description}
                    for m in skills_registry.all_metadata()
                ]
            info: dict = {
                "provider": provider_name,
                "model": media.model,
                "tools": tool_summaries(tools),
                "skills": skill_info,
            }
            if self._mcp and self._mcp.failed_servers:  # type: ignore[attr-defined]
                info["failed_servers"] = list(self._mcp.failed_servers)  # type: ignore[attr-defined]
            self.session_info.emit(info)  # type: ignore[attr-defined]
            if self._attitude_name:  # type: ignore[attr-defined]
                self.attitude_changed.emit(self._attitude_name)  # type: ignore[attr-defined]

        except Exception as e:
            logger.exception("Failed to start voice session")
            await self._fail_start(str(e))  # type: ignore[attr-defined]

    def _build_realtime_media(
        self,
        settings: dict,
        provider_name: str,
        aec_mode: str,
    ) -> _RealtimeMedia:
        """Build what one start attempt connects: provider, transport, pipeline.

        Fresh each attempt — the previous attempt's kit.close() closed them.
        """
        from roomkit.voice.backends.local import LocalAudioBackend

        provider, voice, model = build_realtime_provider(provider_name, settings)
        sample_rate = realtime_sample_rate(provider_name)
        frame_size = sample_rate * _BLOCK_MS // 1000

        # User-selected denoisers are voice-channel only: a speech enhancer on
        # the mic path keeps the *dominant* voice, so during doubletalk it eats
        # the user's barge-in speech before the provider's VAD sees it.
        # (Deepgram gets the mild WebRTC noise suppressor below, mirroring
        # roomkit's example.)
        aec, _ = build_audio_processing(aec_mode, "none", sample_rate, frame_size)
        aec = _with_aec_dump(aec)
        # Provider-specific transport wiring — see transport_audio_profile.
        transport_aec, rt_denoiser, prebuffer_ms = transport_audio_profile(
            provider_name, aec, sample_rate
        )
        if transport_aec is not None or rt_denoiser is not None:
            logger.info(
                "Transport-level AEC=%s (%s) + webrtc NS, prebuffer=%dms",
                transport_aec is not None,
                provider_name,
                prebuffer_ms,
            )
        recorder, recording_config = build_recorder(settings)
        pipeline = _build_realtime_pipeline(
            aec=aec,
            denoiser=rt_denoiser,
            debug_taps=build_debug_taps(settings),
            recorder=recorder,
            recording_config=recording_config,
        )

        # The pipeline attaches to the RealtimeVoiceChannel (see _start_session),
        # NOT the transport.  AEC placement is per provider (see
        # transport_audio_profile): Gemini/OpenAI keep the pipeline-stage AEC
        # (transport_aec is None — LocalAudioBackend(aec=...) would flag
        # NATIVE_AEC and lose the continuous playback reference, the 0.9.0
        # barge-in fix), while Deepgram and GPT-Live run it at transport level
        # like roomkit's examples (realtime_voice_local_deepgram.py,
        # realtime_voice_local_openai_live.py), where NATIVE_AEC correctly
        # makes the pipeline skip its own stage.  No AEC at all arms the
        # playback gate (half-duplex).
        transport = LocalAudioBackend(
            input_sample_rate=sample_rate,
            output_sample_rate=sample_rate,
            block_duration_ms=_BLOCK_MS,
            mute_mic_during_playback=aec is None,
            rt_prebuffer_ms=prebuffer_ms,
            input_device=settings.get("input_device"),
            output_device=settings.get("output_device"),
            aec=transport_aec,
            source=usable_capture_source(getattr(self, "_capture_source", None), sample_rate),
        )
        self._transport = transport
        # A mute pressed while connecting reaches the session once its
        # capture is live; the channel creates the session in start_session.
        transport.on_session_ready(self._apply_mic_mute)  # type: ignore[attr-defined]

        logger.info(
            "Audio pipeline: aec=%s (pipeline stage), rate=%dHz, block=%dms",
            type(aec).__name__ if aec else "none",
            sample_rate,
            _BLOCK_MS,
        )
        self._register_callbacks(provider, transport)  # type: ignore[attr-defined]
        return _RealtimeMedia(provider, voice, model, transport, pipeline, aec, sample_rate)

    async def _open_realtime_session(
        self,
        media: _RealtimeMedia,
        build_media: Callable[[], _RealtimeMedia],
        system_prompt: str,
        toolset: ToolSet,
        *,
        settings: dict,
        provider_config: dict[str, Any] | None,
        skills: Any,
    ) -> tuple[_RealtimeMedia, list[dict]]:
        """Start the session with every tool — or without MCP, if they were refused.

        Only MCP is shed: its schemas are server-supplied and arbitrary,
        whereas built-in and CLI schemas are hand-authored and known-good.
        And only when the provider refused what the session declared
        (``_refuses_session_config``): a bad key, the network or a quota is
        the session's real error, which shedding MCP would only hide behind a
        misleading notice.  If the retry fails too, the first error — the
        one that explains the session — is the one raised.

        Returns the media of the attempt that started, and its tools.
        """
        from roomkit import RealtimeVoiceChannel, RoomKit

        async def attempt(media: _RealtimeMedia, tools: list[dict]) -> None:
            self._session = await self._start_session(
                RoomKit,
                RealtimeVoiceChannel,
                media.provider,
                media.transport,
                system_prompt,
                media.voice,
                media.sample_rate,
                tools,
                self._handle_tool_call,  # type: ignore[attr-defined]
                provider_config=provider_config,
                settings=settings,
                pipeline=media.pipeline,
                skills=skills,
                tool_options=toolset.channel_options(),
            )

        try:
            await attempt(media, toolset.all)
            return media, toolset.all
        except Exception as exc:
            if not (toolset.has_mcp and _refuses_session_config(exc)):
                raise
            refusal = exc
        logger.warning("Provider refused the session with MCP tools — retrying without them")
        media = build_media()
        try:
            await attempt(media, toolset.without_mcp)
        except Exception:
            logger.exception("Session without MCP tools failed too")
            raise refusal from None
        self.mcp_status.emit(  # type: ignore[attr-defined]
            f"MCP tools disabled — the provider refused them: {_brief(refusal)}"
        )
        return media, toolset.without_mcp

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
        provider_config: dict[str, Any] | None = None,
        settings: dict | None = None,
        pipeline: Any = None,
        skills: Any = None,
        tool_options: dict[str, Any] | None = None,
    ) -> Any:
        """Create the room and start a realtime session; raise what refused it."""
        from roomkit_ui.engine_audio import build_telemetry
        from roomkit_ui.memory import ROOM_ID, build_store, ensure_room, memory_recap

        try:
            telemetry = build_telemetry(settings) if settings else None
            store = build_store(settings) if settings else None
            self._kit = (  # type: ignore[attr-defined]
                RoomKit(telemetry=telemetry, store=store)
                if store
                else RoomKit(telemetry=telemetry)
            )
            await ensure_room(self._kit)  # type: ignore[attr-defined]
            if store is not None and system_prompt is not None:
                # Realtime context lives server-side and starts blank — the
                # recap is the only way previous sessions reach the provider.
                recap = await memory_recap(self._kit)  # type: ignore[attr-defined]
                if recap:
                    system_prompt = f"{system_prompt}\n\n{recap}"
            self._channel = RealtimeVoiceChannel(  # type: ignore[attr-defined]
                "voice",
                provider=provider,
                transport=transport,
                system_prompt=system_prompt,
                # ElevenLabs has no per-session voice override (agent-defined) —
                # its builder returns "" and the channel must see None.
                voice=voice or None,
                input_sample_rate=sample_rate,
                output_sample_rate=sample_rate,
                tools=tools,
                tool_handler=tool_handler,
                pipeline=pipeline,
                skills=skills,
                **(tool_options or {}),
            )
            self._kit.register_channel(self._channel)  # type: ignore[attr-defined]
            await self._kit.attach_channel(ROOM_ID, "voice")  # type: ignore[attr-defined]
            metadata: dict[str, Any] = {}
            if provider_config:
                metadata["provider_config"] = provider_config
            # The backend replays the shared source from here, so the phrase
            # spoken before the session existed reaches the provider — unless
            # the user muted while connecting: the replay runs before the
            # session's capture is live, so before the mute can reach it.
            capture_since = getattr(self, "_capture_since", None)
            if capture_since is not None and not getattr(self, "_mic_muted", False):
                metadata["capture_since"] = capture_since
            return await self._channel.start_session(  # type: ignore[attr-defined]
                ROOM_ID,
                "local-user",
                connection=None,
                metadata=metadata or None,
            )
        except Exception:
            # Closing the kit closes the channel, and with it the provider and
            # the transport: an attempt's media never serves another one.
            try:
                await self._kit.close()  # type: ignore[attr-defined]
            except Exception:
                logger.debug("kit.close() after a failed start failed", exc_info=True)
            self._kit = None  # type: ignore[attr-defined]
            self._channel = None  # type: ignore[attr-defined]
            raise


# ---------------------------------------------------------------------------
# Start failures (module-level — no engine state)
# ---------------------------------------------------------------------------

# Gemini Live's close code for an invalid argument — "e.g. a tool schema
# Gemini Live won't accept", in roomkit's providers/gemini/realtime_connection.
_WS_INVALID_ARGUMENT = 1007


def _refuses_session_config(exc: BaseException) -> bool:
    """Whether a failed start is a refusal of what the session declared.

    roomkit 0.96.1 has no error type for a refused tool schema; a start that
    fails on one surfaces as:

    * a ValueError — what roomkit raises when it refuses to declare a tool
      while building the channel (ToolNameCollisionError is one); one from
      elsewhere costs a second attempt, after which it is raised as is;
    * Gemini Live closing the setup with 1007, invalid argument (the SDK's
      APIError carries the code);
    * Deepgram answering the Settings message, which carries the functions,
      with an Error ("Deepgram rejected Settings").

    OpenAI and xAI open the socket first and report a bad ``session.update``
    as a provider error afterwards: no start fails on their tools.  GPT-Live
    hands the tools to its hosted backend in ``session.start``, and a refused
    start is a ConnectionError ("GPT-Live session failed to start: <code>:
    ...") whose code for a bad schema is unknown — so it is not retried.  A
    bad key, the network or a quota is none of these.
    """
    for err in (exc, exc.__cause__):
        if err is None:
            continue
        if isinstance(err, ValueError):
            return True
        if getattr(err, "code", None) == _WS_INVALID_ARGUMENT:
            return True
        if isinstance(err, ConnectionError) and "rejected Settings" in str(err):
            return True
    return False


def _brief(exc: BaseException, limit: int = 160) -> str:
    text = str(exc).strip() or type(exc).__name__
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _with_aec_dump(aec: Any) -> Any:
    """Wrap *aec* in the bench recorder when ROOMKIT_AEC_DUMP=<dir> is set.

    Realtime-only — the VC path hands the same AEC instance to the backend,
    whose transport-level integration the recorder does not mimic.
    """
    import os

    dump_dir = os.environ.get("ROOMKIT_AEC_DUMP", "")
    if aec is None or not dump_dir:
        return aec
    from pathlib import Path

    from roomkit_ui.aec_dump import AECDumpRecorder

    logger.warning("AEC dump recording enabled → %s", dump_dir)
    return AECDumpRecorder(aec, Path(dump_dir).expanduser())


# ---------------------------------------------------------------------------
# Pipeline helpers (module-level — no engine state)
# ---------------------------------------------------------------------------


def _build_realtime_pipeline(
    *,
    aec: Any,
    denoiser: Any = None,
    debug_taps: Any,
    recorder: Any,
    recording_config: Any,
) -> Any:
    """Assemble the realtime ``AudioPipelineConfig`` (or ``None`` if nothing to do).

    Every stage runs at the transport's sample rate, which is the rate the
    provider is told it receives.  No VAD or diarization: see
    ``REALTIME_DIARIZATION_NOTICE``.  No user denoiser in realtime — see
    ``_build_realtime_media``.
    """
    from roomkit.voice.pipeline.config import AudioPipelineConfig

    if aec is not None or denoiser is not None or debug_taps is not None or recorder is not None:
        return AudioPipelineConfig(
            aec=aec,
            denoiser=denoiser,
            debug_taps=debug_taps,
            recorder=recorder,
            recording_config=recording_config,
            inbound_dsp_threads=DSP_THREADS,
        )
    return None
