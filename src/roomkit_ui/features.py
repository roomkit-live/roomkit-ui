"""Optional-feature registry: what this install can do, and how to complete it.

RoomKit UI ships a small core and pulls its backends in through extras
(``pip install 'roomkit-ui[gemini]'``).  Every feature the UI offers but an
install may not carry is declared here once, so a missing backend surfaces as
the command that fixes it rather than as a bare ``ImportError`` — or, worse, a
log line nobody reads.

The extras named here must match ``[project.optional-dependencies]`` in
``pyproject.toml``; :func:`test_features` in ``tests/test_features.py`` keeps
the two in sync.

Call sites use :func:`require` (raises with an actionable message) or
:func:`unavailable_reason` (returns it, for greying a widget out).
``roomkit-ui --doctor`` runs :func:`print_report`.
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from functools import cache
from typing import TextIO

DISTRIBUTION = "roomkit-ui"

# Extras that cannot share an environment: qwen-tts pins transformers==4.57.3,
# neutts wants 5.1.0 and Smart Turn >=5.5.  Mirrors `[tool.uv].conflicts` in
# pyproject.toml — suggesting two in one command would hand the user a
# resolution failure.
EXCLUSIVE_EXTRAS = frozenset({"qwen3-tts", "neutts", "smart-turn"})


class FeatureUnavailableError(RuntimeError):
    """A backend the user selected is not installed.

    The message is written for the user, not the log: it names the feature and
    the command that installs it.  Engine start-up already emits ``str(exc)``
    into the chat, so raising this is enough to surface it.
    """


@dataclass(frozen=True)
class Feature:
    """A capability an install may or may not carry."""

    extra: str
    """Name of the ``[project.optional-dependencies]`` group that provides it."""

    label: str
    """Human name, shown in error messages and the doctor report."""

    probes: tuple[str, ...]
    """Modules that must all be importable for the feature to work."""


FEATURES: dict[str, Feature] = {
    "anthropic": Feature("anthropic", "Anthropic (Claude)", ("anthropic",)),
    # Probe what the code path imports, not what the extra installs.  The
    # realtime providers speak the wire protocol over a raw websocket and never
    # touch the vendor SDK — requiring it would block a session that works.
    # The openai SDK also backs the "Local (vLLM / Ollama)" provider.
    "openai": Feature("openai", "OpenAI (LLM, vLLM / Ollama)", ("openai",)),
    "openai-realtime": Feature("openai", "OpenAI Realtime and xAI Grok", ("websockets",)),
    "gemini": Feature("gemini", "Google Gemini", ("google.genai",)),
    "deepgram": Feature("deepgram", "Deepgram transcription", ("deepgram",)),
    "deepgram-agent": Feature("deepgram", "Deepgram Voice Agent", ("websockets",)),
    "elevenlabs": Feature("elevenlabs", "ElevenLabs", ("elevenlabs",)),
    "gradium": Feature("gradium", "Gradium", ("gradium",)),
    "local-voice": Feature(
        "local-voice",
        "Local speech (STT, Piper TTS, VAD, speaker diarization)",
        ("sherpa_onnx",),
    ),
    "qwen3-tts": Feature("qwen3-tts", "Qwen3-TTS voice cloning", ("qwen_tts",)),
    "neutts": Feature("neutts", "NeuTTS voice cloning", ("neutts",)),
    "dictation": Feature("dictation", "Global-hotkey dictation", ("pynput", "sherpa_onnx")),
    # sherpa_onnx supplies the VAD that gates the detector; onnxruntime runs
    # the whisper encoder that turns a segment into a comparable embedding.
    "wakeword": Feature("wakeword", "Wake word detection", ("onnxruntime", "sherpa_onnx")),
    "mcp-apps": Feature(
        "mcp-apps",
        "MCP Apps, notification sounds and audio preview",
        ("PySide6.QtWebEngineWidgets", "PySide6.QtWebChannel", "PySide6.QtMultimedia"),
    ),
    "telemetry": Feature(
        "telemetry",
        "OpenTelemetry export",
        ("opentelemetry.sdk", "opentelemetry.exporter.otlp"),
    ),
    # roomkit talks to llama-server over the OpenAI API (openai SDK) and
    # downloads the pinned build with httpx; the binary itself is fetched at
    # first use, not installed.
    "llamacpp": Feature("llamacpp", "llama.cpp local LLM (GGUF)", ("openai", "httpx")),
    # roomkit loads the model through both, at warmup.
    "pocket-tts": Feature(
        "pocket-tts", "Pocket TTS (local, voice cloning)", ("pocket_tts", "torch")
    ),
    # One extra, two code paths with different needs: MAI-Transcribe streams
    # over a websocket, Azure Speech TTS posts SSML with httpx (a core dep).
    "azure-stt": Feature("azure-speech", "Azure MAI-Transcribe", ("websockets",)),
    "azure-tts": Feature("azure-speech", "Azure Speech TTS (MAI-Voice)", ("httpx",)),
    # The Voice Channel streams to Muse over a websocket; httpx (a core dep)
    # serves only its one-clip REST endpoint, which the app does not use.
    "meta-stt": Feature("meta-stt", "Meta Muse Voice Transcribe", ("websockets",)),
    # SmartTurnDetector imports numpy and onnxruntime when built, and
    # transformers (WhisperFeatureExtractor) when it loads the model.
    "smart-turn": Feature(
        "smart-turn", "Smart Turn detector", ("numpy", "onnxruntime", "transformers")
    ),
    "typesafe": Feature("typesafe", "TypeSafe Jev classifier", ("typesafe_sdk",)),
}

# Provider ids as stored in QSettings → feature key.  A provider absent from a
# map needs nothing beyond the core.
AI_PROVIDER_FEATURES: dict[str, str] = {
    "anthropic": "anthropic",
    "openai": "openai",
    "gemini": "gemini",
    "local": "openai",
    "llamacpp": "llamacpp",
}

STT_PROVIDER_FEATURES: dict[str, str] = {
    "local": "local-voice",
    "gradium": "gradium",
    "deepgram": "deepgram",
    "azure_mai": "azure-stt",
    "meta": "meta-stt",
}

TTS_PROVIDER_FEATURES: dict[str, str] = {
    "piper": "local-voice",
    "qwen3": "qwen3-tts",
    "neutts": "neutts",
    "gradium": "gradium",
    "elevenlabs": "elevenlabs",
    "pocket": "pocket-tts",
    "azure": "azure-tts",
}

REALTIME_PROVIDER_FEATURES: dict[str, str] = {
    "gemini": "gemini",
    "openai": "openai-realtime",
    "deepgram": "deepgram-agent",
    "elevenlabs": "elevenlabs",
    "xai": "openai-realtime",
    # GPT-Live rides the same websocket transport; tiktoken (in the extra)
    # only sizes context appends, and roomkit falls back to bytes without it.
    "openai_live": "openai-realtime",
}

# Voice-channel speak policies (vc_speak_policy) → the classifier's feature
# key.  "llm" asks the conversation model, which the session already needs.
SPEAK_POLICY_FEATURES: dict[str, str] = {
    "openai": "openai",
    "jev": "typesafe",
}

# Voice-channel turn detectors (vc_turn_detector) → feature key.
TURN_DETECTOR_FEATURES: dict[str, str] = {
    "smart-turn": "smart-turn",
}


@cache
def _module_present(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, AttributeError, ValueError):
        # Parent package missing, or a namespace stub with no __path__.
        return False


@cache
def missing_modules(key: str) -> tuple[str, ...]:
    """Modules the feature needs that this install does not have."""
    return tuple(m for m in FEATURES[key].probes if not _module_present(m))


def is_available(key: str) -> bool:
    """Whether every module the feature needs is importable."""
    return not missing_modules(key)


def install_command(key: str) -> str:
    """The command that completes the install for this feature."""
    return f"pip install '{DISTRIBUTION}[{FEATURES[key].extra}]'"


def unavailable_reason(key: str) -> str | None:
    """A sentence explaining what is missing, or ``None`` if the feature works.

    Written to be shown as-is: in the chat, in a tooltip, next to a combo item.
    """
    if is_available(key):
        return None
    label = FEATURES[key].label
    if getattr(sys, "frozen", False):
        # A frozen build bundles its extras; a gap here is a packaging bug, and
        # telling the user to pip install into a .app would not help them.
        return f"{label} is not included in this build."
    return f"{label} is not installed — run: {install_command(key)}"


def require(key: str) -> None:
    """Raise :class:`FeatureUnavailableError` unless the feature is installed."""
    reason = unavailable_reason(key)
    if reason is not None:
        raise FeatureUnavailableError(reason)


def _version(distribution: str) -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version(distribution)
    except PackageNotFoundError:
        return "unknown"


def print_report(stream: TextIO | None = None) -> None:
    """Write the ``--doctor`` report to *stream*, stdout by default.

    A Windows pipe, or ``--doctor > file`` on Windows, is cp1252, which has no
    ✓ or ✗: print() would raise UnicodeEncodeError.  The marks fall back to
    ASCII where the stream cannot carry them, and any other character it
    cannot (an accented interpreter path) is replaced.
    """
    if stream is None:
        stream = sys.stdout
    if stream is None:  # a windowed build has no console
        return
    encoding = getattr(stream, "encoding", None) or "utf-8"
    try:
        "✓✗".encode(encoding)
        marks = ("✓", "✗")
    except UnicodeEncodeError:
        marks = ("ok", "--")
    report = format_report(marks)
    print(report.encode(encoding, "replace").decode(encoding), file=stream)  # noqa: T201


def format_report(marks: tuple[str, str] = ("✓", "✗")) -> str:
    """Render the ``--doctor`` report: environment, then feature by feature.

    *marks* flag a feature as available and missing, in that order.
    """
    lines = [
        f"roomkit-ui {_version('roomkit-ui')}  (roomkit {_version('roomkit')})",
        f"Python {sys.version.split()[0]} on {sys.platform}"
        + ("  [frozen build]" if getattr(sys, "frozen", False) else ""),
        f"Interpreter: {sys.executable}",
        "",
    ]
    width = max(len(f.label) for f in FEATURES.values())
    missing: list[str] = []
    for key, feature in FEATURES.items():
        absent = missing_modules(key)
        mark = marks[1] if absent else marks[0]
        line = f"  {mark} {feature.label.ljust(width)}"
        if absent:
            line += f"  missing: {', '.join(absent)}"
            missing.append(key)
        lines.append(line)

    lines.append("")
    if not missing:
        lines.append("All features available.")
        return "\n".join(lines)
    if getattr(sys, "frozen", False):
        lines.append(f"{len(missing)} feature(s) missing from this build.")
        return "\n".join(lines)

    # Two features can share one extra (a vendor SDK and its realtime
    # transport), so dedupe while keeping registry order.
    wanted = list(dict.fromkeys(FEATURES[k].extra for k in missing))
    combinable = [e for e in wanted if e not in EXCLUSIVE_EXTRAS]
    if combinable:
        lines.append(
            f"To install everything missing:\n"
            f"  pip install '{DISTRIBUTION}[{','.join(combinable)}]'"
        )
    exclusive = [e for e in wanted if e in EXCLUSIVE_EXTRAS]
    if exclusive:
        if combinable:
            lines.append("")
        lines.append("These pin conflicting transformers versions — install at most one:")
        lines.extend(f"  pip install '{DISTRIBUTION}[{extra}]'" for extra in exclusive)
    return "\n".join(lines)
