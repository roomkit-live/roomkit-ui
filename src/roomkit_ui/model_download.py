"""Download infrastructure for local models (raw GitHub, Git LFS, release assets)."""

from __future__ import annotations

import hashlib
import json
import urllib.request
from collections.abc import Callable
from pathlib import Path

from roomkit_ui.model_catalog import (
    _GTCRN_FILENAME,
    _MODELS_BY_ID,
    _SMART_TURN_FILENAME,
    _SPEAKER_ASSET_URLS,
    _SPEAKER_MODELS_BY_ID,
    _TTS_MODELS_BY_ID,
    _VAD_MODELS_BY_ID,
    _VAD_REPO_PATHS,
    GTCRN_MODEL_ID,
    GTCRN_URL,
    SMART_TURN_MODEL_ID,
    SMART_TURN_URL,
    espeak_ng_data_path,
    get_models_dir,
    model_path,
    speaker_model_path,
    tts_model_path,
    vad_model_path,
)

_RAW_URL = "https://raw.githubusercontent.com/anganyAI/edge-ai-models/main"
_LFS_BATCH_URL = "https://github.com/anganyAI/edge-ai-models.git/info/lfs/objects/batch"
_GH_API_URL = "https://api.github.com/repos/anganyAI/edge-ai-models/contents"

# Progress callback: (bytes_downloaded, total_bytes)
ProgressCallback = Callable[[int, int], None]


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
    expected_sha256: str | None = None,
) -> None:
    """Download *url* to *target* atomically, reporting bytes via *on_bytes*.

    Integrity: when *expected_size* is non-zero the byte count must match,
    and when *expected_sha256* is given (the Git LFS OID) the digest must
    match — otherwise the partial file is removed and RuntimeError raised.
    """
    tmp = target.with_suffix(target.suffix + ".part")
    hasher = hashlib.sha256() if expected_sha256 else None
    received = 0
    try:
        req = urllib.request.Request(url)  # noqa: S310
        with urllib.request.urlopen(req) as resp, open(tmp, "wb") as fp:  # noqa: S310
            while True:
                chunk = resp.read(_CHUNK)
                if not chunk:
                    break
                fp.write(chunk)
                received += len(chunk)
                if hasher is not None:
                    hasher.update(chunk)
                if on_bytes is not None:
                    on_bytes(len(chunk))
        if expected_size and received != expected_size:
            raise RuntimeError(
                f"size mismatch for {target.name}: expected {expected_size}, got {received}"
            )
        if hasher is not None and hasher.hexdigest() != expected_sha256:
            raise RuntimeError(f"sha256 mismatch for {target.name}: download corrupted")
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
    file_infos: list[tuple[str, str, int, str]] = []  # (fname, url, size, oid)
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
            file_infos.append((fname, real_url, size, oid))
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

    for fname, url, size, oid in file_infos:
        target = dest / fname

        def _on_bytes(n: int) -> None:
            nonlocal downloaded
            downloaded += n
            if progress is not None:
                progress(downloaded, total_bytes)

        _download_file(url, target, expected_size=size, on_bytes=_on_bytes, expected_sha256=oid)


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

        _download_file(
            real_url, target, expected_size=size, on_bytes=_on_bytes, expected_sha256=oid
        )
    else:
        total = len(raw_bytes)
        if progress is not None:
            progress(0, total)
        target.write_bytes(raw_bytes)
        if progress is not None:
            progress(total, total)


def _download_smart_turn_sync(progress: ProgressCallback | None = None) -> None:
    """Download the smart-turn ONNX model (blocking)."""
    dest = get_models_dir() / SMART_TURN_MODEL_ID
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / _SMART_TURN_FILENAME
    if target.is_file():
        return

    downloaded = 0

    def _on_bytes(n: int) -> None:
        nonlocal downloaded
        downloaded += n
        if progress is not None:
            progress(downloaded, total)

    req = urllib.request.Request(SMART_TURN_URL, method="HEAD")  # noqa: S310
    with urllib.request.urlopen(req) as resp:  # noqa: S310
        total = int(resp.headers.get("Content-Length", 0))

    if progress is not None:
        progress(0, total)

    _download_file(SMART_TURN_URL, target, expected_size=total, on_bytes=_on_bytes)


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

    files_to_download: list[tuple[str, str, int, str]] = []
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
            files_to_download.append((fname, real_url, size, oid))
            total_bytes += size
        else:
            target.write_bytes(raw_bytes)

    if files_to_download:
        downloaded = 0
        if progress is not None:
            progress(0, total_bytes)

        for fname, url, size, oid in files_to_download:
            target = dest / fname

            def _on_bytes(n: int) -> None:
                nonlocal downloaded
                downloaded += n
                if progress is not None:
                    progress(downloaded, total_bytes)

            _download_file(
                url, target, expected_size=size, on_bytes=_on_bytes, expected_sha256=oid
            )

    # Fallback: generate tokens.txt from .onnx.json if not downloaded
    json_path = dest / m.config_file
    tokens_path = dest / "tokens.txt"
    if json_path.is_file() and not tokens_path.is_file():
        _generate_tokens_txt(json_path, tokens_path)


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
