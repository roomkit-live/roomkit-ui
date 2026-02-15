"""RoomKit hook registration for UI event bridging."""

from __future__ import annotations

from typing import Any


def register_audio_hooks(kit: Any, engine: Any) -> None:
    """Register ON_INPUT/OUTPUT_AUDIO_LEVEL hooks — shared by both modes."""
    from roomkit.models.enums import HookExecution, HookTrigger

    @kit.hook(HookTrigger.ON_INPUT_AUDIO_LEVEL, HookExecution.ASYNC)
    async def _on_input_level(event, context):
        try:
            db = getattr(event, "level_db", -60.0)
            level = max(0.0, min(1.0, (db + 60.0) / 60.0))
            if engine._mic_muted:
                level = 0.0
            engine.mic_audio_level.emit(level)
        except Exception:
            pass

    @kit.hook(HookTrigger.ON_OUTPUT_AUDIO_LEVEL, HookExecution.ASYNC)
    async def _on_output_level(event, context):
        try:
            db = getattr(event, "level_db", -60.0)
            level = max(0.0, min(1.0, (db + 60.0) / 60.0))
            engine._spk_rms_queue.append(level)
        except Exception:
            pass


def register_vc_hooks(kit: Any, engine: Any) -> None:
    """Register framework hooks for VoiceChannel UI callbacks."""
    from roomkit.models.enums import HookExecution, HookTrigger

    register_audio_hooks(kit, engine)

    @kit.hook(HookTrigger.ON_SPEAKER_CHANGE, HookExecution.ASYNC)
    async def _on_speaker_change(event, context):
        try:
            speaker_id = getattr(event, "speaker_id", "")
            confidence = getattr(event, "confidence", 0.0)
            engine._current_speaker_id = speaker_id
            engine.speaker_identified.emit(speaker_id, confidence)
        except Exception:
            pass

    @kit.hook(HookTrigger.ON_TRANSCRIPTION, HookExecution.SYNC)
    async def _on_user_transcription(text, context):
        from roomkit import HookResult

        # Sticky speaker: use the best ID seen during this utterance so that
        # a single low-score diarization segment doesn't flip to "unknown".
        current = engine._current_speaker_id or ""
        stored = engine._partial_speakers.get("user", "")
        speaker = current if current and current != "unknown" else stored or current
        engine._partial_speakers.pop("user", None)

        # Primary speaker mode: only the primary speaker triggers the AI.
        # Everyone else (other enrolled speakers AND unknown voices) is blocked.
        if (
            engine._primary_speaker_mode
            and engine._primary_speaker_name
            and speaker != engine._primary_speaker_name
        ):
            label = speaker if speaker and speaker != "unknown" else "Unknown"
            try:
                engine.transcription.emit(str(text), "other", True, label)
            except Exception:
                pass
            return HookResult.block("non-primary speaker")

        try:
            engine.transcription.emit(str(text), "user", True, speaker)
        except Exception:
            pass
        return HookResult.allow()

    @kit.hook(HookTrigger.ON_PARTIAL_TRANSCRIPTION, HookExecution.ASYNC)
    async def _on_partial_transcription(event, context):
        try:
            current = engine._current_speaker_id or ""
            # Remember the best speaker ID seen during this utterance.
            if current and current != "unknown":
                engine._partial_speakers["user"] = current
            speaker = engine._partial_speakers.get("user", "") or current
            engine.transcription.emit(str(event.text), "user", False, speaker)
        except Exception:
            pass

    @kit.hook(HookTrigger.ON_SPEECH_START, HookExecution.ASYNC)
    async def _on_speech_start(event, context):
        try:
            engine.user_speaking.emit(True)
        except Exception:
            pass

    @kit.hook(HookTrigger.ON_SPEECH_END, HookExecution.ASYNC)
    async def _on_speech_end(event, context):
        try:
            engine.user_speaking.emit(False)
        except Exception:
            pass

    @kit.hook(HookTrigger.BEFORE_TTS, HookExecution.SYNC)
    async def _on_ai_response(text, context):
        from roomkit import HookResult

        if engine._state != "active":
            return HookResult.allow()
        try:
            # Emit as partial — the chat bubble will stream words progressively
            engine.transcription.emit(str(text), "assistant", False, "")
            engine.ai_speaking.emit(True)
        except Exception:
            pass
        return HookResult.allow()

    @kit.hook(HookTrigger.AFTER_TTS, HookExecution.ASYNC)
    async def _on_tts_done(text, context):
        if engine._state != "active":
            return
        try:
            # Finalize the assistant bubble (renders markdown, shows full text)
            engine.transcription.emit(str(text), "assistant", True, "")
            engine.ai_speaking.emit(False)
        except Exception:
            pass


def register_realtime_hooks(kit: Any, engine: Any) -> None:
    """Register framework hooks for RealtimeVoiceChannel.

    Includes audio level hooks and ON_TRANSCRIPTION for routing
    transcriptions to the UI.  Speaker change events are handled
    directly by the engine via the transport's on_speaker_change callback.
    """
    import logging

    from roomkit.models.enums import HookExecution, HookTrigger

    _log = logging.getLogger("roomkit_ui.hooks.realtime")

    register_audio_hooks(kit, engine)

    # Speaker change events are handled directly by the engine via
    # transport.on_speaker_change() — no hook needed here.

    @kit.hook(HookTrigger.ON_TRANSCRIPTION, HookExecution.SYNC)
    async def _on_transcription(event, context):
        from roomkit import HookResult

        text = str(event.text)
        role = str(event.role)
        is_final = event.is_final

        if role == "user":
            current = engine._current_speaker_id or ""
            # Remember the best speaker ID seen during this utterance.
            # Diarization may reset to "" between the last partial and final,
            # so we keep the last positively-identified speaker.
            stored = engine._partial_speakers.get(role, "")
            if current and current != "unknown":
                engine._partial_speakers[role] = current
                speaker = current
            else:
                speaker = stored or current
            if is_final:
                engine._partial_speakers.pop(role, None)
        else:
            speaker = ""

        _log.info(
            "TRANSCRIPTION: role=%s final=%s speaker=%r text=%r",
            role, is_final, speaker, text[:80],
        )

        # Primary speaker mode: only block when positively identified as
        # a *different* enrolled speaker.  Unknown / empty → benefit of doubt.
        if (
            role == "user"
            and engine._primary_speaker_mode
            and engine._primary_speaker_name
            and speaker
            and speaker != "unknown"
            and speaker != engine._primary_speaker_name
        ):
            _log.info("BLOCKED non-primary speaker %r", speaker)
            if is_final:
                engine._partial_buffers.pop(role, None)
                try:
                    engine.transcription.emit(text, "other", True, speaker)
                except Exception:
                    pass
            return HookResult.block("non-primary speaker")

        # Accumulate partials (providers send deltas, UI needs full text)
        try:
            if is_final:
                engine._partial_buffers.pop(role, None)
                engine.transcription.emit(text, role, True, speaker)
            else:
                buf = engine._partial_buffers.get(role, "")
                buf += text
                engine._partial_buffers[role] = buf
                engine.transcription.emit(buf, role, False, speaker)
        except Exception:
            pass
        return HookResult.allow()
