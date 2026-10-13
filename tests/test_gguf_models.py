"""llama.cpp models from Hugging Face: listings, the cache llama-server reads,
downloads held to their SHA-256, and whether a model fits this computer."""

from __future__ import annotations

import hashlib
import os
import threading
from pathlib import Path

import httpx
import pytest

from roomkit_ui import gguf_models as hub
from roomkit_ui.providers.llamacpp import local_model

COMMIT = "a" * 40
REPO = "acme/Tiny-GGUF"


def _sibling(name: str, data: bytes | None = None, *, size: int = 0, sha: str = "") -> dict:
    if data is not None:
        size, sha = len(data), hashlib.sha256(data).hexdigest()
    return {"rfilename": name, "size": size, "lfs": {"sha256": sha, "size": size}}


def _layout(cache: Path, repo: str, files: dict[str, bytes], *, commit: str = COMMIT) -> Path:
    """The cache as huggingface_hub and llama-server leave it."""
    root = hub.repo_dir(repo, cache)
    for name, data in files.items():
        blob = root / "blobs" / hashlib.sha256(data).hexdigest()
        blob.parent.mkdir(parents=True, exist_ok=True)
        blob.write_bytes(data)
        link = root / "snapshots" / commit / name
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(os.path.relpath(blob, link.parent))
    (root / "refs").mkdir(parents=True, exist_ok=True)
    (root / "refs" / "main").write_text(commit)
    return root


@pytest.mark.parametrize(
    ("stem", "quant"),
    [
        ("Qwen3-4B-Instruct-2507-Q4_K_M", "Q4_K_M"),
        ("Qwen3-4B-Instruct-2507-UD-Q4_K_XL", "UD-Q4_K_XL"),
        ("LFM2.5-1.2B-Instruct-QAD-Q4_0", "QAD-Q4_0"),
        ("gpt-oss-20b-MXFP4", "MXFP4"),
        ("Llama-3.2-3B-Instruct-IQ4_XS", "IQ4_XS"),
        ("qwen2.5-7b-instruct-q4_k_m", "q4_k_m"),
        ("gemma-3-4b-it-BF16", "BF16"),
        ("model.Q8_0", "Q8_0"),
        ("Qwen3-8B-Q4_K_M-00001-of-00002", "Q4_K_M"),
        ("no-quant-here", "no-quant-here"),
    ],
)
def test_a_file_name_gives_its_quantization(stem, quant):
    assert hub.quant_label(stem) == quant


def test_a_listing_becomes_its_quantizations_smallest_first():
    siblings = [
        _sibling("README.md", b"x"),
        _sibling("M-Q8_0.gguf", b"8" * 80),
        _sibling("M-Q4_K_M.gguf", b"4" * 40),
        _sibling("mmproj-M-F16.gguf", b"v" * 10),  # a vision projector, no model
        _sibling("M-F16.gguf", size=160),  # no SHA-256: it could not be checked
        _sibling("big/M-Q2_K-00001-of-00002.gguf", b"a" * 20),
        _sibling("big/M-Q2_K-00002-of-00002.gguf", b"b" * 20),
        _sibling("M-Q3_K-00001-of-00002.gguf", b"c" * 20),  # its second part is missing
    ]
    quants = hub.group_quants(REPO, siblings)
    assert [(q.quant, q.size) for q in quants] == [("Q4_K_M", 40), ("Q2_K", 40), ("Q8_0", 80)]
    split = quants[1]
    assert [p.name for p in split.parts] == [
        "big/M-Q2_K-00001-of-00002.gguf",
        "big/M-Q2_K-00002-of-00002.gguf",
    ]
    assert split.reference == f"{REPO}:Q2_K"


async def test_search_asks_for_llama_cpp_models_no_larger_than_the_machine_runs():
    seen: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json=[
                {
                    "id": "acme/Small-GGUF",
                    "downloads": 1200,
                    "gated": "manual",
                    "gguf": {"total": 4_000_000_000, "chat_template": "{% if tools %}…"},
                },
                {"id": "../escape", "downloads": 1},
            ],
        )

    client = hub.HubClient("hf_secret", transport=httpx.MockTransport(answer))
    models = await client.search("qwen", max_params=14_200_000_000)
    params = seen[0].url.params
    assert params["apps"] == "llama.cpp"
    assert params["pipeline_tag"] == "text-generation"
    assert params["num_parameters"] == "min:0,max:14.2B"
    assert params["search"] == "qwen"
    assert params.get_list("expand[]") == ["gguf", "downloads", "gated"]
    assert seen[0].headers["Authorization"] == "Bearer hf_secret"
    assert models == [hub.HubModel("acme/Small-GGUF", 4_000_000_000, 1200, True, True, "")]


async def test_a_repository_reads_its_commit_and_quantizations():
    def answer(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/api/models/{REPO}/revision/main"
        assert request.url.params["blobs"] == "true"
        return httpx.Response(
            200,
            json={
                "sha": COMMIT,
                "gated": False,
                "gguf": {"total": 1_000_000_000, "architecture": "qwen3"},
                "siblings": [_sibling("T-Q4_K_M.gguf", b"q" * 8)],
            },
        )

    info = await hub.HubClient(transport=httpx.MockTransport(answer)).repo(REPO)
    assert info.commit == COMMIT
    assert info.model.architecture == "qwen3"
    assert info.quant("q4_k_m") is info.quants[0]


@pytest.mark.parametrize(
    ("status", "token", "words"),
    [
        (401, "", "add an access token"),
        (401, "hf_x", "refused the access token"),
        (403, "hf_x", "gated"),
        (404, "", "no such model"),
    ],
)
async def test_a_refusal_says_what_to_do(status, token, words):
    client = hub.HubClient(token, transport=httpx.MockTransport(lambda _r: httpx.Response(status)))
    with pytest.raises(hub.HubError, match=words):
        await client.repo(REPO)


async def test_a_repository_name_is_checked_before_any_request():
    client = hub.HubClient(transport=httpx.MockTransport(_no_request))
    with pytest.raises(hub.HubError):
        await client.repo("../../etc")


def _file(data: bytes, name: str = "T-Q4_K_M.gguf") -> hub.GGUFFile:
    part = hub.GGUFPart(name, len(data), hashlib.sha256(data).hexdigest())
    return hub.GGUFFile(REPO, "Q4_K_M", (part,))


def _serving(data: bytes, seen: list[httpx.Request] | None = None, *, ranges: bool = True):
    """huggingface.co redirecting to its CDN, which serves *data*."""

    def answer(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if request.url.host == "huggingface.co":
            return httpx.Response(302, headers={"Location": "https://cdn.example/blob"})
        start = request.headers.get("Range", "bytes=0-")[6:-1]
        if ranges and start:
            return httpx.Response(206, content=data[int(start) :])
        return httpx.Response(200, content=data)

    return httpx.MockTransport(answer)


def test_a_download_lands_in_the_cache_as_llama_server_finds_it(tmp_path):
    data = b"GGUF" + bytes(range(256)) * 64
    seen: list[httpx.Request] = []
    reports: list[tuple[int, int]] = []
    path = hub.download(
        _file(data),
        COMMIT,
        token="hf_secret",
        progress=lambda done, total: reports.append((done, total)),
        cache=tmp_path,
        transport=_serving(data, seen),
    )
    root = hub.repo_dir(REPO, tmp_path)
    blob = root / "blobs" / hashlib.sha256(data).hexdigest()
    assert path == root / "snapshots" / COMMIT / "T-Q4_K_M.gguf"
    assert path.is_symlink() and path.resolve() == blob.resolve()
    assert path.read_bytes() == data
    assert (root / "refs" / "main").read_text() == COMMIT
    assert reports[0] == (0, len(data)) and reports[-1] == (len(data), len(data))
    # The token goes to Hugging Face, never to the CDN it redirects to.
    assert seen[0].url.path == f"/{REPO}/resolve/{COMMIT}/T-Q4_K_M.gguf"
    assert seen[0].headers["Authorization"] == "Bearer hf_secret"
    assert "Authorization" not in seen[1].headers
    assert hub.resolve(f"{REPO}:Q4_K_M", tmp_path) == path

    # Already there: nothing is asked for again.
    again = hub.download(
        _file(data), COMMIT, cache=tmp_path, transport=httpx.MockTransport(_no_request)
    )
    assert again == path


def test_a_damaged_download_is_discarded(tmp_path):
    data = b"real model"
    with pytest.raises(hub.HubError, match="damaged"):
        hub.download(_file(data), COMMIT, cache=tmp_path, transport=_serving(b"tampered!!"))
    root = hub.repo_dir(REPO, tmp_path)
    assert not list((root / "blobs").glob("*"))
    assert hub.resolve(f"{REPO}:Q4_K_M", tmp_path) is None


@pytest.mark.parametrize("ranges", [True, False])
def test_an_interrupted_download_resumes(tmp_path, ranges):
    data = bytes(range(256)) * 32
    sha = hashlib.sha256(data).hexdigest()
    partial = hub.repo_dir(REPO, tmp_path) / "blobs" / f"{sha}.incomplete"
    partial.parent.mkdir(parents=True)
    partial.write_bytes(data[:1000])
    seen: list[httpx.Request] = []
    path = hub.download(
        _file(data), COMMIT, cache=tmp_path, transport=_serving(data, seen, ranges=ranges)
    )
    assert path.read_bytes() == data
    assert seen[-1].headers["Range"] == "bytes=1000-"
    assert not partial.exists()


def test_a_cancelled_download_keeps_what_arrived(tmp_path):
    data = b"x" * (3 << 20)
    cancelled = threading.Event()

    def progress(done: int, _total: int) -> None:
        if done >= 1 << 20:
            cancelled.set()

    with pytest.raises(hub.DownloadCancelledError):
        hub.download(
            _file(data),
            COMMIT,
            progress=progress,
            cancelled=cancelled,
            cache=tmp_path,
            transport=_serving(data),
        )
    partials = list((hub.repo_dir(REPO, tmp_path) / "blobs").glob("*.incomplete"))
    assert len(partials) == 1 and 0 < partials[0].stat().st_size < len(data)


def _no_request(request: httpx.Request) -> httpx.Response:
    pytest.fail(f"unexpected request: {request.url}")


@pytest.mark.parametrize("name", ["../../outside.gguf", "../T-Q4_K_M.gguf", "/etc/x.gguf"])
def test_a_download_stays_inside_its_snapshot(tmp_path, name):
    part = hub.GGUFPart(name, 1, "0" * 64)
    with pytest.raises(hub.HubError, match="outside"):
        hub.download(
            hub.GGUFFile(REPO, "Q4_K_M", (part,)),
            COMMIT,
            cache=tmp_path,
            transport=httpx.MockTransport(_no_request),
        )
    assert hub.group_quants(REPO, [_sibling(name, b"x")]) == ()


def test_the_cache_lists_complete_models_whoever_downloaded_them(tmp_path):
    _layout(
        tmp_path,
        "acme/Big-GGUF",
        {
            "Q4/Big-Q4_K_M-00001-of-00002.gguf": b"one",
            "Q4/Big-Q4_K_M-00002-of-00002.gguf": b"two",
            "Big-Q8_0-00001-of-00002.gguf": b"half",  # the other part never arrived
            "mmproj-Big-F16.gguf": b"vision",
        },
    )
    root = _layout(tmp_path, REPO, {"T-Q4_K_M.gguf": b"tiny"})
    dangling = root / "snapshots" / COMMIT / "T-Q8_0.gguf"
    dangling.symlink_to("../../blobs/" + "f" * 64)  # a download llama-server left unfinished
    models = hub.cached_models(tmp_path)
    assert [(m.reference, m.size) for m in models] == [
        ("acme/Big-GGUF:Q4_K_M", 6),
        (f"{REPO}:Q4_K_M", 4),
    ]
    assert models[0].path.name == "Big-Q4_K_M-00001-of-00002.gguf"
    assert models[0].name == "Big-Q4_K_M"
    # A reference without a quantization means llama-server's default, Q4_K_M.
    assert hub.resolve(REPO, tmp_path) == root / "snapshots" / COMMIT / "T-Q4_K_M.gguf"
    assert hub.resolve(f"{REPO}:Q8_0", tmp_path) is None
    assert hub.resolve("nobody/Missing-GGUF:Q4_K_M", tmp_path) is None


def test_deleting_a_model_removes_its_blobs_and_its_last_folder(tmp_path):
    root = _layout(tmp_path, REPO, {"T-Q4_K_M.gguf": b"four", "T-Q8_0.gguf": b"eight"})
    q4, q8 = sorted(hub.cached_models(tmp_path), key=lambda m: m.quant)
    hub.delete(q4, tmp_path)
    assert [m.quant for m in hub.cached_models(tmp_path)] == ["Q8_0"]
    assert not (root / "blobs" / hashlib.sha256(b"four").hexdigest()).exists()
    hub.delete(q8, tmp_path)
    assert not root.exists()


def test_a_session_starts_a_downloaded_model_from_its_file(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path))
    root = _layout(tmp_path, REPO, {"T-Q4_K_M.gguf": b"tiny"})
    file = str(root / "snapshots" / COMMIT / "T-Q4_K_M.gguf")
    assert local_model(f"{REPO}:Q4_K_M") == file
    # Not downloaded: llama-server fetches it; a path is a path.
    assert local_model("acme/Other-GGUF:Q4_K_M") == "acme/Other-GGUF:Q4_K_M"
    assert local_model("/models/x.gguf") == "/models/x.gguf"


def test_the_cache_follows_the_hugging_face_variables(monkeypatch, tmp_path):
    for var in ("HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE", "HF_HOME", "XDG_CACHE_HOME"):
        monkeypatch.delenv(var, raising=False)
    assert hub.hub_cache() == Path.home() / ".cache" / "huggingface" / "hub"
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    assert hub.hub_cache() == tmp_path / "xdg" / "huggingface" / "hub"
    monkeypatch.setenv("HF_HOME", str(tmp_path / "home"))
    assert hub.hub_cache() == tmp_path / "home" / "hub"
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "hub"))
    assert hub.hub_cache() == tmp_path / "hub"


def test_whether_a_model_fits_warns_by_tier():
    sixteen = hub.Machine(16 * hub.GiB, int(16 * hub.GiB * 2 / 3), unified=True)
    by_name = {r.name: r for r in hub.RECOMMENDED}

    def verdict(name: str) -> str:
        rec = by_name[name]
        return hub.fit(rec.size, rec.params, 8192, sixteen)

    assert verdict("Qwen3 4B Instruct 2507") == hub.FITS
    assert verdict("gpt-oss 20B") == hub.TOO_BIG
    assert verdict("Qwen3 30B-A3B Instruct 2507") == hub.TOO_BIG
    eight = hub.Machine(8 * hub.GiB, int(8 * hub.GiB * 2 / 3), unified=True)
    rec = by_name["Qwen3 4B Instruct 2507"]
    assert hub.fit(rec.size, rec.params, 8192, eight) == hub.TIGHT
    # A longer conversation needs more memory.
    assert hub.memory_needed(rec.size, rec.params, 32768) > hub.memory_needed(
        rec.size, rec.params, 8192
    )
    # The search's ceiling follows the context: with 8k tokens, about 14B on
    # 16 GB and a 4B on 8 GB; with the default 32k, about 9B and 1B.
    assert 12e9 < hub.max_params(sixteen, 8192) < 16e9
    assert 4e9 < hub.max_params(eight, 8192) < 8e9
    assert 8e9 < hub.max_params(sixteen) < 10e9
    assert 0.5e9 <= hub.max_params(eight) < 2e9
    # Never stricter than the badge: the largest model it lets through is not too big.
    ceiling = hub.max_params(sixteen)
    assert hub.fit(int(ceiling * 0.6), ceiling, 32768, sixteen) != hub.TOO_BIG
    assert sixteen.describe() == "16 GB of memory, about 11 GB of it for a model on the GPU"


def test_this_machine_is_measured():
    here = hub.machine()
    assert here.memory > 1 << 30
    assert 0 < here.budget <= here.memory


def test_recommended_models_are_named_by_their_reference():
    assert hub.recommended("unsloth/Qwen3-4B-Instruct-2507-GGUF").name == (
        "Qwen3 4B Instruct 2507"
    )
    assert hub.recommended("ggml-org/gpt-oss-20b-gguf:mxfp4") is not None
    assert hub.recommended("acme/Other-GGUF:Q4_K_M") is None
    sizes = [r.size for r in hub.RECOMMENDED]
    assert sizes == sorted(sizes)  # "smallest first", as the tab says
