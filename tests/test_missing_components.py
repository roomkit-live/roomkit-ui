"""A backend this install lacks is a state to report, not a fault to trace.

A session start that needs one says in the chat what is missing and how to
add it, logs one line without a traceback, and is told apart from an error
(``component_missing``).  An optional pipeline stage that needs one is left
out of the session, and the chat says so.
"""

import logging

import pytest

from roomkit_ui import features
from roomkit_ui.engine import Engine
from roomkit_ui.engine_audio import build_denoiser, notify_missing_denoiser, setup_diarization
from roomkit_ui.features import FeatureUnavailableError, require


@pytest.fixture
def missing(monkeypatch):
    """Make the given feature keys read as not installed."""

    def hide(*keys: str) -> None:
        monkeypatch.setattr(
            features, "missing_modules", lambda key: ("absent",) if key in keys else ()
        )

    return hide


def _signals(engine: Engine) -> tuple[list, list]:
    missing_seen: list[tuple[str, str]] = []
    errors: list[str] = []
    engine.component_missing.connect(lambda key, msg: missing_seen.append((key, msg)))
    engine.error_occurred.connect(errors.append)
    return missing_seen, errors


def test_the_refusal_names_the_feature_to_install(missing):
    missing("gemini")

    with pytest.raises(FeatureUnavailableError) as refused:
        require("gemini")

    assert refused.value.feature == "gemini"
    assert str(refused.value) == (
        "Google Gemini is not installed — add it in Settings → Models & components → Components."
    )


async def test_a_realtime_start_without_its_backend_says_so_without_a_traceback(
    qapp, missing, caplog
):
    missing("gemini")
    engine = Engine()
    missing_seen, errors = _signals(engine)

    with caplog.at_level(logging.WARNING):
        await engine._start_realtime({"provider": "gemini", "api_key": "k"})

    assert [key for key, _ in missing_seen] == ["gemini"]
    assert errors == []
    assert all(record.exc_info is None for record in caplog.records)
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


async def test_a_voice_channel_start_without_its_stt_says_so_without_a_traceback(
    qapp, missing, caplog
):
    missing("deepgram")
    engine = Engine()
    missing_seen, errors = _signals(engine)

    with caplog.at_level(logging.WARNING):
        await engine._start_voice_channel({"vc_stt_provider": "deepgram"})

    assert [key for key, _ in missing_seen] == ["deepgram"]
    assert errors == []
    assert all(record.exc_info is None for record in caplog.records)


def test_gtcrn_without_sherpa_onnx_leaves_the_session_without_a_denoiser(missing):
    missing("local-voice")
    notices: list[str] = []

    denoiser = build_denoiser("gtcrn", 16000)
    notify_missing_denoiser("gtcrn", denoiser, notices.append)

    assert denoiser is None
    assert len(notices) == 1
    assert notices[0].startswith("No noise suppression this session: Local speech")


def test_a_denoiser_that_loaded_is_not_reported(missing):
    missing()
    notices: list[str] = []

    notify_missing_denoiser("gtcrn", object(), notices.append)
    notify_missing_denoiser("webrtc", None, notices.append)

    assert notices == []


def test_diarization_without_sherpa_onnx_is_left_out_and_said(qapp, missing, monkeypatch):
    from roomkit_ui import model_manager

    missing("local-voice")
    monkeypatch.setattr(model_manager, "is_speaker_model_downloaded", lambda _id: True)
    engine = Engine()
    notices: list[str] = []
    engine.session_notice.connect(notices.append)

    diarization = setup_diarization(
        engine,
        {"diarization_enabled": True, "diarization_model": "nemo-titanet-large"},
        vad_available=True,
        inference_device="cpu",
    )

    assert diarization is None
    assert notices and notices[0].startswith("Speakers are not identified this session")


def test_a_turnless_stt_falls_back_to_the_energy_vad_without_sherpa_onnx(missing, monkeypatch):
    from roomkit_ui import model_manager
    from roomkit_ui.vc_stt import build_turn_vad

    missing("local-voice")
    monkeypatch.setattr(model_manager, "is_vad_model_downloaded", lambda _id: True)

    vad = build_turn_vad({"vc_vad_model": "silero-vad"}, "cpu")

    assert type(vad).__name__ == "EnergyVADProvider"


def test_without_pynput_the_hotkeys_say_so_once_and_start_nothing(qapp, missing, caplog):
    from roomkit_ui import hotkey

    missing("hotkey")
    hotkey._unavailable_logged = False
    listeners = [hotkey.HotkeyListener("<cmd_r>"), hotkey.HotkeyListener("<ctrl>+<shift>+a")]

    with caplog.at_level(logging.INFO, logger="roomkit_ui.hotkey"):
        for listener in listeners * 2:  # both listeners, started, then reloaded
            listener.start()

    said = [r for r in caplog.records if r.name == "roomkit_ui.hotkey"]
    assert len(said) == 1
    assert said[0].levelno == logging.INFO
    assert said[0].getMessage() == (
        "Global hotkeys off: Global hotkey support is not installed — add it in "
        "Settings → Models & components → Components."
    )
    assert all(lst._listener is None and lst._monitor is None for lst in listeners)
