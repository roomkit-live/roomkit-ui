"""RoomKit hook registration for UI event bridging."""

from __future__ import annotations

from typing import Any

from roomkit_ui.engine_state import EngineState
from roomkit_ui.engine_vc_helpers import LOCAL_TOOL_REFUSAL


def register_audio_hooks(kit: Any, engine: Any) -> None:
    """Register ON_INPUT/OUTPUT_AUDIO_LEVEL hooks — shared by both modes."""
    from roomkit.models.enums import HookExecution, HookTrigger

    @kit.hook(HookTrigger.ON_INPUT_AUDIO_LEVEL, HookExecution.ASYNC)
    async def _on_input_level(event, context):
        try:
            if engine._state != EngineState.ACTIVE:
                return
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
            if engine._state != EngineState.ACTIVE:
                return
            db = getattr(event, "level_db", -60.0)
            level = max(0.0, min(1.0, (db + 60.0) / 60.0))
            engine._spk_rms_queue.append(level)
        except Exception:
            pass


def register_vc_hooks(kit: Any, engine: Any, *, tts_filter: Any = None) -> None:
    """Register framework hooks for VoiceChannel UI callbacks.

    *tts_filter* is the channel's: the assistant bubble shows what is spoken.
    """
    register_audio_hooks(kit, engine)
    _register_vc_user_hooks(kit, engine)
    _register_vc_assistant_hooks(kit, engine, tts_filter)
    _register_vc_error_hooks(kit, engine)


def _register_vc_user_hooks(kit: Any, engine: Any) -> None:
    """The user's side: who speaks, what they said, when they talk."""
    from roomkit.models.enums import HookExecution, HookTrigger

    @kit.hook(HookTrigger.ON_SPEAKER_CHANGE, HookExecution.ASYNC)
    async def _on_speaker_change(event, context):
        try:
            speaker_id = getattr(event, "speaker_id", "")
            # A diarizing STT's label carries no score (roomkit 0.92): None,
            # which the float signal cannot carry.
            confidence = getattr(event, "confidence", None)
            engine.speaker_identified.emit(speaker_id, float(confidence or 0.0))
        except Exception:
            pass

    # Who said an utterance comes with its transcription: the channel runs
    # with pipeline_speakers whenever diarization is on, and names the voice
    # the diarization stage heard the longest over that utterance.
    @kit.hook(HookTrigger.ON_TRANSCRIPTION, HookExecution.SYNC)
    async def _on_user_transcription(event, context):
        from roomkit import HookResult

        # roomkit passes a TranscriptionEvent (with .text) to VC-mode
        # ON_TRANSCRIPTION hooks, not the raw string it used to hand them.
        text = str(event.text)
        speaker = _utterance_speaker(event)

        # Primary speaker mode: only the primary speaker triggers the AI.
        # Everyone else (other enrolled speakers AND unknown voices) is blocked.
        if not _primary_may_speak(engine, event):
            try:
                engine.transcription.emit(text, "other", True, speaker or _UNKNOWN)
            except Exception:
                pass
            return HookResult.block("non-primary speaker")

        # A new user turn: the next assistant sentence opens a new reply.
        engine._partial_buffers.pop("assistant", None)
        try:
            engine.transcription.emit(text, "user", True, speaker)
        except Exception:
            pass
        return _named_after_the_voice(event)

    @kit.hook(HookTrigger.ON_PARTIAL_TRANSCRIPTION, HookExecution.ASYNC)
    async def _on_partial_transcription(event, context):
        # The speaker is known once the utterance ends: its final names it.
        try:
            engine.transcription.emit(str(event.text), "user", False, "")
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


def _register_vc_assistant_hooks(kit: Any, engine: Any, tts_filter: Any) -> None:
    """The assistant's side: the bubble as the reply is spoken, its usage."""
    from roomkit.models.enums import HookExecution, HookTrigger

    @kit.hook(HookTrigger.BEFORE_TTS, HookExecution.SYNC)
    async def _on_ai_response(text, context):
        from roomkit import HookResult

        if engine._state != EngineState.ACTIVE:
            return HookResult.allow()
        # A streamed reply runs this once per sentence, and the bubble wants
        # the growing text: join the sentences as roomkit does for AFTER_TTS.
        # Those sentences are filtered already (only their spacing is not
        # tidied); a reply delivered whole (a TTS without streamed input:
        # Piper, Qwen3, NeuTTS) is filtered only after this hook, so the
        # bubble filters it the same way.
        sentence = str(text).strip()
        if tts_filter is not None:
            sentence = tts_filter(sentence)
        if not sentence:
            return HookResult.allow()
        so_far = engine._partial_buffers.get("assistant", "")
        reply = f"{so_far} {sentence}" if so_far else sentence
        engine._partial_buffers["assistant"] = reply
        try:
            # Emit as partial — the chat bubble will stream words progressively
            engine.transcription.emit(reply, "assistant", False, "")
            engine.ai_speaking.emit(True)
        except Exception:
            pass
        return HookResult.allow()

    @kit.hook(HookTrigger.AFTER_TTS, HookExecution.ASYNC)
    async def _on_tts_done(text, context):
        engine._partial_buffers.pop("assistant", None)
        if engine._state != EngineState.ACTIVE:
            return
        try:
            # Finalize the assistant bubble (renders markdown, shows full text)
            engine.transcription.emit(str(text), "assistant", True, "")
            engine.ai_speaking.emit(False)
        except Exception:
            pass

    @kit.hook(HookTrigger.ON_AI_RESPONSE, HookExecution.ASYNC)
    async def _on_ai_usage(event, context):
        # AIResponseEvent.usage carries the provider's token counters
        # (input/output + cache counters since roomkit 0.42).
        try:
            usage = dict(getattr(event, "usage", {}) or {})
            if usage:
                engine._accumulate_usage(usage)
        except Exception:
            pass


def _register_vc_error_hooks(kit: Any, engine: Any) -> None:
    """Failures the user would otherwise only notice as silence."""
    from roomkit.models.enums import HookExecution, HookTrigger

    # Voice failures became framework events in roomkit 0.35 — surface them
    # in the chat instead of leaving the user with unexplained silence.

    @kit.on("tts_error")
    async def _on_tts_error(event):
        engine._partial_buffers.pop("assistant", None)
        try:
            engine.session_notice.emit(_voice_error_notice("Speech synthesis failed", event.data))
            engine.ai_speaking.emit(False)
        except Exception:
            pass

    @kit.on("stt_error")
    async def _on_stt_error(event):
        try:
            engine.session_notice.emit(
                _voice_error_notice("Speech recognition failed", event.data)
            )
        except Exception:
            pass

    # A turn the LLM could not answer (bad key, quota, refused request) ends
    # in ON_ERROR, not in a voice event: without this the user hears silence.
    @kit.hook(HookTrigger.ON_ERROR, HookExecution.ASYNC)
    async def _on_turn_error(event, context):
        error = str((getattr(event, "metadata", None) or {}).get("error") or "").strip()
        if LOCAL_TOOL_REFUSAL in error:
            return  # register_local_tool_hint names the setting to change instead
        try:
            engine.session_notice.emit(_turn_error_notice(error))
        except Exception:
            pass


_UNKNOWN = "Unknown"


def _utterance_speaker(event: Any) -> str:
    """Who said a voice-channel utterance, for the chat.

    The enrolled name the diarization stage matched; "Unknown" for a voice it
    matched to nobody (roomkit then names the sender "Unknown speaker"); ""
    without diarization.
    """
    label = getattr(event, "speaker", None)
    if label:
        return str(label)
    return _UNKNOWN if getattr(event, "sender_name", None) else ""


def _primary_may_speak(engine: Any, event: Any) -> bool:
    """Whether primary-speaker mode lets this utterance reach the assistant.

    Only an utterance attributed to the primary speaker does.  roomkit carries
    a name as its speaker label, which drops a leading "Speaker" word: the
    primary's name is compared the same way.
    """
    if not (engine._primary_speaker_mode and engine._primary_speaker_name):
        return True
    from roomkit.voice.base import speaker_label

    label = getattr(event, "speaker", None)
    return label is not None and label == speaker_label(engine._primary_speaker_name)


def _named_after_the_voice(event: Any) -> Any:
    """Let the utterance through under the enrolled name of its voice.

    roomkit names a pipeline speaker "Speaker <label>"; the room message, the
    AI's "Name: text" attribution when several people speak, and the stored
    conversation get "Alice" instead.
    """
    import dataclasses

    from roomkit import HookResult

    label = getattr(event, "speaker", None)
    if not label or getattr(event, "sender_name", None) == label:
        return HookResult.allow()
    return HookResult.modify(dataclasses.replace(event, sender_name=label))


def _turn_error_notice(error: str) -> str:
    """One chat-visible line for a turn the assistant could not answer."""
    if len(error) > 200:
        error = error[:197] + "…"
    notice = "The assistant could not answer"
    return f"{notice}: {error}" if error else notice


def _voice_error_notice(prefix: str, data: dict) -> str:
    """One chat-visible line for a tts_error / stt_error framework event."""
    provider = data.get("provider") or "unknown"
    error = str(data.get("error") or "").strip()
    if len(error) > 200:
        error = error[:197] + "…"
    notice = f"{prefix} ({provider})"
    return f"{notice}: {error}" if error else notice


def register_realtime_hooks(kit: Any, engine: Any) -> None:
    """Register framework hooks for RealtimeVoiceChannel.

    Includes audio level hooks and ON_TRANSCRIPTION for routing
    transcriptions to the UI.  A realtime session has no speaker source
    (diarization is voice-channel only, see engine_realtime), so the
    speaker fields below stay empty there.
    """
    import logging

    from roomkit.models.enums import HookExecution, HookTrigger

    _log = logging.getLogger("roomkit_ui.hooks.realtime")

    register_audio_hooks(kit, engine)

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
            "TRANSCRIPTION: role=%s final=%s speaker=%r chars=%d",
            role,
            is_final,
            speaker,
            len(text),
        )
        _log.debug(
            "TRANSCRIPTION text: role=%s final=%s speaker=%r text=%r",
            role,
            is_final,
            speaker,
            text,
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

    # Partial transcriptions travel their own trigger (the channel skips
    # the full hook pipeline for them).  Nothing registered here until the
    # providers started streaming deltas (xAI, Deepgram sentence-by-
    # sentence) — without this hook the realtime chat showed nothing while
    # the agent spoke and the whole reply appeared at the final.
    @kit.hook(HookTrigger.ON_PARTIAL_TRANSCRIPTION, HookExecution.ASYNC)
    async def _on_partial(event, context):
        try:
            if engine._state != EngineState.ACTIVE:
                return
            role = str(getattr(event, "role", "user") or "user")
            speaker = ""
            if role == "user":
                current = engine._current_speaker_id or ""
                if current and current != "unknown":
                    engine._partial_speakers[role] = current
                speaker = engine._partial_speakers.get(role, "") or current
            buf = engine._partial_buffers.get(role, "") + str(event.text)
            engine._partial_buffers[role] = buf
            engine.transcription.emit(buf, role, False, speaker)
        except Exception:
            pass
