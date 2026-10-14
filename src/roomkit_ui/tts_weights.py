"""Weights a local TTS loads from Hugging Face at its first warmup, fetched ahead.

Vui and Pocket TTS download their models the first time a session warms them
up: gigabytes, at the moment the user wants to talk.  Models & components
fetches them before, into the Hugging Face cache the libraries read, through
huggingface_hub (both depend on it): the layout it writes is the one they
look up, so a session after a fetch makes no download.

TODO(RMK-745): which files a session loads is the libraries' knowledge.  roomkit
will expose ``prefetch(config)`` / ``is_prefetched(config)`` on its local TTS
providers; once a roomkit release carries them, replace ``VUI_WEIGHTS``,
``VUI_CLONING_WEIGHTS``, ``_POCKET_VOICE_URI`` and ``pocket_weights`` with those
calls.  Until then the Vui lists mirror vui-tts 1.2.3 and Pocket's URIs are
read from the configs pocket-tts ships.
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import os
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from roomkit_ui.download_flight import single_flight
from roomkit_ui.features import is_available, require
from roomkit_ui.gguf_models import hub_cache, repo_dir
from roomkit_ui.tts import pocket
from roomkit_ui.tts.vui import PRESETS

logger = logging.getLogger(__name__)

Progress = Callable[[int, int], None]


@dataclass(frozen=True)
class HubWeights:
    """Files of one Hugging Face repository a library loads."""

    repo_id: str
    files: tuple[str, ...]  # checked; fetched too unless the library takes the whole repo
    revision: str | None = None  # None: the repository's main, as the library asks for it
    whole: bool = False  # the library snapshots the whole repository: so does the fetch


# vui-tts 1.2.3 with roomkit's default checkpoint (VuiTTSConfig.checkpoint).
_VUI_CHECKPOINT = "vui-nano-1.1"
VUI_WEIGHTS = (
    HubWeights(
        "fluxions/vui",
        (
            f"{_VUI_CHECKPOINT}.safetensors",
            *(f"prompts/{_VUI_CHECKPOINT}/{voice}.safetensors" for voice in PRESETS),
        ),
    ),
    HubWeights("Qwen/Qwen3-TTS-Tokenizer-12Hz", ("model.safetensors",), whole=True),  # codec
    HubWeights("HuggingFaceTB/SmolLM2-135M", ("tokenizer.json",), whole=True),  # base tokenizer
)
# The speaker encoder Vui runs on a clip to clone the voice in it.
VUI_CLONING_WEIGHTS = (
    HubWeights("Qwen/Qwen3-TTS-12Hz-0.6B-Base", ("model.safetensors",), whole=True),
)

# pocket-tts 3.3's get_predefined_voice: a pre-made voice is an embedding per language.
_POCKET_VOICE_URI = (
    "hf://kyutai/pocket-tts-without-voice-cloning/languages/{language}/embeddings/"
    "{voice}.safetensors@4e1e0a3e611c51c0b4ed8174fc10f32a54644303"
)
_HF_URI = re.compile(r"hf://([\w.-]+/[\w.-]+)/(\S+?)(?:@([0-9a-f]{40}))?")
_CONFIG_LINE = re.compile(
    r"^\s*(weights_path|weights_path_without_voice_cloning|tokenizer_path):\s*(hf://\S+)\s*$",
    re.MULTILINE,
)


def weights_for(key: str, settings: dict | None = None) -> tuple[HubWeights, ...]:
    """The weights of *key* ("vui", "vui-cloning", "pocket"); Pocket's follow *settings*."""
    if key == "vui":
        return VUI_WEIGHTS
    if key == "vui-cloning":
        return VUI_CLONING_WEIGHTS
    if key == "pocket":
        return pocket_weights(settings or {})
    raise ValueError(f"Unknown TTS weights: {key!r}")


def feature_of(key: str) -> str:
    return "pocket-tts" if key == "pocket" else "vui"


def pocket_weights(settings: dict) -> tuple[HubWeights, ...]:
    """What Pocket loads for the language and voice of *settings*.

    Its tokenizer, then the weights that clone a voice when the voice is a
    clip (kyutai/pocket-tts, gated), else the others and the pre-made voice's
    embedding.  With access to the gated weights Pocket tries those first even
    for a pre-made voice; without it, it falls back to what is fetched here.
    """
    language = pocket.model_language(settings)
    voice = pocket.voice_for(settings, language)
    config = _pocket_config(language)
    clip = "/" in voice or os.sep in voice
    uris = [
        config["tokenizer_path"],
        config["weights_path" if clip else "weights_path_without_voice_cloning"],
    ]
    if not clip:
        uris.append(_POCKET_VOICE_URI.format(language=language, voice=voice))
    return tuple(_from_uri(uri) for uri in uris)


def _pocket_config(language: str) -> dict[str, str]:
    """The hf:// URIs pocket-tts's own config for *language* names."""
    if not re.fullmatch(r"[a-z0-9_-]+", language):
        raise ValueError(f"{language!r} is not a Pocket TTS language.")
    spec = importlib.util.find_spec("pocket_tts")  # locates it without importing torch
    if spec is None or not spec.submodule_search_locations:
        raise ValueError("Pocket TTS is not installed.")
    path = Path(next(iter(spec.submodule_search_locations))) / "config" / f"{language}.yaml"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Pocket TTS has no {language} model.") from exc
    return dict(_CONFIG_LINE.findall(text))


def _from_uri(uri: str) -> HubWeights:
    match = _HF_URI.fullmatch(uri)
    if match is None:
        raise ValueError(f"{uri!r} is not a Hugging Face file.")
    repo_id, path, revision = match.groups()
    return HubWeights(repo_id, (path,), revision)


def is_downloaded(key: str) -> bool:
    """Whether every file *key* loads is in the cache (False without its component)."""
    if not is_available(feature_of(key)):
        return False
    try:
        weights = weights_for(key, pocket_settings() if key == "pocket" else None)
    except ValueError:
        return False
    from huggingface_hub import try_to_load_from_cache

    cache = hub_cache()  # the app's, read now: huggingface_hub fixes its own at import
    return all(
        isinstance(
            try_to_load_from_cache(w.repo_id, name, cache_dir=cache, revision=w.revision), str
        )
        for w in weights
        for name in w.files
    )


async def download(key: str, progress: Progress | None = None) -> None:
    """Fetch what *key* loads, in a worker thread."""
    require(feature_of(key))
    await asyncio.to_thread(_download_sync, key, progress)


@single_flight
def _download_sync(key: str, progress: Progress | None = None) -> None:
    weights = weights_for(key, pocket_settings() if key == "pocket" else None)
    token = _huggingface_token()
    from huggingface_hub import hf_hub_download

    plan = _plan(weights, token)
    total = sum(size for *_, size in plan)
    done = 0
    if progress is not None:
        progress(0, total)
    cache = hub_cache()
    for repo_id, name, revision, size in plan:
        hf_hub_download(repo_id, name, revision=revision, token=token, cache_dir=cache)
        done += size
        if progress is not None:
            progress(done, total)


def _plan(
    weights: tuple[HubWeights, ...], token: str | None
) -> list[tuple[str, str, str | None, int]]:
    """Each file to fetch with its size: a whole repository's, or the named ones."""
    from huggingface_hub import HfApi

    api = HfApi(token=token)
    plan: list[tuple[str, str, str | None, int]] = []
    for w in weights:
        if w.whole:
            info = api.model_info(w.repo_id, revision=w.revision, files_metadata=True)
            sizes = {s.rfilename: s.size or 0 for s in info.siblings or ()}
        else:
            paths = api.get_paths_info(w.repo_id, list(w.files), revision=w.revision)
            sizes = {p.path: getattr(p, "size", 0) or 0 for p in paths}
            missing = set(w.files) - set(sizes)
            if missing:
                raise ValueError(f"{w.repo_id} has no {', '.join(sorted(missing))}.")
        plan += [(w.repo_id, name, w.revision, size) for name, size in sorted(sizes.items())]
    return plan


def delete(key: str) -> None:
    """Remove what *key* fetched: a whole repository's cache, or its named files.

    A repository other models share (the Qwen codec Qwen3-TTS loads too) is
    fetched again by whichever needs it next.
    """
    weights = weights_for(key, pocket_settings() if key == "pocket" else None)
    for w in weights:
        root = repo_dir(w.repo_id)
        if w.whole:
            shutil.rmtree(root, ignore_errors=True)
            continue
        for name in w.files:
            _remove_cached_file(root, name, w.revision)


def _remove_cached_file(root: Path, name: str, revision: str | None) -> None:
    """Drop one file's link in the snapshot and the blob it points at."""
    commit = revision or _main_commit(root)
    if not commit:
        return
    snapshot = root / "snapshots" / commit
    link = snapshot / name
    if not Path(os.path.normpath(link)).is_relative_to(snapshot):
        return  # a name from a list is data: never a path out of the cache
    blob = link.resolve() if link.is_symlink() else None
    link.unlink(missing_ok=True)
    if blob is not None and blob.is_relative_to(root / "blobs"):
        blob.unlink(missing_ok=True)


def _main_commit(root: Path) -> str:
    try:
        return (root / "refs" / "main").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def pocket_settings() -> dict:
    """The saved choices Pocket's files follow, read without the keyring."""
    from roomkit_ui.settings import load_setting

    return {key: load_setting(key) for key in _POCKET_KEYS}


_POCKET_KEYS = ("vc_pocket_language", "vc_pocket_voice", "stt_language")


def _huggingface_token() -> str | None:
    """The token of Providers & keys, else huggingface_hub's own (HF_TOKEN, a login):
    the gated Pocket weights that clone a voice need one."""
    from roomkit_ui.settings import load_settings

    return str(load_settings().get("huggingface_token", "") or "").strip() or None
