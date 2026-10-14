"""Kokoro: a checked download, a voice in a language it reads well, cached like Piper."""

import io
import tarfile

import pytest
import shiboken6

from roomkit_ui import engine_vc, model_catalog, model_download
from roomkit_ui.engine import Engine
from roomkit_ui.settings import _DEFAULTS
from roomkit_ui.tts import is_cached_tts, kokoro
from roomkit_ui.widgets.settings.voice_setup import VC_TTS_PROVIDERS, VoiceSetup

_KOKORO = {"vc_tts_provider": "kokoro"}


@pytest.fixture
def models(tmp_path, monkeypatch):
    monkeypatch.setattr(model_catalog, "get_models_dir", lambda: tmp_path)
    return tmp_path


def _install(models_dir):
    d = models_dir / "kokoro" / model_catalog.KOKORO_MODEL_ID
    (d / "espeak-ng-data").mkdir(parents=True)
    for name in model_catalog._KOKORO_FILES:
        (d / name).write_bytes(b"x")
    return d


# -- voices ----------------------------------------------------------------------


def test_only_languages_kokoro_reads_well_are_offered():
    languages = {label.split(" · ")[0] for label, _ in kokoro.VOICES}

    assert languages == {
        "American English",
        "British English",
        "French",
        "Spanish",
        "Italian",
        "Brazilian Portuguese",
    }
    assert ("French · Siwis (female)", "ff_siwis") in kokoro.VOICES


def test_a_voice_is_its_index_in_voices_bin():
    assert kokoro._VOICES_BIN.index("af_heart") == 3
    assert kokoro._VOICES_BIN.index("ff_siwis") == 30
    assert kokoro._VOICES_BIN.index("em_santa") == 53
    assert len(kokoro._VOICES_BIN) == 54
    assert kokoro.voice_label("30") == "French · Siwis (female)"


# -- factory ---------------------------------------------------------------------


def test_not_downloaded_says_where_to_get_it(models):
    with pytest.raises(ValueError, match="Models & components"):
        kokoro.create({})


def test_by_default_it_speaks_the_speech_recognition_language(models):
    d = _install(models)

    tts, rate = kokoro.create({"stt_language": "fr"})

    config = tts._config
    assert rate == 24000
    assert (config.model_type, config.lang, config.speaker_id) == ("kokoro", "fr", 30)
    assert config.voices == str(d / "voices.bin")
    assert config.lexicon.startswith(str(d / "lexicon-us-en.txt"))


def test_a_chosen_voice_wins_and_brings_its_language(models):
    _install(models)

    tts, _ = kokoro.create(
        {"stt_language": "fr", "vc_kokoro_voice": "bm_george", "inference_device": "cuda"}
    )

    config = tts._config
    assert (config.lang, config.speaker_id, config.provider) == ("", 26, "cuda")
    assert "lexicon-gb-en.txt" in config.lexicon


def test_a_voice_not_offered_falls_back_to_the_language_default(models):
    _install(models)

    tts, _ = kokoro.create({"stt_language": "de", "vc_kokoro_voice": "jf_alpha"})

    assert tts._config.speaker_id == 3  # af_heart: no Japanese, no German


# -- engine cache ------------------------------------------------------------------


@pytest.fixture
def engine(qapp, monkeypatch):
    built: list[object] = []

    def create(name, settings):
        tts = object()
        built.append(tts)
        return tts, 24000

    monkeypatch.setattr(engine_vc, "create_tts_provider", create)
    eng = Engine()
    eng.built = built
    return eng


async def test_the_same_voice_reuses_the_cached_model_another_rebuilds_it(engine):
    assert is_cached_tts("kokoro")
    first, _ = await engine._build_tts({**_KOKORO, "vc_kokoro_voice": "ff_siwis"}, "cpu")
    again, _ = await engine._build_tts({**_KOKORO, "vc_kokoro_voice": "ff_siwis"}, "cpu")
    other, _ = await engine._build_tts({**_KOKORO, "vc_kokoro_voice": "ef_dora"}, "cpu")

    assert first is again
    assert other is not first


# -- download ----------------------------------------------------------------------


def _archive(path, members):
    with tarfile.open(path, "w:bz2") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))


def _fake_download(members):
    def download(url, target, **_kwargs):
        _archive(target, members)

    return download


def test_the_checked_archive_is_unpacked_then_removed(models, monkeypatch):
    top = model_catalog.KOKORO_MODEL_ID
    members = {f"{top}/{name}": b"x" for name in model_catalog._KOKORO_FILES}
    members[f"{top}/espeak-ng-data/phontab"] = b"x"
    monkeypatch.setattr(model_download, "_download_file", _fake_download(members))

    model_download._download_kokoro_sync()

    assert model_catalog.is_kokoro_downloaded()
    assert [p.name for p in (models / "kokoro").iterdir()] == [top]  # no archive, no staging


def test_an_archive_reaching_outside_its_folder_installs_nothing(models, monkeypatch):
    top = model_catalog.KOKORO_MODEL_ID
    members = {f"{top}/tokens.txt": b"x", f"{top}/../../escaped.txt": b"x"}
    monkeypatch.setattr(model_download, "_download_file", _fake_download(members))

    with pytest.raises(tarfile.FilterError):
        model_download._download_kokoro_sync()

    assert not model_catalog.is_kokoro_downloaded()
    assert not (models / "escaped.txt").exists()
    assert list((models / "kokoro").iterdir()) == []


# -- settings page -------------------------------------------------------------------


def test_the_settings_page_offers_kokoro_and_its_voices(qapp, models):
    page = VoiceSetup({**_DEFAULTS, **_KOKORO, "vc_kokoro_voice": "if_sara"})
    try:
        local = page._local
        assert ("Kokoro (local, five languages)", "kokoro") in VC_TTS_PROVIDERS
        assert not local.vc_kokoro_voice.isHidden()
        assert not local._vc_kokoro_missing.isHidden()  # nothing downloaded here
        assert local.vc_tts_model.isHidden()  # Piper's models
        assert page.get_settings()["vc_kokoro_voice"] == "if_sara"
    finally:
        shiboken6.delete(page)


def test_another_voice_hides_kokoros_fields(qapp, models):
    page = VoiceSetup({**_DEFAULTS, "vc_tts_provider": "piper"})
    try:
        assert page._local.vc_kokoro_voice.isHidden()
        assert page._local._vc_kokoro_missing.isHidden()
    finally:
        shiboken6.delete(page)
