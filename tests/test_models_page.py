"""Model library behavior across filtering, downloads, retries and dialog lifetime."""

from __future__ import annotations

import asyncio

import pytest
import shiboken6

from roomkit_ui import model_manager as models
from roomkit_ui.theme_live import apply_theme
from roomkit_ui.widgets.settings import models_page
from roomkit_ui.widgets.settings.model_jobs import ModelDownloads
from roomkit_ui.widgets.settings.model_library import LibraryModel, ModelGroup, model_groups


async def _drain(done, timeout=5.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not done() and loop.time() < deadline:
        await asyncio.sleep(0.01)
    assert done(), "Download did not reach the expected state"


@pytest.fixture
def library(qapp, monkeypatch, tmp_path):
    runner = ModelDownloads(qapp)
    monkeypatch.setattr(models_page, "model_downloads", lambda: runner)
    opened = []

    def open_page(download, *, remove=None):
        marker = tmp_path / "model"
        model = LibraryModel(
            "test-model",
            "Test voice",
            "Local speech",
            "1 MB",
            marker.exists,
            download,
            remove or marker.unlink,
        )
        monkeypatch.setattr(
            models_page,
            "model_groups",
            lambda: (ModelGroup("speech", "Speech & voices", "Local voices", (model,)),),
        )
        page = models_page._ModelsPage({})
        opened.append(page)
        return page, page.rows[model.id], marker

    yield runner, open_page
    for page in opened:
        if shiboken6.isValid(page):
            shiboken6.delete(page)
    shiboken6.delete(runner)


async def test_progress_then_success_ignores_a_late_worker_report(library):
    runner, open_page = library
    gate = asyncio.Event()

    async def download(progress):
        await asyncio.to_thread(progress, 50, 100)
        await gate.wait()
        marker.touch()
        # Queued after completion: must not replace the outcome with a progress bar.
        asyncio.get_running_loop().call_soon(progress, 100, 100)

    page, row, marker = open_page(download)
    row.action_btn.click()
    assert row.phase == "resolving"
    await _drain(lambda: row.phase == "downloading")
    assert row.progress_bar.value() == 50
    gate.set()
    await _drain(lambda: row.phase == "downloaded")
    await asyncio.sleep(0.02)
    assert row.phase == "downloaded"
    assert row.progress_bar.isHidden()
    assert not row.delete_btn.isHidden()
    assert not runner._tasks


async def test_reopening_and_changing_theme_keep_one_download_and_its_progress(library, qapp):
    runner, open_page = library
    gate = asyncio.Event()
    started = []

    async def download(progress):
        started.append(True)
        await asyncio.to_thread(progress, 42, 100)
        await gate.wait()
        marker.touch()

    page, row, marker = open_page(download)
    row.action_btn.click()
    await _drain(lambda: row.phase == "downloading")
    shiboken6.delete(page)
    reopened, new_row, _ = open_page(download)
    assert new_row.progress_bar.value() == 42
    assert new_row.action_btn.isHidden()
    runner.start(new_row.model)
    reopened.search.setText("voice")
    for theme in ("light", "dark"):
        apply_theme(theme)
        qapp.processEvents()
        assert reopened.rows["test-model"] is new_row
        assert new_row.progress_bar.value() == 42
        assert reopened.search.text() == "voice"
    gate.set()
    await _drain(lambda: new_row.phase == "downloaded")
    assert started == [True]


async def test_error_is_visible_and_retry_can_succeed(library):
    _, open_page = library
    calls = []

    async def download(_progress):
        calls.append(True)
        if len(calls) == 1:
            raise OSError("Connection reset")
        marker.touch()

    page, row, marker = open_page(download)
    row.action_btn.click()
    await _drain(lambda: row.phase == "error")
    assert row.error.text() == "Connection reset"
    assert not row.error.isHidden()
    assert row.action_btn.text() == "Retry download"
    assert row.delete_btn.isHidden()
    row.action_btn.click()
    await _drain(lambda: row.phase == "downloaded")
    assert row.error.isHidden()
    assert len(calls) == 2


async def test_completion_after_the_only_page_was_destroyed_is_retained(library):
    runner, open_page = library
    gate = asyncio.Event()
    loop = asyncio.get_running_loop()
    errors = []
    loop.set_exception_handler(lambda _loop, context: errors.append(context))

    async def download(progress):
        await gate.wait()
        await asyncio.to_thread(progress, 100, 100)
        marker.touch()

    try:
        page, row, marker = open_page(download)
        row.action_btn.click()
        shiboken6.delete(page)
        gate.set()
        await _drain(lambda: not runner._tasks)
        reopened, row, _ = open_page(download)
        assert row.phase == "downloaded"
        assert errors == []
    finally:
        loop.set_exception_handler(None)


def test_filters_do_not_recreate_rows_or_forget_file_changes(library):
    _, open_page = library

    async def download(_progress):
        pass

    page, row, marker = open_page(download)
    page.availability.setCurrentIndex(1)
    assert row.isHidden() and not page.empty.isHidden()
    marker.touch()
    page.refresh()
    assert not row.isHidden()
    page.search.setText("unmatched")
    assert not page.empty.isHidden()
    page.reset.click()
    assert page.rows["test-model"] is row
    assert not row.isHidden()
    row.delete_btn.click()
    assert not marker.exists()
    assert row.phase == "available"


def test_failed_deletion_keeps_files_and_explains_the_failure(library):
    _, open_page = library

    async def download(_progress):
        pass

    def remove():
        raise PermissionError("Folder is read-only")

    page, row, marker = open_page(download, remove=remove)
    marker.touch()
    page.refresh()
    row.delete_btn.click()
    assert marker.exists()
    assert row.phase == "downloaded"
    assert "Folder is read-only" in row.error.text()
    assert not row.error.isHidden()


@pytest.mark.parametrize(
    ("model_id", "check", "fetch", "remove", "args"),
    [
        (
            models.STT_MODELS[0].id,
            "is_model_downloaded",
            "download_model",
            "delete_model",
            (models.STT_MODELS[0].id,),
        ),
        (
            models.TTS_MODELS[0].id,
            "is_tts_model_downloaded",
            "download_tts_model",
            "delete_tts_model",
            (models.TTS_MODELS[0].id,),
        ),
        (
            models.VAD_MODELS[0].id,
            "is_vad_model_downloaded",
            "download_vad_model",
            "delete_vad_model",
            (models.VAD_MODELS[0].id,),
        ),
        (
            models.SPEAKER_MODELS[0].id,
            "is_speaker_model_downloaded",
            "download_speaker_model",
            "delete_speaker_model",
            (models.SPEAKER_MODELS[0].id,),
        ),
        (models.GTCRN_MODEL_ID, "is_gtcrn_downloaded", "download_gtcrn", "delete_gtcrn", ()),
        (
            models.DPDFNET_MODEL_ID,
            "is_dpdfnet_downloaded",
            "download_dpdfnet",
            "delete_dpdfnet",
            (),
        ),
        (
            models.SMART_TURN_MODEL_ID,
            "is_smart_turn_downloaded",
            "download_smart_turn",
            "delete_smart_turn",
            (),
        ),
        (
            "espeak-ng-data",
            "is_espeak_ng_downloaded",
            "download_espeak_ng_data",
            "delete_espeak_ng_data",
            (),
        ),
    ],
)
async def test_each_model_kind_uses_its_own_file_operations(
    monkeypatch, model_id, check, fetch, remove, args
):
    calls = []
    monkeypatch.setattr(models, check, lambda *values: calls.append(("check", values)) or True)
    monkeypatch.setattr(models, remove, lambda *values: calls.append(("remove", values)))

    async def download(*values):
        calls.append(("download", values))

    monkeypatch.setattr(models, fetch, download)
    model = next(
        model for group in model_groups() for model in group.models if model.id == model_id
    )

    def progress(done, total):
        pass

    assert model.downloaded()
    await model.download(progress)
    model.delete()
    assert calls == [("check", args), ("download", (*args, progress)), ("remove", args)]
