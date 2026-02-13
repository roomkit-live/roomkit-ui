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

    @kit.hook(HookTrigger.ON_TRANSCRIPTION, HookExecution.SYNC)
    async def _on_user_transcription(text, context):
        from roomkit import HookResult

        try:
            engine.transcription.emit(str(text), "user", True)
        except Exception:
            pass
        return HookResult.allow()

    @kit.hook(HookTrigger.ON_PARTIAL_TRANSCRIPTION, HookExecution.ASYNC)
    async def _on_partial_transcription(event, context):
        try:
            engine.transcription.emit(str(event.text), "user", False)
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

        try:
            engine.transcription.emit(str(text), "assistant", True)
            engine.ai_speaking.emit(True)
        except Exception:
            pass
        return HookResult.allow()

    @kit.hook(HookTrigger.AFTER_TTS, HookExecution.ASYNC)
    async def _on_tts_done(text, context):
        try:
            engine.ai_speaking.emit(False)
        except Exception:
            pass
