"""Vui's and Pocket's weights, fetched before a session into the Hugging Face cache."""

from types import SimpleNamespace

import pytest

from roomkit_ui import tts_weights
from roomkit_ui.widgets.settings import model_library

pytest.importorskip("huggingface_hub")

_POCKET_CONFIG = """\
weights_path: hf://kyutai/pocket-tts/languages/french/model.safetensors@{gated}
weights_path_without_voice_cloning: hf://kyutai/pocket-tts-without-voice-cloning/languages/french/model.safetensors@{open}
flow_lm:
  lookup_table:
    tokenizer: tokenizers
    tokenizer_path: hf://kyutai/pocket-tts-without-voice-cloning/languages/french/tokenizer.json@{open}
"""  # noqa: E501
_GATED, _OPEN = "a" * 40, "b" * 40
_FRENCH = {"vc_pocket_language": "french", "vc_pocket_voice": "", "stt_language": "fr"}


@pytest.fixture
def pocket_package(tmp_path, monkeypatch):
    """A pocket_tts package holding its French config, found without importing it."""
    package = tmp_path / "pocket_tts"
    (package / "config").mkdir(parents=True)
    (package / "config" / "french.yaml").write_text(
        _POCKET_CONFIG.format(gated=_GATED, open=_OPEN)
    )
    spec = SimpleNamespace(submodule_search_locations=[str(package)])
    real = tts_weights.importlib.util.find_spec
    monkeypatch.setattr(
        tts_weights.importlib.util,
        "find_spec",
        lambda name, *a: spec if name == "pocket_tts" else real(name, *a),
    )


@pytest.fixture
def installed(monkeypatch):
    monkeypatch.setattr(tts_weights, "is_available", lambda _feature: True)
    monkeypatch.setattr(tts_weights, "require", lambda _feature: None)


def _cache(tmp_path, repo, files, commit="c" * 40, *, main=True):
    """Lay *files* out in the hub cache as huggingface_hub does (HF_HUB_CACHE: conftest)."""
    root = tmp_path / "hf-hub" / ("models--" + repo.replace("/", "--"))
    for name in files:
        blob = root / "blobs" / f"blob-{abs(hash((commit, name)))}"
        blob.parent.mkdir(parents=True, exist_ok=True)
        blob.write_bytes(b"x")
        link = root / "snapshots" / commit / name
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(blob)
    if main:
        (root / "refs").mkdir(parents=True, exist_ok=True)
        (root / "refs" / "main").write_text(commit)
    return root


# -- what each one loads -------------------------------------------------------------


def test_a_premade_pocket_voice_takes_the_open_weights_and_its_embedding(pocket_package):
    weights = tts_weights.pocket_weights(_FRENCH)

    assert [(w.repo_id, w.files[0], w.revision) for w in weights] == [
        ("kyutai/pocket-tts-without-voice-cloning", "languages/french/tokenizer.json", _OPEN),
        ("kyutai/pocket-tts-without-voice-cloning", "languages/french/model.safetensors", _OPEN),
        (
            "kyutai/pocket-tts-without-voice-cloning",
            "languages/french/embeddings/estelle.safetensors",
            "4e1e0a3e611c51c0b4ed8174fc10f32a54644303",
        ),
    ]


def test_a_clip_to_clone_takes_the_gated_weights_and_no_embedding(pocket_package, tmp_path):
    weights = tts_weights.pocket_weights({**_FRENCH, "vc_pocket_voice": str(tmp_path / "me.wav")})

    assert [(w.repo_id, w.files[0]) for w in weights] == [
        ("kyutai/pocket-tts-without-voice-cloning", "languages/french/tokenizer.json"),
        ("kyutai/pocket-tts", "languages/french/model.safetensors"),
    ]


def test_a_language_name_is_never_a_path(pocket_package):
    with pytest.raises(ValueError, match="not a Pocket TTS language"):
        tts_weights.pocket_weights({**_FRENCH, "vc_pocket_language": "../../etc"})


# -- in the cache or not -----------------------------------------------------------


def _vui_cache(tmp_path):
    commit = "d" * 40
    for weights in tts_weights.VUI_WEIGHTS:
        _cache(tmp_path, weights.repo_id, weights.files, commit)


def test_vui_is_downloaded_once_every_file_it_loads_is_cached(tmp_path, installed):
    _vui_cache(tmp_path)
    assert tts_weights.is_downloaded("vui")

    fluxions = tmp_path / "hf-hub" / "models--fluxions--vui"
    next(fluxions.glob("snapshots/*/prompts/vui-nano-1.1/rhian.safetensors")).unlink()

    assert not tts_weights.is_downloaded("vui")


def test_nothing_counts_as_downloaded_without_its_component(tmp_path, monkeypatch):
    _vui_cache(tmp_path)
    monkeypatch.setattr(tts_weights, "is_available", lambda _feature: False)

    assert not tts_weights.is_downloaded("vui")


# -- fetching ----------------------------------------------------------------------


class _Hub:
    """huggingface_hub as the fetch uses it: the listings, then one file at a time."""

    def __init__(self, monkeypatch):
        import huggingface_hub

        self.fetched: list[tuple[str, str, str | None, str | None]] = []
        hub = self

        class Api:
            def __init__(self, token=None):
                hub.token = token

            def model_info(self, repo_id, revision=None, files_metadata=False):
                files = ("model.safetensors", "config.json")
                return SimpleNamespace(
                    siblings=[SimpleNamespace(rfilename=f, size=10) for f in files]
                )

            def get_paths_info(self, repo_id, paths, revision=None):
                return [SimpleNamespace(path=p, size=5) for p in paths]

        def download(repo_id, filename, revision=None, token=None, cache_dir=None):
            hub.fetched.append((repo_id, filename, revision, token))
            return "/cache/" + filename

        monkeypatch.setattr(huggingface_hub, "HfApi", Api)
        monkeypatch.setattr(huggingface_hub, "hf_hub_download", download)


async def test_a_fetch_takes_whole_repositories_and_named_files_with_progress(
    installed, monkeypatch
):
    hub = _Hub(monkeypatch)
    monkeypatch.setattr(tts_weights, "_huggingface_token", lambda: "hf_test")
    seen: list[tuple[int, int]] = []

    await tts_weights.download("vui", lambda done, total: seen.append((done, total)))

    named = len(tts_weights.VUI_WEIGHTS[0].files)
    assert len(hub.fetched) == named + 2 + 2  # fluxions' files, two whole repos of two
    assert ("Qwen/Qwen3-TTS-Tokenizer-12Hz", "config.json", None, "hf_test") in hub.fetched
    total = named * 5 + 4 * 10
    assert seen[0] == (0, total) and seen[-1] == (total, total)
    assert hub.token == "hf_test"


async def test_a_fetch_needs_its_component(monkeypatch):
    from roomkit_ui.features import FeatureUnavailableError

    def missing(feature):
        raise FeatureUnavailableError("Vui is not installed.", feature)

    monkeypatch.setattr(tts_weights, "require", missing)

    with pytest.raises(FeatureUnavailableError):
        await tts_weights.download("vui")


# -- deleting ----------------------------------------------------------------------


def test_delete_removes_whole_repositories_and_only_the_named_files(
    tmp_path, pocket_package, monkeypatch
):
    monkeypatch.setattr(tts_weights, "pocket_settings", lambda: _FRENCH)
    repo = "kyutai/pocket-tts-without-voice-cloning"
    root = _cache(tmp_path, repo, ["languages/french/tokenizer.json"], _OPEN, main=False)
    other = _cache(tmp_path, repo, ["languages/german/tokenizer.json"], _OPEN, main=False)
    whole = _cache(tmp_path, "Qwen/Qwen3-TTS-Tokenizer-12Hz", ["model.safetensors"])

    tts_weights.delete("pocket")
    tts_weights.delete("vui")

    assert not (root / "snapshots" / _OPEN / "languages/french/tokenizer.json").exists()
    assert (other / "snapshots" / _OPEN / "languages/german/tokenizer.json").exists()
    assert not whole.exists()


def test_a_cache_reached_through_a_link_loses_its_blob_too(tmp_path):
    """Before: resolve() followed the link to the cache as well, the blob was
    outside the unresolved root, and its hundreds of MB stayed on disk."""
    real = _cache(tmp_path / "drive", "kyutai/pocket-tts", ["model.safetensors"])
    blob = (real / "snapshots" / ("c" * 40) / "model.safetensors").resolve()
    linked = tmp_path / "linked"
    linked.symlink_to(real)

    tts_weights._remove_cached_file(linked, "model.safetensors", None)

    assert not blob.exists()


# -- in Models & components --------------------------------------------------------


def test_the_library_offers_them_and_names_pockets_language(pocket_package, monkeypatch):
    monkeypatch.setattr(tts_weights, "pocket_settings", lambda: _FRENCH)

    rows = {row.id: row for row in model_library.tts_weight_models()}

    assert set(rows) == {"tts-weights-vui", "tts-weights-vui-cloning", "tts-weights-pocket"}
    assert "French" in rows["tts-weights-pocket"].detail
