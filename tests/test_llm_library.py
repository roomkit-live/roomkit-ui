"""Settings for local LLMs: the LLMs tab of Models & components, the GGUF
field every LLM picker shares, and the Hugging Face token."""

from __future__ import annotations

import asyncio
import hashlib
import os
import threading
from pathlib import Path

import pytest
import shiboken6
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

from roomkit_ui import gguf_models as hub
from roomkit_ui.settings import _DEFAULTS
from roomkit_ui.widgets.settings import llm_fields
from roomkit_ui.widgets.settings.controls import FeedbackLabel
from roomkit_ui.widgets.settings.llm_library_page import LLMLibrary, model_id
from roomkit_ui.widgets.settings.model_jobs import ModelDownloads
from roomkit_ui.widgets.settings.providers_page import ProvidersPage
from roomkit_ui.widgets.settings.text_chat_setup import TextChatSetup

COMMIT = "c" * 40
SIXTEEN = hub.Machine(16 * hub.GiB, int(16 * hub.GiB * 2 / 3), unified=True)
QWEN4B = "unsloth/Qwen3-4B-Instruct-2507-GGUF:Q4_K_M"


def _download_into_cache(reference: str, data: bytes = b"gguf") -> Path:
    """A model in the cache, as a finished download leaves it."""
    repo, _, quant = reference.partition(":")
    root = hub.repo_dir(repo, hub.hub_cache())
    blob = root / "blobs" / hashlib.sha256(data).hexdigest()
    blob.parent.mkdir(parents=True, exist_ok=True)
    blob.write_bytes(data)
    link = root / "snapshots" / COMMIT / f"{repo.split('/')[1].removesuffix('-GGUF')}-{quant}.gguf"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(os.path.relpath(blob, link.parent))
    (root / "refs").mkdir(exist_ok=True)
    (root / "refs" / "main").write_text(COMMIT)
    return link


async def _until(done, timeout: float = 5.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not done() and loop.time() < deadline:
        await asyncio.sleep(0.01)
    assert done(), "the expected state never came"


@pytest.fixture
def world(qapp, monkeypatch):
    runner = ModelDownloads(qapp)
    monkeypatch.setattr(qapp, "_roomkit_model_downloads", runner, raising=False)
    monkeypatch.setattr(hub, "machine", lambda: SIXTEEN)
    llm_fields._machine.cache_clear()
    widgets: list = []

    def open_widget(factory, *args):
        widget = factory(*args)
        widgets.append(widget)
        return widget

    yield runner, open_widget
    for widget in widgets:
        if shiboken6.isValid(widget):
            shiboken6.delete(widget)
    llm_fields._machine.cache_clear()
    shiboken6.delete(runner)


class FakeHub:
    """Hugging Face as the tab sees it: a search, a repository."""

    tokens: list[str] = []
    models: list[hub.HubModel] = []
    info: hub.RepoInfo | None = None
    error: Exception | None = None

    def __init__(self, token: str = "") -> None:
        FakeHub.tokens.append(token)

    async def search(self, query, *, max_params=0, limit=20):
        if FakeHub.error is not None:
            raise FakeHub.error
        return list(FakeHub.models)

    async def repo(self, repo):
        assert FakeHub.info is not None
        return FakeHub.info


@pytest.fixture
def fake_hub(monkeypatch):
    FakeHub.tokens, FakeHub.models, FakeHub.info, FakeHub.error = [], [], None, None
    monkeypatch.setattr(hub, "HubClient", FakeHub)
    return FakeHub


def _quant(repo: str, label: str, size: int) -> hub.GGUFFile:
    part = hub.GGUFPart(f"M-{label}.gguf", size, "0" * 64)
    return hub.GGUFFile(repo, label, (part,))


def test_recommended_models_say_whether_they_fit_this_computer(world):
    _runner, open_widget = world
    page = open_widget(LLMLibrary, {})
    badges = {
        page.rows[model_id(rec.reference)].model.name: page.rows[
            model_id(rec.reference)
        ].badge.text()
        for rec in hub.RECOMMENDED
    }
    assert badges["Qwen3 4B Instruct 2507"] == "Runs well here"
    assert badges["gpt-oss 20B"] == "Too big for this computer"
    # A warning only: it can still be downloaded.
    row = page.rows[model_id("ggml-org/gpt-oss-20b-GGUF:MXFP4")]
    assert not row.action_btn.isHidden()
    assert page.local_empty.isVisibleTo(page)


def test_a_downloaded_model_is_listed_and_deleted_from_this_computer(world):
    runner, open_widget = world
    _download_into_cache(QWEN4B)
    page = open_widget(LLMLibrary, {})
    recommended = page.rows[model_id(QWEN4B)]
    assert recommended.phase == "downloaded"
    local = page.local_rows[model_id(QWEN4B)]
    assert local.model.name == "Qwen3-4B-Instruct-2507-Q4_K_M"
    assert not page.local_empty.isVisibleTo(page)

    local.delete_btn.click()
    assert hub.cached(QWEN4B) is None
    assert recommended.phase == "available"
    assert not page.local_rows
    assert page.local_empty.isVisibleTo(page)


async def test_search_shows_the_latest_answer_only(world, fake_hub):
    _runner, open_widget = world
    page = open_widget(LLMLibrary, {"huggingface_token": "hf_saved"})
    fake_hub.models = [hub.HubModel("acme/Small-GGUF", 3_000_000_000, 4200, False, True)]
    page._seq = 2
    await page.run_search("small", 0, 1)  # an older search, answering late
    assert page.results == []
    await page.run_search("small", 0, 2)
    assert [r.model.repo for r in page.results] == ["acme/Small-GGUF"]
    texts = [child.text() for child in page.results[0].findChildren(QLabel)]
    assert "3B parameters · 4k downloads · tool calls" in texts
    assert fake_hub.tokens == ["hf_saved", "hf_saved"]

    fake_hub.error = hub.HubError("Hugging Face could not be reached: offline")
    await page.run_search("small", 0, 2)
    assert page.status.text() == "Search failed: Hugging Face could not be reached: offline"


async def test_a_result_downloads_the_size_that_fits_into_the_cache(world, fake_hub, monkeypatch):
    runner, open_widget = world
    repo = "acme/Small-GGUF"
    model = hub.HubModel(repo, 3_000_000_000, 10, False, True)
    fake_hub.info = hub.RepoInfo(
        model,
        COMMIT,
        (
            _quant(repo, "Q2_K", 1_200_000_000),
            _quant(repo, "Q4_K_M", 1_900_000_000),
            _quant(repo, "BF16", 30_000_000_000),
        ),
    )
    page = open_widget(LLMLibrary, {})
    page._render([model])
    result = page.results[0]
    await page.read_sizes(result)
    assert result.selected().quant == "Q4_K_M"
    assert result.quants.itemData(2, Qt.ToolTipRole) == "Too big for this computer"
    gate = threading.Event()
    calls = []

    def fake_download(file, commit, *, token, progress, cancelled):
        calls.append((file.reference, commit, token))
        progress(0, file.size)
        gate.wait(5)
        _download_into_cache(file.reference)

    monkeypatch.setattr(hub, "download", fake_download)
    result.download_btn.click()
    await _until(lambda: not result.cancel_btn.isHidden())
    assert not result.quants.isEnabled()
    gate.set()
    await _until(lambda: model_id(f"{repo}:Q4_K_M") not in runner.states)
    assert calls == [(f"{repo}:Q4_K_M", COMMIT, "")]
    assert result.badge.text() == "Downloaded"
    assert result.download_btn.isHidden()
    assert model_id(f"{repo}:Q4_K_M") in page.local_rows


async def test_cancel_stops_a_download_between_chunks(world, fake_hub, monkeypatch):
    runner, open_widget = world
    rec = hub.RECOMMENDED[0]
    fake_hub.info = hub.RepoInfo(
        hub.HubModel(rec.repo), COMMIT, (_quant(rec.repo, rec.quant, rec.size),)
    )
    stopped = threading.Event()

    def fake_download(file, commit, *, token, progress, cancelled):
        progress(1, file.size)
        assert cancelled.wait(5)
        stopped.set()
        raise hub.DownloadCancelledError(file.reference)

    monkeypatch.setattr(hub, "download", fake_download)
    page = open_widget(LLMLibrary, {})
    row = page.rows[model_id(rec.reference)]
    row.action_btn.click()
    await _until(lambda: row.phase == "downloading")
    assert not row.cancel_btn.isHidden()
    row.cancel_btn.click()
    await _until(lambda: not runner._tasks)
    assert stopped.is_set()
    assert row.phase == "available"
    assert row.cancel_btn.isHidden()


def test_the_gguf_field_offers_downloaded_models_and_warns(world):
    runner, open_widget = world
    _download_into_cache(QWEN4B)
    setup = open_widget(TextChatSetup, {**_DEFAULTS, "text_llm_provider": "llamacpp"})
    gguf = setup.llm.fields["llamacpp_model"]
    assert [gguf.itemText(i) for i in range(gguf.count())] == [QWEN4B]
    assert gguf.text() == ""  # Think · LLM's model, until chosen
    assert "As in Think · LLM" in gguf.placeholderText()
    status = next(w for w in setup.llm._rows["llamacpp"] if isinstance(w, FeedbackLabel))
    # Think · LLM's model, the default one, is downloaded.
    assert status.text() == "Downloaded · 0.00 GB · Runs well here"

    gguf.setCurrentIndex(0)
    assert setup.llm.get_settings()["text_llamacpp_model"] == QWEN4B
    gguf.setText("LiquidAI/LFM2.5-2.6B-GGUF:Q4_K_M")
    assert status.text() == "Not downloaded yet (1.67 GB) · Runs well here"

    gguf.setText("unsloth/Qwen3-30B-A3B-Instruct-2507-GGUF:Q4_K_M")
    assert status.text().startswith("Not downloaded yet (19 GB) · Too big for this computer")
    gguf.setText("/no/such/model.gguf")
    assert status.text() == "No file at this path."

    # A download finished elsewhere: the list follows, the text stays.
    other = "acme/Small-GGUF:Q8_0"
    _download_into_cache(other)
    runner.changed.emit(model_id(other))
    assert gguf.count() == 2
    assert gguf.text() == "/no/such/model.gguf"


def test_hugging_face_is_a_local_provider_with_an_optional_token(qapp):
    page = ProvidersPage({**_DEFAULTS, "huggingface_token": ""})
    try:
        card = page.cards["huggingface_token"]
        assert card.parent() is page.local.card
        assert card.status.text() == "Token optional"
        field = page.fields["huggingface_token"]
        assert field.placeholderText() == "Optional access token"
        field.setText(" hf_abc ")
        assert card.status.text() == "Token added"
        assert page.get_settings()["huggingface_token"] == "hf_abc"
    finally:
        shiboken6.delete(page)
