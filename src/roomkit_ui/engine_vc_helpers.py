"""Stateless builders for the Voice-Channel session (no engine state).

Extracted from :mod:`roomkit_ui.engine_vc` so the mixin file keeps only
the session orchestration; everything here is a pure function of the
settings dict (plus emit callbacks for UI status/errors).
"""

from __future__ import annotations

import functools
import logging
from typing import Any

from roomkit_ui.mcp_config import has_enabled_mcp_servers

logger = logging.getLogger(__name__)


# How Ollama words a model refusing the tools it was given.
LOCAL_TOOL_REFUSAL = "does not support tools"
_NO_TOOLS_HINT = (
    'This model does not support tool use. Disable "Model supports tool use" in '
    "Settings → AI Provider."
)


def register_local_tool_hint(kit: Any, emit_error) -> None:
    """Point at the setting when a local model refuses the tools it was given.

    The refusal (Ollama: "<model> does not support tools") fails the turn
    inside the AIChannel's streamed generation, and roomkit hands every such
    turn failure to the ON_ERROR hooks with the provider's message in
    ``metadata["error"]``.  Said once per session: every turn fails alike.
    """
    from roomkit.models.enums import HookExecution, HookTrigger

    shown = False

    @kit.hook(HookTrigger.ON_ERROR, HookExecution.ASYNC)
    async def _on_tool_refusal(event: Any, context: Any) -> None:
        nonlocal shown
        error = str((getattr(event, "metadata", None) or {}).get("error", ""))
        if shown or LOCAL_TOOL_REFUSAL not in error:
            return
        shown = True
        try:
            emit_error(_NO_TOOLS_HINT)
        except Exception:
            logger.debug("emit_error failed (Qt object deleted?)", exc_info=True)


# How long "words only" barge-in waits for a streaming STT's first words
# before judging the speech on its duration.  roomkit's examples use 2 s: a
# streaming transducer gives a short word ("okay", "no") 1-1.5 s in.
_TRANSCRIPT_WAIT_MS = 2000


def build_interruption(settings: dict, *, stt_streams: bool) -> Any:
    """The barge-in policy of ``vc_interruption_mode``: off, immediate or semantic.

    *stt_streams* says whether the STT hears words while the user speaks
    (``supports_streaming``), which the semantic mode depends on.
    """
    from roomkit.voice.interruption import InterruptionConfig, InterruptionStrategy

    mode = settings.get("vc_interruption_mode", "off")
    if mode == "semantic":
        config = _semantic_interruption(stt_streams)
    elif mode == "immediate":
        config = InterruptionConfig(strategy=InterruptionStrategy.IMMEDIATE)
    else:
        # DISABLED explicitly: None would let roomkit fall back to its own default.
        config = InterruptionConfig(strategy=InterruptionStrategy.DISABLED)
    logger.info("Interruption: %s (STT streams: %s)", config.strategy.value, stt_streams)
    return config


def _semantic_interruption(stt_streams: bool) -> Any:
    """Words only: an acknowledgement lets the assistant go on, other words stop it.

    ``PhraseBackchannelDetector`` reads the words the STT hears while the
    assistant speaks ("ok", "mm", "d'accord", "merci" — English and French).
    With a streaming STT, sound without words (echo the AEC left, a cough)
    never cuts in.  An STT that does not stream (a Whisper-type local model)
    has no words before the speech ends, so there wordless speech must still
    cut in once it lasts — as CONFIRMED does — or nothing could stop the
    assistant at all.
    """
    from roomkit.voice.interruption import InterruptionConfig, InterruptionStrategy
    from roomkit.voice.pipeline.backchannel import PhraseBackchannelDetector

    return InterruptionConfig(
        strategy=InterruptionStrategy.SEMANTIC,
        backchannel_detector=PhraseBackchannelDetector(cut_without_words=not stt_streams),
        transcript_wait_ms=_TRANSCRIPT_WAIT_MS,
    )


# The reasoning settings a cloud LLM takes, in roomkit's words (RFC §6.7):
# ``enable_thinking`` switches reasoning, ``reasoning_effort`` says how much
# and ``none`` is off.  Empty, in each setting, leaves the model's default.
CLAUDE_THINKING = ("on", "off")
CLAUDE_EFFORTS = ("low", "medium", "high", "xhigh", "max")
GEMINI_THINKING_LEVELS = ("none", "minimal", "low", "medium", "high")

# A turn's output budget.  roomkit's providers default to 1024 tokens, and
# reasoning counts against it: Claude 5.x and Gemini 3.x reason when the turn
# says nothing, so a reply was cut mid-sentence and a round of tool calls lost
# its last call ("Provider cut tool call").  Every cloud model the app offers
# writes 16 384 tokens at least (gpt-4o the fewest); 64k is Anthropic's
# starting point at xhigh and max.  A cap, not a cost: unused tokens are free.
_CLOUD_LLMS = ("anthropic", "gemini", "openai")
# The Voice Channel's LLMs that run on this machine or the user's server.
LOCAL_LLMS = ("local", "llamacpp")
_CLOUD_MAX_TOKENS = 16_000
_CLAUDE_DEEP_MAX_TOKENS = 64_000


def reasoning_options(settings: dict, llm_provider: str) -> dict[str, Any]:
    """The ``AIChannel`` reasoning arguments for the session's LLM, and the
    room its turn gets.

    Claude takes thinking and effort apart: with thinking off, the effort
    still sets how much it writes and how readily it calls tools.  Gemini has
    one level, off included.  roomkit sends each model what it takes, and a
    model that cannot stop thinking its lowest level for off.  OpenAI gets
    none: a voice turn always carries tools, and with tools roomkit sends
    GPT-5.4 and later no reasoning whatever is asked.  A local model keeps
    its server's budget: its context window may be smaller than ours.
    """
    options: dict[str, Any] = {}
    if llm_provider in _CLOUD_LLMS:
        options["max_tokens"] = _CLOUD_MAX_TOKENS
    if llm_provider == "anthropic":
        thinking = settings.get("vc_anthropic_thinking", "")
        if thinking in CLAUDE_THINKING:
            options["enable_thinking"] = thinking == "on"
        effort = settings.get("vc_anthropic_effort", "")
        if effort in CLAUDE_EFFORTS:
            options["reasoning_effort"] = effort
            if effort in ("xhigh", "max"):
                options["max_tokens"] = _CLAUDE_DEEP_MAX_TOKENS
    elif llm_provider == "gemini":
        level = settings.get("vc_gemini_thinking", "")
        if level in GEMINI_THINKING_LEVELS:
            options["reasoning_effort"] = level
    return options


def build_tts_filter(settings: dict) -> Any:
    """What the TTS must not read aloud of a reply, as one roomkit filter chain.

    - Technical text: a JSON object the model wrote instead of calling a tool,
      a ``(Note: ...)`` to itself, a ``---`` separator.
    - Bracketed stage directions (``[smiles]``, ``[Respond in French]``) —
      except on a TTS that performs audio tags (ElevenLabs v3/v4, Gemini),
      where ``[laughs]`` is a cue the voice acts out.  Their tags are
      open-ended, so no keep-list would cover them: brackets all pass there,
      as roomkit advises for both (``audio_tags.performed_tags``).
    - Emoji, which a TTS names or garbles.

    AFTER_TTS gets the filtered text, and the assistant bubble filters what
    BEFORE_TTS shows it (hooks.py), so the chat reads what is spoken; the
    stored conversation keeps the text as the model wrote it.
    """
    from roomkit.voice.tts.filters import (
        StripBrackets,
        StripEmoji,
        StripTechnicalText,
        TTSFilterChain,
    )

    from roomkit_ui.audio_tags import performed_tags

    # Technical text first: brackets left around a removed JSON array go next.
    filters: list[Any] = [StripTechnicalText()]
    if not performed_tags(settings):
        filters.append(StripBrackets())
    filters.append(StripEmoji())
    return TTSFilterChain(*filters)


def smart_turn_config(settings: dict, inference_device: str) -> Any:
    """The SmartTurnConfig the settings ask for; None when no detector is selected
    or its model is not downloaded."""
    if settings.get("vc_turn_detector", "") != "smart-turn":
        return None

    from roomkit_ui.model_manager import is_smart_turn_downloaded, smart_turn_model_path

    if not is_smart_turn_downloaded():
        logger.warning("Smart Turn model not downloaded — skipping")
        return None

    from roomkit.voice.pipeline.turn.smart_turn import SmartTurnConfig

    threshold: dict[str, Any] = {"threshold": 0.5}
    try_set_float(threshold, "threshold", settings.get("vc_turn_threshold", ""))
    return SmartTurnConfig(
        model_path=str(smart_turn_model_path()),
        threshold=threshold["threshold"],
        provider=inference_device,
    )


def build_turn_detector(config: Any) -> Any:
    """A SmartTurnDetector the engine keeps across sessions.

    The pipeline closes its stages when a session ends, and SmartTurnDetector
    .close() drops its ONNX session — the cached detector would load again,
    every session.  This one keeps it; the engine's model cache owns it.
    """
    logger.info("Turn detector: smart-turn, threshold=%.2f", config.threshold)
    return _kept_smart_turn_class()(config)


@functools.cache
def _kept_smart_turn_class() -> type:
    from roomkit.voice.pipeline.turn.smart_turn import SmartTurnDetector

    class KeptSmartTurnDetector(SmartTurnDetector):
        def close(self) -> None:
            """Stay loaded for the next session (see build_turn_detector)."""

    return KeptSmartTurnDetector


def turn_incomplete_wait_ms(settings: dict) -> float:
    """How long a turn the detector judged unfinished waits for more speech.

    roomkit's default (1500 ms) unless the setting holds a number of ms.
    """
    wait: dict[str, Any] = {"ms": 1500.0}
    try_set_float(wait, "ms", settings.get("vc_turn_incomplete_wait_ms", ""))
    return float(wait["ms"])


def log_vc_audio_pipeline(
    aec: Any, denoiser: Any, input_sample_rate: int, output_sample_rate: int
) -> None:
    aec_label = type(aec).__name__ if aec else "none"
    denoise_label = type(denoiser).__name__ if denoiser else "none"
    logger.info(
        "VC audio pipeline: aec=%s, denoiser=%s, in_rate=%dHz, out_rate=%dHz",
        aec_label,
        denoise_label,
        input_sample_rate,
        output_sample_rate,
    )


def mcp_servers_configured(settings: dict) -> bool:
    return has_enabled_mcp_servers(settings.get("mcp_servers", "[]"))


def try_set_int(target: dict[str, Any], key: str, raw: str) -> None:
    if not raw:
        return
    try:
        target[key] = int(raw)
    except (ValueError, TypeError):
        pass


def try_set_float(target: dict[str, Any], key: str, raw: str) -> None:
    if not raw:
        return
    try:
        target[key] = float(raw)
    except (ValueError, TypeError):
        pass


def announce_llm_model(provider: Any, emit_notice) -> None:
    """Say in the chat what the user should know about the session's model.

    Once, that a retired default was moved to its successor (see
    ``settings._RETIRED_DEFAULTS``).  Every session, that a model the user
    kept is deprecated in roomkit's catalog: it stops answering on the
    vendor's retirement date, and a deliberate pick is not overridden.
    """
    from roomkit_ui.settings import take_model_notices

    for notice in take_model_notices():
        emit_notice(notice)
    try:
        entry = provider.catalog_entry()
    except Exception:
        return
    if entry is not None and getattr(entry, "deprecated", False):
        name = getattr(entry, "display_name", None) or entry.id
        emit_notice(
            f"{name} is deprecated by its vendor and will stop answering. "
            "Pick another model in Settings → AI Provider → LLM."
        )


async def start_local_llm(provider: Any, emit_status) -> None:
    """Start a model roomkit runs itself before the session opens the mic.

    llama.cpp downloads llama-server and the model the first time, and loads
    the model at each server start: left to the first turn, the user's first
    sentence would wait in silence for it — minutes on a first run.  The
    server outlives the session (providers/llamacpp.py), so later sessions
    find it running and return at once.
    """
    if getattr(provider, "name", "") != "llamacpp":
        return
    emit_status("Starting llama.cpp — the first run downloads the model…")
    await provider.start()
