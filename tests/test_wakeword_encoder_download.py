"""The wake-word encoder can be fetched from Settings, not placed by hand."""

from __future__ import annotations

import asyncio

import pytest

from roomkit_ui import model_catalog, model_download
from roomkit_ui.wakeword import encoder_download
from roomkit_ui.widgets.settings import wakeword_page


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def test_downloads_the_pinned_file_and_checks_its_digest(home, monkeypatch):
    calls = []

    def fake_download(url, target, expected_size=0, on_bytes=None, expected_sha256=None):
        calls.append((url, target, expected_size, expected_sha256))
        on_bytes(expected_size)
        target.write_bytes(b"onnx")

    monkeypatch.setattr(model_download, "_download_file", fake_download)
    progress = []

    encoder_download.download_encoder_sync(lambda done, total: progress.append((done, total)))

    url, target, size, sha = calls[0]
    assert url == model_catalog.WAKEWORD_ENCODER_URL
    assert target == model_catalog.wakeword_encoder_path()
    assert size == model_catalog.WAKEWORD_ENCODER_BYTES
    assert sha == model_catalog.WAKEWORD_ENCODER_SHA256
    assert progress[-1] == (size, size)
    assert model_catalog.is_wakeword_encoder_downloaded()


def test_an_existing_encoder_is_not_downloaded_again(home, monkeypatch):
    path = model_catalog.wakeword_encoder_path()
    path.parent.mkdir(parents=True)
    path.write_bytes(b"onnx")
    monkeypatch.setattr(
        model_download, "_download_file", lambda *a, **kw: pytest.fail("downloaded twice")
    )

    encoder_download.download_encoder_sync()


# -- the settings page -------------------------------------------------------


@pytest.fixture
def page(qapp, home, monkeypatch):
    monkeypatch.setattr(wakeword_page, "unavailable_reason", lambda _feature: None)
    monkeypatch.setattr(wakeword_page, "is_vad_model_downloaded", lambda _model: True)
    monkeypatch.setattr(wakeword_page, "load_fingerprint", lambda: None)
    return wakeword_page._WakeWordPage({})


async def _settle(page) -> None:
    for _ in range(100):
        if page._download_task is None:
            return
        await asyncio.sleep(0.01)


def test_a_missing_encoder_offers_a_download(page):
    """Before: only "Expected at <path>", and no way to get the file."""
    assert not page._download_button.isHidden()
    assert not page._setup_button.isEnabled()


async def test_downloading_unlocks_enrolment(page, monkeypatch):
    async def fake_download(progress):
        progress(model_catalog.WAKEWORD_ENCODER_BYTES, model_catalog.WAKEWORD_ENCODER_BYTES)
        path = model_catalog.wakeword_encoder_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"onnx")

    monkeypatch.setattr(encoder_download, "download_encoder", fake_download)

    page._download_button.click()
    await _settle(page)

    assert page._download_button.isHidden()
    assert page._setup_button.isEnabled()


async def test_a_failed_download_says_so_and_offers_a_retry(page, monkeypatch):
    async def failing_download(_progress):
        raise RuntimeError("sha256 mismatch")

    monkeypatch.setattr(encoder_download, "download_encoder", failing_download)

    page._download_button.click()
    await _settle(page)

    assert "sha256 mismatch" in page._status.text()
    assert page._download_button.text() == "Retry download"
    assert page._download_button.isEnabled()
