"""GTCRN and DPDFNet run on sherpa-onnx, each from the file the app downloads for it.

sherpa-onnx ends the process when the model_type it is given does not match the
file, so a mode must always hand roomkit its own model under its own type.
"""

import logging

import pytest
import roomkit.voice.pipeline.denoiser.sherpa_onnx as sherpa_denoiser

from roomkit_ui import features, model_catalog
from roomkit_ui.engine_audio import build_denoiser


def _onnx(**metadata: str) -> bytes:
    """An ONNX file reduced to its metadata_props (ModelProto field 14)."""
    out = b""
    for key, value in metadata.items():
        entry = bytes([0x0A, len(key)]) + key.encode() + bytes([0x12, len(value)]) + value.encode()
        out += bytes([0x72, len(entry)]) + entry
    return out


@pytest.fixture
def models_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(model_catalog, "get_models_dir", lambda: tmp_path)
    monkeypatch.setattr(features, "missing_modules", lambda key: ())
    return tmp_path


@pytest.fixture
def built(monkeypatch):
    """The configs the app hands roomkit's sherpa-onnx denoiser."""
    configs: list = []

    class Provider:
        def __init__(self, config) -> None:
            configs.append(config)

    monkeypatch.setattr(sherpa_denoiser, "SherpaOnnxDenoiserProvider", Provider)
    return configs


@pytest.mark.parametrize(
    ("mode", "path"),
    [("gtcrn", model_catalog.gtcrn_model_path), ("dpdfnet", model_catalog.dpdfnet_model_path)],
)
def test_each_mode_runs_its_own_file_as_its_own_model_type(models_dir, built, mode, path):
    path().parent.mkdir(parents=True)
    path().write_bytes(_onnx(model_type=mode, sample_rate="16000"))

    assert build_denoiser(mode, 16000) is not None

    assert [(c.model_type, c.model) for c in built] == [(mode, str(path()))]


@pytest.mark.parametrize("mode", ["gtcrn", "dpdfnet"])
def test_a_model_not_downloaded_leaves_the_session_without_a_denoiser(
    models_dir, built, mode, caplog
):
    with caplog.at_level(logging.WARNING):
        assert build_denoiser(mode, 16000) is None

    assert built == []
    assert "not downloaded" in caplog.text


@pytest.mark.parametrize("mode", ["gtcrn", "dpdfnet"])
def test_audio_settings_keep_the_chosen_denoiser(qapp, mode):
    from roomkit_ui.widgets.settings.audio_processing import AudioSettings

    page = AudioSettings({"denoise": mode}, ([], []))

    assert page.get_settings()["denoise"] == mode
