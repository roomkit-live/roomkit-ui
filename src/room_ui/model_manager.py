"""Download and manage local STT models from edge-ai-models."""

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
_LFS_BATCH_URL = (
    "https://github.com/anganyAI/edge-ai-models.git/info/lfs/objects/batch"
)

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
    return obj["actions"]["download"]["href"]


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
