"""Catalog of downloadable local models and their on-disk locations."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from roomkit_ui.paths import data_dir


@dataclass(frozen=True)
class ReleaseArchive:
    """A model sherpa-onnx publishes as a .tar.bz2 release asset with one top
    folder, held to the size and sha256 GitHub publishes for it."""

    url: str
    sha256: str
    size: int
    folder: str


@dataclass(frozen=True)
class STTModel:
    id: str
    name: str
    type: str  # "offline" or "streaming"
    size: str
    files: tuple[str, ...]
    # Silence fed to a streaming transducer after the audio ends; None keeps
    # roomkit's 0.66 s.  Kroko needs 1.5: with less it dropped the last words
    # ("demain à ne", "the lights" for "the lights in the kitchen").
    tail_padding_s: float | None = None
    # Downloaded from a sherpa-onnx release rather than edge-ai-models.
    archive: ReleaseArchive | None = None


STT_MODELS: list[STTModel] = [
    STTModel(
        id="whisper-small",
        name="Whisper Small",
        type="offline",
        size="~357 MB",
        files=("encoder.int8.onnx", "decoder.int8.onnx", "tokens.txt"),
    ),
    STTModel(
        id="parakeet-offline",
        name="Parakeet",
        type="offline",
        size="~640 MB",
        files=(
            "encoder.int8.onnx",
            "decoder.int8.onnx",
            "joiner.int8.onnx",
            "tokens.txt",
        ),
    ),
    STTModel(
        id="kroko-streaming-fr",
        name="Kroko Streaming (FR)",
        type="streaming",
        size="~147 MB",
        files=(
            "encoder.int8.onnx",
            "decoder.int8.onnx",
            "joiner.int8.onnx",
            "tokens.txt",
        ),
        tail_padding_s=1.5,
    ),
    STTModel(
        id="kroko-streaming-en",
        name="Kroko Streaming (EN)",
        type="streaming",
        size="~154 MB",
        files=(
            "encoder.int8.onnx",
            "decoder.int8.onnx",
            "joiner.int8.onnx",
            "tokens.txt",
        ),
        tail_padding_s=1.5,
    ),
    STTModel(
        id="nemotron-streaming",
        name="Nemotron 3.5 Streaming (multilingual)",
        type="streaming",
        size="~475 MB",
        files=(
            "encoder.int8.onnx",
            "decoder.int8.onnx",
            "joiner.int8.onnx",
            "tokens.txt",
        ),
        # NVIDIA's 35-language streaming model, sherpa-onnx's int8 export with
        # 560 ms chunks; it detects the language itself ("auto").
        archive=ReleaseArchive(
            "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
            "sherpa-onnx-nemotron-3.5-asr-streaming-0.6b-560ms-int8-2026-06-11.tar.bz2",
            "c6bf5e0df765f9d5b43bc9e0536d4b4b3e7d40bdf5ecf13e45f134c51c05ae3a",
            475_271_763,
            "sherpa-onnx-nemotron-3.5-asr-streaming-0.6b-560ms-int8-2026-06-11",
        ),
    ),
    STTModel(
        id="zipformer-streaming",
        name="Zipformer Streaming",
        type="streaming",
        size="~122 MB",
        files=(
            "encoder-epoch-29-avg-9-with-averaged-model.int8.onnx",
            "decoder-epoch-29-avg-9-with-averaged-model.int8.onnx",
            "joiner-epoch-29-avg-9-with-averaged-model.int8.onnx",
            "tokens.txt",
        ),
    ),
]

_MODELS_BY_ID: dict[str, STTModel] = {m.id: m for m in STT_MODELS}


def get_models_dir() -> Path:
    """Return (and create) the local models storage directory."""
    p = data_dir() / "models"
    p.mkdir(parents=True, exist_ok=True)
    return p


def model_path(model_id: str) -> Path:
    """Return the directory for a specific model."""
    return get_models_dir() / model_id / "v1"


def is_model_downloaded(model_id: str) -> bool:
    """Check whether all expected files exist for a model."""
    m = _MODELS_BY_ID.get(model_id)
    if m is None:
        return False
    d = model_path(model_id)
    return all((d / f).is_file() for f in m.files)


def delete_model(model_id: str) -> None:
    """Remove a downloaded model's directory."""
    d = get_models_dir() / model_id
    if d.exists():
        shutil.rmtree(d)


# ---------------------------------------------------------------------------
# GTCRN denoiser model (direct GitHub release asset, no LFS)
# ---------------------------------------------------------------------------

GTCRN_MODEL_ID = "gtcrn-denoiser"
GTCRN_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/speech-enhancement-models/gtcrn_simple.onnx"
# The sha256 sherpa-onnx publishes in that release's checksum.txt (GitHub
# computes no digest for assets that old), checked against the file itself.
GTCRN_SHA256 = "e77603ac0c23dac3227dd2d7135b3a585cbee2679048aecfa886657d3ae1b534"
GTCRN_SIZE = "~2 MB"
_GTCRN_FILENAME = "gtcrn_simple.onnx"


def gtcrn_model_path() -> Path:
    """Return the path to the GTCRN ONNX model file."""
    return get_models_dir() / GTCRN_MODEL_ID / _GTCRN_FILENAME


def is_gtcrn_downloaded() -> bool:
    """Check whether the GTCRN model file exists."""
    return gtcrn_model_path().is_file()


def delete_gtcrn() -> None:
    """Remove the GTCRN model directory."""
    d = get_models_dir() / GTCRN_MODEL_ID
    if d.exists():
        shutil.rmtree(d)


# ---------------------------------------------------------------------------
# DPDFNet denoiser model (the same sherpa-onnx release as GTCRN)
# ---------------------------------------------------------------------------

DPDFNET_MODEL_ID = "dpdfnet2-denoiser"
DPDFNET_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/speech-enhancement-models/dpdfnet2.onnx"
# The sha256 GitHub publishes for the asset, checked against the file itself.
# dpdfnet2 is the 16 kHz model: the Voice Channel's input rate.
DPDFNET_SHA256 = "ce35d6025fc71df0ef10d1540e1b7916837bbfe5f6896deb744508d2cad487a9"
DPDFNET_SIZE = "~10 MB"
_DPDFNET_FILENAME = "dpdfnet2.onnx"


def dpdfnet_model_path() -> Path:
    """Return the path to the DPDFNet ONNX model file."""
    return get_models_dir() / DPDFNET_MODEL_ID / _DPDFNET_FILENAME


def is_dpdfnet_downloaded() -> bool:
    """Check whether the DPDFNet model file exists."""
    return dpdfnet_model_path().is_file()


def delete_dpdfnet() -> None:
    """Remove the DPDFNet model directory."""
    d = get_models_dir() / DPDFNET_MODEL_ID
    if d.exists():
        shutil.rmtree(d)


# ---------------------------------------------------------------------------
# Wake word encoder (whisper-tiny's encoder alone)
# ---------------------------------------------------------------------------
# Only the encoder: it turns a speech segment into a comparable acoustic
# sequence.  The decoder is 97 of whisper-tiny's 109 MB and would only give
# us text, which is exactly what the wake word must not depend on.

WAKEWORD_ENCODER_ID = "wakeword-encoder"
WAKEWORD_ENCODER_SIZE = "~12 MB"
_WAKEWORD_ENCODER_FILENAME = "tiny-encoder.int8.onnx"
# sherpa-onnx's whisper-tiny export (input "mel", output n_layer_cross_k),
# which features.WhisperEmbedder is written against.  Pinned to a commit so
# the digest below stays the file's: an upstream re-export would otherwise
# fail the check rather than silently change what detection measures.
WAKEWORD_ENCODER_URL = (
    "https://huggingface.co/csukuangfj/sherpa-onnx-whisper-tiny/resolve/"
    "65176e2deb88badc814a94058666cadccc29b61c/tiny-encoder.int8.onnx"
)
WAKEWORD_ENCODER_BYTES = 12_937_772
WAKEWORD_ENCODER_SHA256 = "d24fb083ae3b1041fc24e97971d60e280c9342201fbb67b0ab428a8b4a51a434"


def wakeword_encoder_path() -> Path:
    """Path to the wake-word encoder ONNX file."""
    return get_models_dir() / WAKEWORD_ENCODER_ID / _WAKEWORD_ENCODER_FILENAME


def is_wakeword_encoder_downloaded() -> bool:
    return wakeword_encoder_path().is_file()


def delete_wakeword_encoder() -> None:
    d = get_models_dir() / WAKEWORD_ENCODER_ID
    if d.exists():
        shutil.rmtree(d)


# ---------------------------------------------------------------------------
# VAD models (Silero / TEN via sherpa-onnx)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VADModel:
    id: str
    name: str
    type: str  # "silero" or "ten" (maps to SherpaOnnxVADConfig.model_type)
    size: str
    onnx_file: str


VAD_MODELS: list[VADModel] = [
    VADModel(
        "ten-vad",
        "TEN VAD",
        "ten",
        "~126 KB",
        "ten-vad.int8.onnx",
    ),
    VADModel(
        "silero-vad",
        "Silero VAD",
        "silero",
        "~2.2 MB",
        "silero_vad.onnx",
    ),
]

_VAD_MODELS_BY_ID: dict[str, VADModel] = {m.id: m for m in VAD_MODELS}

# Map edge-ai-models repo paths for each VAD model
_VAD_REPO_PATHS: dict[str, str] = {
    "ten-vad": "vad/ten/v1/ten-vad.int8.onnx",
    "silero-vad": "vad/silero/v1/silero_vad.onnx",
}


def vad_model_path(model_id: str) -> Path:
    """Return the directory for a specific VAD model."""
    return get_models_dir() / "vad" / model_id / "v1"


def is_vad_model_downloaded(model_id: str) -> bool:
    """Check whether the VAD model ONNX file exists."""
    m = _VAD_MODELS_BY_ID.get(model_id)
    if m is None:
        return False
    return (vad_model_path(model_id) / m.onnx_file).is_file()


def delete_vad_model(model_id: str) -> None:
    """Remove a downloaded VAD model's directory."""
    d = get_models_dir() / "vad" / model_id
    if d.exists():
        shutil.rmtree(d)


# ---------------------------------------------------------------------------
# Kokoro (Kokoro-82M v1.0, int8, as sherpa-onnx packages it)
# ---------------------------------------------------------------------------

KOKORO_MODEL_ID = "kokoro-int8-multi-lang-v1_0"
# A sherpa-onnx release asset, held to the size and sha256 GitHub publishes
# for it (uploaded 2026-09-08). Its voices.bin order is tts/kokoro.py's.
KOKORO_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/"
    "kokoro-int8-multi-lang-v1_0.tar.bz2"
)
KOKORO_SHA256 = "4c3052abaa60943a341f193888cf6abd68787dae6ab8ae5c925a706caa247e4e"
KOKORO_ARCHIVE_BYTES = 132_303_094
KOKORO_SIZE = "~126 MB"
KOKORO_ARCHIVE = ReleaseArchive(KOKORO_URL, KOKORO_SHA256, KOKORO_ARCHIVE_BYTES, KOKORO_MODEL_ID)
# What a session loads; espeak-ng-data (a folder) comes with them.
_KOKORO_FILES = (
    "model.int8.onnx",
    "voices.bin",
    "tokens.txt",
    "lexicon-us-en.txt",
    "lexicon-gb-en.txt",
    "lexicon-zh.txt",
)


def kokoro_model_path() -> Path:
    """Return the folder the Kokoro archive unpacks to."""
    return get_models_dir() / "kokoro" / KOKORO_MODEL_ID


def is_kokoro_downloaded() -> bool:
    """Check whether every file a Kokoro session loads is there."""
    d = kokoro_model_path()
    return all((d / name).is_file() for name in _KOKORO_FILES) and (d / "espeak-ng-data").is_dir()


def delete_kokoro() -> None:
    """Remove the unpacked Kokoro model."""
    d = kokoro_model_path()
    if d.exists():
        shutil.rmtree(d)


# ---------------------------------------------------------------------------
# Smart Turn model (pipecat-ai/smart-turn ONNX)
# ---------------------------------------------------------------------------

SMART_TURN_MODEL_ID = "smart-turn-v3"
# Pinned to a commit, with the sha256 the Hub publishes for that file (its
# LFS oid, from /api/models/.../paths-info), so the download is checked
# against more than a HEAD Content-Length.
SMART_TURN_URL = (
    "https://huggingface.co/pipecat-ai/smart-turn-v3/resolve/"
    "f766f81d3cfdf7737ac64aad813d91bbfd56bf93/smart-turn-v3.2-cpu.onnx"
)
SMART_TURN_SHA256 = "2bb026316b14a660486a75b1733cd3fbab8c2fd0314dc9af7be49f8cca967e4f"
SMART_TURN_SIZE = "~8 MB"
_SMART_TURN_FILENAME = "smart-turn-v3.2-cpu.onnx"


def smart_turn_model_path() -> Path:
    """Return the path to the smart-turn ONNX model file."""
    return get_models_dir() / SMART_TURN_MODEL_ID / _SMART_TURN_FILENAME


def is_smart_turn_downloaded() -> bool:
    """Check whether the smart-turn model file exists."""
    return smart_turn_model_path().is_file()


def delete_smart_turn() -> None:
    """Remove the smart-turn model directory."""
    d = get_models_dir() / SMART_TURN_MODEL_ID
    if d.exists():
        shutil.rmtree(d)


# ---------------------------------------------------------------------------
# TTS models (Piper via sherpa-onnx)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TTSModel:
    id: str
    name: str
    size: str
    sample_rate: int
    num_speakers: int
    onnx_file: str  # e.g. "fr_FR-siwis-medium.onnx"
    config_file: str  # e.g. "fr_FR-siwis-medium.onnx.json"


TTS_MODELS: list[TTSModel] = [
    TTSModel(
        "piper-siwis-medium",
        "Siwis (French Female)",
        "~61 MB",
        22050,
        1,
        "fr_FR-siwis-medium.onnx",
        "fr_FR-siwis-medium.onnx.json",
    ),
    TTSModel(
        "piper-mls-medium",
        "MLS (French Multi-speaker)",
        "~74 MB",
        22050,
        125,
        "fr_FR-mls-medium.onnx",
        "fr_FR-mls-medium.onnx.json",
    ),
    TTSModel(
        "piper-tom-medium",
        "Tom (French Male)",
        "~61 MB",
        44100,
        1,
        "fr_FR-tom-medium.onnx",
        "fr_FR-tom-medium.onnx.json",
    ),
]

_TTS_MODELS_BY_ID: dict[str, TTSModel] = {m.id: m for m in TTS_MODELS}


def tts_model_path(model_id: str) -> Path:
    """Return the directory for a specific TTS model."""
    return get_models_dir() / "tts" / model_id / "v1"


def espeak_ng_data_path() -> Path:
    """Return the shared espeak-ng-data directory."""
    return get_models_dir() / "tts" / "espeak-ng-data"


def is_tts_model_downloaded(model_id: str) -> bool:
    """Check whether the TTS model ONNX + tokens.txt exist."""
    m = _TTS_MODELS_BY_ID.get(model_id)
    if m is None:
        return False
    d = tts_model_path(model_id)
    return (d / m.onnx_file).is_file() and (d / "tokens.txt").is_file()


# Present while an espeak-ng-data download is under way, removed once every
# file is in: the files arrive in API order, so phontab alone proves nothing.
# (A marker of completion instead would disown every install made before it.)
ESPEAK_NG_INCOMPLETE_MARKER = ".download-incomplete"


def is_espeak_ng_downloaded() -> bool:
    """Check whether espeak-ng-data directory exists and has content."""
    d = espeak_ng_data_path()
    return (
        d.is_dir() and (d / "phontab").is_file() and not (d / ESPEAK_NG_INCOMPLETE_MARKER).exists()
    )


def delete_tts_model(model_id: str) -> None:
    """Remove a downloaded TTS model's directory."""
    d = get_models_dir() / "tts" / model_id
    if d.exists():
        shutil.rmtree(d)


def delete_espeak_ng_data() -> None:
    """Remove the shared espeak-ng-data directory."""
    d = espeak_ng_data_path()
    if d.exists():
        shutil.rmtree(d)


# ---------------------------------------------------------------------------
# Speaker embedding models (for diarization)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SpeakerModel:
    id: str
    name: str
    size: str
    onnx_file: str


SPEAKER_MODELS: list[SpeakerModel] = [
    SpeakerModel(
        "nemo-titanet-large",
        "NeMo TitaNet Large",
        "~90 MB",
        "nemo_en_titanet_large.onnx",
    ),
    SpeakerModel(
        "wespeaker-resnet34-lm",
        "WeSpeaker ResNet34-LM (VoxCeleb)",
        "~26 MB",
        "wespeaker_en_voxceleb_resnet34_LM.onnx",
    ),
    SpeakerModel(
        "3dspeaker-campplus-voxceleb",
        "3D-Speaker CAM++ (VoxCeleb)",
        "~28 MB",
        "3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx",
    ),
]

_SPEAKER_MODELS_BY_ID: dict[str, SpeakerModel] = {m.id: m for m in SPEAKER_MODELS}

_SPEAKER_BASE = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models"
)
_SPEAKER_ASSET_URLS: dict[str, str] = {
    "nemo-titanet-large": f"{_SPEAKER_BASE}/nemo_en_titanet_large.onnx",
    "wespeaker-resnet34-lm": f"{_SPEAKER_BASE}/wespeaker_en_voxceleb_resnet34_LM.onnx",
    "3dspeaker-campplus-voxceleb": (
        f"{_SPEAKER_BASE}/3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx"
    ),
}
# From that release's checksum.txt, checked against the files themselves.
_SPEAKER_ASSET_SHA256: dict[str, str] = {
    "nemo-titanet-large": "d51abcf31717ef28162f26acb9d44dd4127c3d44c9b8624f699f3425daca8e77",
    "wespeaker-resnet34-lm": "e9848563da86f263117134dfd7ad63c92355b37de492b55e325400c9d9c39012",
    "3dspeaker-campplus-voxceleb": (
        "357a834f702b80161e5b981182c038e18553c1f2ca752ed6cec2052365d4129b"
    ),
}


def speaker_model_path(model_id: str) -> Path:
    """Return the directory for a specific speaker embedding model."""
    return get_models_dir() / "speaker" / model_id / "v1"


def is_speaker_model_downloaded(model_id: str) -> bool:
    """Check whether the speaker embedding model ONNX file exists."""
    m = _SPEAKER_MODELS_BY_ID.get(model_id)
    if m is None:
        return False
    return (speaker_model_path(model_id) / m.onnx_file).is_file()


def delete_speaker_model(model_id: str) -> None:
    """Remove a downloaded speaker embedding model's directory."""
    d = get_models_dir() / "speaker" / model_id
    if d.exists():
        shutil.rmtree(d)
