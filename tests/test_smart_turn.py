"""Smart Turn loads when it can, says so when it cannot, and loads once.

The Settings offered the detector while no extra installed ``transformers``:
the detector was built, failed on every turn, and after three failures held
every turn open — the assistant stopped answering. Now the install says what
is missing, the session goes on without the detector, and an installed one
is loaded off the loop before the first turn and kept for the next session.
"""

import threading
from types import SimpleNamespace

import pytest
import shiboken6
from roomkit.voice.pipeline.turn.smart_turn import SmartTurnConfig, SmartTurnDetector

import roomkit_ui.engine_vc as engine_vc
from roomkit_ui.engine import Engine
from roomkit_ui.engine_vc_helpers import (
    build_turn_detector,
    smart_turn_config,
    turn_incomplete_wait_ms,
)
from roomkit_ui.settings import _DEFAULTS

_SETTINGS = {"vc_turn_detector": "smart-turn"}
_CONFIG = SimpleNamespace(model_path="/models/smart-turn.onnx", threshold=0.5, provider="cpu")


class _FakeDetector:
    def __init__(self, fail: bool = False) -> None:
        self.warmed_on: list[int] = []
        self._fail = fail

    def warmup(self) -> None:
        self.warmed_on.append(threading.get_ident())
        if self._fail:
            raise RuntimeError("bad model file")


@pytest.fixture
def engine(qapp, monkeypatch):
    monkeypatch.setattr(engine_vc, "smart_turn_config", lambda settings, device: _CONFIG)
    monkeypatch.setattr(engine_vc, "unavailable_reason", lambda key: None)
    eng = Engine()
    eng.notices = []
    eng.session_notice.connect(eng.notices.append)
    yield eng
    shiboken6.delete(eng)


async def test_without_the_packages_the_session_goes_on_without_it(engine, monkeypatch):
    monkeypatch.setattr(
        engine_vc,
        "unavailable_reason",
        lambda key: "Smart Turn detector is not installed — run: pip install x",
    )

    assert await engine._build_turn_detector(_SETTINGS, "cpu") is None
    assert engine.notices == [
        "Turn detection is off for this session. "
        "Smart Turn detector is not installed — run: pip install x"
    ]


async def test_it_loads_off_the_loop_once_for_every_session(engine, monkeypatch):
    built: list[_FakeDetector] = []
    monkeypatch.setattr(
        engine_vc, "build_turn_detector", lambda config: built.append(_FakeDetector()) or built[-1]
    )

    first = await engine._build_turn_detector(_SETTINGS, "cpu")
    second = await engine._build_turn_detector(_SETTINGS, "cpu")

    assert first is second is built[0] and len(built) == 1
    assert len(first.warmed_on) == 1
    assert first.warmed_on[0] != threading.get_ident()  # not on the loop's thread


async def test_a_model_that_fails_to_load_is_reported_not_fatal(engine, monkeypatch):
    monkeypatch.setattr(engine_vc, "build_turn_detector", lambda config: _FakeDetector(fail=True))

    assert await engine._build_turn_detector(_SETTINGS, "cpu") is None
    assert engine.notices == ["Turn detection is off for this session: bad model file"]
    key = ("turn", _CONFIG.model_path, _CONFIG.threshold, _CONFIG.provider)
    assert engine._get_cached("turn", key) is None  # the next session tries again


def _counting_loads(monkeypatch) -> list[int]:
    """Count SmartTurnDetector model loads, without onnxruntime or a model."""
    loads: list[int] = []

    def fake_initialize(self) -> None:
        loads.append(1)
        self._feature_extractor = object()
        self._session = object()

    monkeypatch.setattr(SmartTurnDetector, "_initialize", fake_initialize)
    return loads


def test_the_kept_detector_survives_the_pipeline_closing_it(monkeypatch):
    loads = _counting_loads(monkeypatch)
    config = SmartTurnConfig(model_path="/models/smart-turn.onnx")

    plain = SmartTurnDetector(config)
    plain.warmup()
    plain.close()  # what the pipeline does at the session's end
    plain.warmup()
    assert len(loads) == 2  # roomkit's own loads again

    kept = build_turn_detector(config)
    assert isinstance(kept, SmartTurnDetector)
    kept.warmup()
    kept.close()
    kept.warmup()
    assert len(loads) == 3  # loaded once, kept across the close


def test_no_detector_unless_selected_and_downloaded(monkeypatch):
    monkeypatch.setattr("roomkit_ui.model_manager.is_smart_turn_downloaded", lambda: False)

    assert smart_turn_config({}, "cpu") is None
    assert smart_turn_config(_SETTINGS, "cpu") is None


def test_the_threshold_setting_reaches_the_config(monkeypatch):
    monkeypatch.setattr("roomkit_ui.model_manager.is_smart_turn_downloaded", lambda: True)

    assert smart_turn_config({**_SETTINGS, "vc_turn_threshold": "0.7"}, "cpu").threshold == 0.7
    assert smart_turn_config({**_SETTINGS, "vc_turn_threshold": "x"}, "cpu").threshold == 0.5


@pytest.mark.parametrize(("raw", "ms"), [("", 1500.0), ("2500", 2500.0), ("soon", 1500.0)])
def test_the_unfinished_turn_wait(raw, ms):
    assert turn_incomplete_wait_ms({"vc_turn_incomplete_wait_ms": raw}) == ms


# -- settings page ---------------------------------------------------------------


@pytest.fixture
def general_page(qapp, monkeypatch):
    from roomkit_ui.widgets.settings import general_page as page_mod

    monkeypatch.setattr(page_mod, "_list_audio_devices", lambda: ([], []))
    monkeypatch.setattr("roomkit_ui.model_manager.is_smart_turn_downloaded", lambda: True)
    pages = []

    def _build(**overrides):
        pages.append(page_mod._GeneralPage({**_DEFAULTS, **overrides}))
        return pages[-1]

    yield _build
    for page in pages:
        shiboken6.delete(page)


def test_a_missing_install_is_named_where_the_detector_is_picked(general_page, monkeypatch):
    reason = "Smart Turn detector is not installed — run: pip install x"
    monkeypatch.setattr(
        "roomkit_ui.widgets.settings.feature_hints.unavailable_reason", lambda key: reason
    )
    monkeypatch.setattr(
        "roomkit_ui.widgets.settings.general_page.unavailable_reason", lambda key: reason
    )

    page = general_page(vc_turn_detector="smart-turn")

    assert page.turn_detector.currentText() == "Smart Turn v3 — not installed"
    assert page._turn_hint.text() == reason
    assert page.get_settings()["vc_turn_detector"] == "smart-turn"  # still the user's pick


def test_an_installed_detector_keeps_its_settings(general_page, monkeypatch):
    monkeypatch.setattr(
        "roomkit_ui.widgets.settings.feature_hints.unavailable_reason", lambda key: None
    )

    page = general_page(vc_turn_detector="smart-turn", vc_turn_incomplete_wait_ms="2500")

    assert page.turn_detector.currentText() == "Smart Turn v3"
    assert page.get_settings()["vc_turn_incomplete_wait_ms"] == "2500"
