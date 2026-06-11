"""Catalog of downloadable local models and their on-disk locations."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class STTModel:
    id: str
    name: str
    type: str  # "offline" or "streaming"
    size: str
    files: tuple[str, ...]


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
    p = Path.home() / ".local" / "share" / "roomkit-ui" / "models"
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
# Smart Turn model (pipecat-ai/smart-turn ONNX)
# ---------------------------------------------------------------------------

SMART_TURN_MODEL_ID = "smart-turn-v3"
SMART_TURN_URL = (
    "https://huggingface.co/pipecat-ai/smart-turn-v3/resolve/main/smart-turn-v3.2-cpu.onnx"
)
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


def is_espeak_ng_downloaded() -> bool:
    """Check whether espeak-ng-data directory exists and has content."""
    d = espeak_ng_data_path()
    return d.is_dir() and (d / "phontab").is_file()


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
