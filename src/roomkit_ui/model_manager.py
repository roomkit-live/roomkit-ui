"""Download and manage local STT/TTS models from edge-ai-models."""

from __future__ import annotations

import asyncio
import ctypes
import json
import shutil
import sys
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

_RAW_URL = "https://raw.githubusercontent.com/anganyAI/edge-ai-models/main"
_LFS_BATCH_URL = "https://github.com/anganyAI/edge-ai-models.git/info/lfs/objects/batch"
_GH_API_URL = "https://api.github.com/repos/anganyAI/edge-ai-models/contents"

# Progress callback: (bytes_downloaded, total_bytes)
ProgressCallback = Callable[[int, int], None]


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


def _resolve_lfs_pointer(raw_content: bytes) -> tuple[str, int] | None:
    """Parse a Git LFS pointer and return (oid, size), or None if not LFS."""
    text = raw_content.decode("utf-8", errors="replace")
    if not text.startswith("version https://git-lfs"):
        return None
    oid = ""
    size = 0
    for line in text.splitlines():
        if line.startswith("oid sha256:"):
            oid = line.split(":", 1)[1]
        elif line.startswith("size "):
            size = int(line.split(" ", 1)[1])
    return (oid, size) if oid else None


def _lfs_download_url(oid: str, size: int) -> str:
    """Call the GitHub LFS batch API to get a direct download URL."""
    payload = json.dumps(
        {
            "operation": "download",
            "transfers": ["basic"],
            "objects": [{"oid": oid, "size": size}],
        }
    ).encode()
    req = urllib.request.Request(  # noqa: S310
        _LFS_BATCH_URL,
        data=payload,
        headers={
            "Content-Type": "application/vnd.git-lfs+json",
            "Accept": "application/vnd.git-lfs+json",
        },
    )
    with urllib.request.urlopen(req) as resp:  # noqa: S310
        data = json.loads(resp.read())
    obj = data["objects"][0]
    if "error" in obj:
        raise RuntimeError(f"LFS error: {obj['error']}")
    return str(obj["actions"]["download"]["href"])


_CHUNK = 256 * 1024  # 256 KB read chunks


def _download_file(
    url: str,
    target: Path,
    expected_size: int = 0,
    on_bytes: Callable[[int], None] | None = None,
) -> None:
    """Download *url* to *target* atomically, reporting bytes via *on_bytes*."""
    tmp = target.with_suffix(target.suffix + ".part")
    try:
        req = urllib.request.Request(url)  # noqa: S310
        with urllib.request.urlopen(req) as resp, open(tmp, "wb") as fp:  # noqa: S310
            while True:
                chunk = resp.read(_CHUNK)
                if not chunk:
                    break
                fp.write(chunk)
                if on_bytes is not None:
                    on_bytes(len(chunk))
        tmp.rename(target)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def _download_model_sync(
    model_id: str,
    progress: ProgressCallback | None = None,
) -> None:
    """Download all files for *model_id* (blocking).

    *progress(bytes_so_far, total_bytes)* is called periodically.
    Files stored via Git LFS are resolved through the LFS batch API.
    """
    m = _MODELS_BY_ID.get(model_id)
    if m is None:
        raise ValueError(f"Unknown model: {model_id}")

    dest = model_path(model_id)
    dest.mkdir(parents=True, exist_ok=True)

    # First pass: resolve LFS pointers to get total size
    file_infos: list[tuple[str, str, int]] = []  # (fname, url, size)
    total_bytes = 0
    for fname in m.files:
        target = dest / fname
        if target.is_file():
            continue  # already downloaded
        raw_url = f"{_RAW_URL}/{model_id}/v1/{fname}"
        with urllib.request.urlopen(raw_url) as resp:  # noqa: S310
            raw_bytes = resp.read()
        lfs = _resolve_lfs_pointer(raw_bytes)
        if lfs is not None:
            oid, size = lfs
            real_url = _lfs_download_url(oid, size)
            file_infos.append((fname, real_url, size))
            total_bytes += size
        else:
            # Small file — write directly
            target.write_bytes(raw_bytes)

    if not file_infos:
        return

    # Second pass: download with byte-level progress
    downloaded = 0
    if progress is not None:
        progress(0, total_bytes)

    for fname, url, size in file_infos:
        target = dest / fname

        def _on_bytes(n: int) -> None:
            nonlocal downloaded
            downloaded += n
            if progress is not None:
                progress(downloaded, total_bytes)

        _download_file(url, target, expected_size=size, on_bytes=_on_bytes)


def is_streaming_model(model_id: str) -> bool:
    """Return True if *model_id* is a streaming (transducer) model."""
    m = _MODELS_BY_ID.get(model_id)
    return m is not None and m.type == "streaming"


def _sherpa_mode(model_id: str) -> str:
    """Return the sherpa-onnx mode string for *model_id*."""
    return "whisper" if model_id == "whisper-small" else "transducer"


def detect_providers() -> list[tuple[str, str]]:
    """Return available ONNX execution providers as ``(label, value)`` pairs."""
    providers = [("CPU", "cpu")]
    if sys.platform == "darwin":
        providers.append(("CoreML (Apple GPU)", "coreml"))
    else:
        try:
            ctypes.CDLL("libcuda.so.1")
            providers.append(("CUDA (NVIDIA GPU)", "cuda"))
        except OSError:
            pass
    return providers


def build_stt_config(
    model_id: str,
    language: str = "en",
    *,
    translate: bool = False,
    provider: str = "cpu",
):
    """Build a ``SherpaOnnxSTTConfig`` for the given downloaded model."""
    from roomkit.voice.stt.sherpa_onnx import SherpaOnnxSTTConfig

    m = _MODELS_BY_ID.get(model_id)
    if m is None:
        raise ValueError(f"Unknown model: {model_id}")

    d = model_path(model_id)
    mode = _sherpa_mode(model_id)

    if mode == "whisper":
        return SherpaOnnxSTTConfig(
            mode="whisper",
            encoder=str(d / m.files[0]),
            decoder=str(d / m.files[1]),
            tokens=str(d / m.files[2]),
            language=language or "en",
            task="translate" if translate else "transcribe",
            provider=provider,
        )
    # transducer (parakeet-offline, kroko, zipformer)
    # Offline-only transducers need model_type set so the provider knows
    # they don't support streaming (uses OfflineRecognizer instead).
    model_type = "nemo_transducer" if m.type == "offline" else ""
    return SherpaOnnxSTTConfig(
        mode="transducer",
        encoder=str(d / m.files[0]),
        decoder=str(d / m.files[1]),
        joiner=str(d / m.files[2]),
        tokens=str(d / m.files[3]),
        language=language or "en",
        model_type=model_type,
        provider=provider,
    )


async def download_model(
    model_id: str,
    progress: ProgressCallback | None = None,
) -> None:
    """Download model files in a background thread."""
    await asyncio.to_thread(_download_model_sync, model_id, progress)


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


def _download_gtcrn_sync(progress: ProgressCallback | None = None) -> None:
    """Download the GTCRN ONNX model (blocking)."""
    dest = get_models_dir() / GTCRN_MODEL_ID
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / _GTCRN_FILENAME
    if target.is_file():
        return

    downloaded = 0

    def _on_bytes(n: int) -> None:
        nonlocal downloaded
        downloaded += n
        if progress is not None:
            progress(downloaded, total)

    # HEAD request to get total size for progress reporting
    req = urllib.request.Request(GTCRN_URL, method="HEAD")  # noqa: S310
    with urllib.request.urlopen(req) as resp:  # noqa: S310
        total = int(resp.headers.get("Content-Length", 0))

    if progress is not None:
        progress(0, total)

    _download_file(GTCRN_URL, target, expected_size=total, on_bytes=_on_bytes)


async def download_gtcrn(progress: ProgressCallback | None = None) -> None:
    """Download the GTCRN model in a background thread."""
    await asyncio.to_thread(_download_gtcrn_sync, progress)


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


def _download_vad_model_sync(
    model_id: str,
    progress: ProgressCallback | None = None,
) -> None:
    """Download a VAD model (blocking), resolving LFS pointers."""
    m = _VAD_MODELS_BY_ID.get(model_id)
    if m is None:
        raise ValueError(f"Unknown VAD model: {model_id}")

    dest = vad_model_path(model_id)
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / m.onnx_file
    if target.is_file():
        return

    repo_path = _VAD_REPO_PATHS[model_id]
    raw_url = f"{_RAW_URL}/{repo_path}"

    with urllib.request.urlopen(raw_url) as resp:  # noqa: S310
        raw_bytes = resp.read()

    lfs = _resolve_lfs_pointer(raw_bytes)
    if lfs is not None:
        oid, size = lfs
        real_url = _lfs_download_url(oid, size)
        downloaded = 0
        if progress is not None:
            progress(0, size)

        def _on_bytes(n: int) -> None:
            nonlocal downloaded
            downloaded += n
            if progress is not None:
                progress(downloaded, size)

        _download_file(real_url, target, expected_size=size, on_bytes=_on_bytes)
    else:
        total = len(raw_bytes)
        if progress is not None:
            progress(0, total)
        target.write_bytes(raw_bytes)
        if progress is not None:
            progress(total, total)


async def download_vad_model(
    model_id: str,
    progress: ProgressCallback | None = None,
) -> None:
    """Download VAD model in a background thread."""
    await asyncio.to_thread(_download_vad_model_sync, model_id, progress)


def build_vad_config(model_id: str, *, provider: str = "cpu"):
    """Build a ``SherpaOnnxVADConfig`` for the given downloaded VAD model."""
    from roomkit.voice.pipeline.vad.sherpa_onnx import SherpaOnnxVADConfig

    m = _VAD_MODELS_BY_ID.get(model_id)
    if m is None:
        raise ValueError(f"Unknown VAD model: {model_id}")

    d = vad_model_path(model_id)
    return SherpaOnnxVADConfig(
        model=str(d / m.onnx_file),
        model_type=m.type,
        provider=provider,
    )


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


def _generate_tokens_txt(onnx_json_path: Path, tokens_path: Path) -> None:
    """Generate tokens.txt from Piper .onnx.json phoneme_id_map.

    sherpa-onnx expects ``symbol ID`` pairs, one per line (e.g. ``_ 0``).
    """
    config = json.loads(onnx_json_path.read_text())
    phoneme_map: dict[str, list[int]] = config["phoneme_id_map"]
    max_id = max(max(ids) for ids in phoneme_map.values())
    tokens: list[str] = [""] * (max_id + 1)
    for symbol, ids in phoneme_map.items():
        tokens[ids[0]] = symbol
    lines = [f"{tok} {i}" for i, tok in enumerate(tokens)]
    tokens_path.write_text("\n".join(lines) + "\n")


def _download_tts_model_sync(
    model_id: str,
    progress: ProgressCallback | None = None,
) -> None:
    """Download TTS model files (blocking)."""
    m = _TTS_MODELS_BY_ID.get(model_id)
    if m is None:
        raise ValueError(f"Unknown TTS model: {model_id}")

    dest = tts_model_path(model_id)
    dest.mkdir(parents=True, exist_ok=True)

    files_to_download: list[tuple[str, str, int]] = []
    total_bytes = 0

    for fname in (m.onnx_file, m.config_file, "tokens.txt"):
        target = dest / fname
        if target.is_file():
            continue
        raw_url = f"{_RAW_URL}/tts/{model_id}/v1/{fname}"
        try:
            with urllib.request.urlopen(raw_url) as resp:  # noqa: S310
                raw_bytes = resp.read()
        except urllib.error.HTTPError:
            continue  # tokens.txt may not be in repo yet
        lfs = _resolve_lfs_pointer(raw_bytes)
        if lfs is not None:
            oid, size = lfs
            real_url = _lfs_download_url(oid, size)
            files_to_download.append((fname, real_url, size))
            total_bytes += size
        else:
            target.write_bytes(raw_bytes)

    if files_to_download:
        downloaded = 0
        if progress is not None:
            progress(0, total_bytes)

        for fname, url, size in files_to_download:
            target = dest / fname

            def _on_bytes(n: int) -> None:
                nonlocal downloaded
                downloaded += n
                if progress is not None:
                    progress(downloaded, total_bytes)

            _download_file(url, target, expected_size=size, on_bytes=_on_bytes)

    # Fallback: generate tokens.txt from .onnx.json if not downloaded
    json_path = dest / m.config_file
    tokens_path = dest / "tokens.txt"
    if json_path.is_file() and not tokens_path.is_file():
        _generate_tokens_txt(json_path, tokens_path)


async def download_tts_model(
    model_id: str,
    progress: ProgressCallback | None = None,
) -> None:
    """Download TTS model files in a background thread."""
    await asyncio.to_thread(_download_tts_model_sync, model_id, progress)


def _list_gh_tree(path: str) -> list[dict]:
    """Recursively list files under *path* via GitHub Contents API."""
    url = f"{_GH_API_URL}/{path}"
    req = urllib.request.Request(url)  # noqa: S310
    req.add_header("Accept", "application/vnd.github.v3+json")
    with urllib.request.urlopen(req) as resp:  # noqa: S310
        entries = json.loads(resp.read())
    files: list[dict] = []
    for entry in entries:
        if entry["type"] == "file":
            files.append(entry)
        elif entry["type"] == "dir":
            files.extend(_list_gh_tree(entry["path"]))
    return files


def _download_espeak_ng_sync(
    progress: ProgressCallback | None = None,
) -> None:
    """Download espeak-ng-data directory from edge-ai-models (blocking)."""
    dest = espeak_ng_data_path()
    if dest.is_dir() and (dest / "phontab").is_file():
        return

    # Enumerate all files via GitHub API
    entries = _list_gh_tree("tts/espeak-ng-data")
    total_bytes = sum(e.get("size", 0) for e in entries)
    downloaded = 0

    if progress is not None:
        progress(0, total_bytes)

    for entry in entries:
        # entry["path"] is like "tts/espeak-ng-data/lang/roa/fr"
        rel = entry["path"].removeprefix("tts/espeak-ng-data/")
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)

        if target.is_file():
            downloaded += entry.get("size", 0)
            if progress is not None:
                progress(downloaded, total_bytes)
            continue

        raw_url = entry.get("download_url") or f"{_RAW_URL}/{entry['path']}"
        with urllib.request.urlopen(raw_url) as resp:  # noqa: S310
            data = resp.read()
        target.write_bytes(data)

        downloaded += entry.get("size", 0)
        if progress is not None:
            progress(downloaded, total_bytes)


async def download_espeak_ng_data(
    progress: ProgressCallback | None = None,
) -> None:
    """Download espeak-ng-data in a background thread."""
    await asyncio.to_thread(_download_espeak_ng_sync, progress)


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
    "https://github.com/k2-fsa/sherpa-onnx/releases/download"
    "/speaker-recongition-models"
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


def _download_speaker_model_sync(
    model_id: str,
    progress: ProgressCallback | None = None,
) -> None:
    """Download a speaker embedding model (blocking)."""
    m = _SPEAKER_MODELS_BY_ID.get(model_id)
    if m is None:
        raise ValueError(f"Unknown speaker model: {model_id}")

    dest = speaker_model_path(model_id)
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / m.onnx_file
    if target.is_file():
        return

    asset_url = _SPEAKER_ASSET_URLS.get(model_id)
    if asset_url is None:
        raise ValueError(f"No download URL for speaker model: {model_id}")

    # HEAD request for content-length
    req = urllib.request.Request(asset_url, method="HEAD")  # noqa: S310
    with urllib.request.urlopen(req) as resp:  # noqa: S310
        total = int(resp.headers.get("Content-Length", 0))

    downloaded = 0
    if progress is not None:
        progress(0, total)

    def _on_bytes(n: int) -> None:
        nonlocal downloaded
        downloaded += n
        if progress is not None:
            progress(downloaded, total)

    _download_file(asset_url, target, expected_size=total, on_bytes=_on_bytes)


async def download_speaker_model(
    model_id: str,
    progress: ProgressCallback | None = None,
) -> None:
    """Download speaker embedding model in a background thread."""
    await asyncio.to_thread(_download_speaker_model_sync, model_id, progress)


def build_diarization_config(model_id: str, *, provider: str = "cpu", threshold: float = 0.4):
    """Build a ``SherpaOnnxDiarizationConfig`` for the given downloaded model."""
    from roomkit.voice.pipeline.diarization.sherpa_onnx import SherpaOnnxDiarizationConfig

    m = _SPEAKER_MODELS_BY_ID.get(model_id)
    if m is None:
        raise ValueError(f"Unknown speaker model: {model_id}")

    d = speaker_model_path(model_id)
    return SherpaOnnxDiarizationConfig(
        model=str(d / m.onnx_file),
        provider=provider,
        search_threshold=threshold,
    )


# ---------------------------------------------------------------------------
# TTS config builder
# ---------------------------------------------------------------------------


def build_tts_config(
    model_id: str,
    *,
    provider: str = "cpu",
):
    """Build a ``SherpaOnnxTTSConfig`` for the given downloaded TTS model."""
    from roomkit.voice.tts.sherpa_onnx import SherpaOnnxTTSConfig

    m = _TTS_MODELS_BY_ID.get(model_id)
    if m is None:
        raise ValueError(f"Unknown TTS model: {model_id}")

    d = tts_model_path(model_id)
    return SherpaOnnxTTSConfig(
        model=str(d / m.onnx_file),
        tokens=str(d / "tokens.txt"),
        data_dir=str(espeak_ng_data_path()),
        sample_rate=m.sample_rate,
        provider=provider,
    )
