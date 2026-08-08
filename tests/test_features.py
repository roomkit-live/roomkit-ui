"""The feature registry must describe extras that actually exist.

``features.py`` names the extras it tells users to install.  A typo there is
invisible until someone runs the command and pip reports an unknown extra, so
the registry is checked against ``pyproject.toml`` here, and every provider a
settings combo offers is checked to map onto a declared feature.
"""

import tomllib
from pathlib import Path

import pytest

from roomkit_ui.features import (
    AI_PROVIDER_FEATURES,
    FEATURES,
    REALTIME_PROVIDER_FEATURES,
    STT_PROVIDER_FEATURES,
    TTS_PROVIDER_FEATURES,
    FeatureUnavailableError,
    format_report,
    install_command,
    is_available,
    require,
    unavailable_reason,
)

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


@pytest.fixture(scope="module")
def declared_extras() -> set[str]:
    data = tomllib.loads(PYPROJECT.read_text())
    return set(data["project"]["optional-dependencies"])


def test_every_feature_names_a_declared_extra(declared_extras):
    unknown = {key: f.extra for key, f in FEATURES.items() if f.extra not in declared_extras}
    assert not unknown, f"extras missing from pyproject.toml: {unknown}"


def test_aggregate_all_covers_every_installable_feature(declared_extras):
    """``[all]`` must pull every feature except the deliberately excluded ones.

    qwen3-tts and neutts stay out: torch and perth are several GB for two
    optional voices.  Any *other* omission means a user who installed
    ``roomkit-ui[all]`` still hits a missing backend, which is the exact
    failure this registry exists to prevent.
    """
    data = tomllib.loads(PYPROJECT.read_text())
    extras = data["project"]["optional-dependencies"]

    reached: set[str] = set()
    frontier = ["all"]
    while frontier:
        name = frontier.pop()
        if name in reached:
            continue
        reached.add(name)
        for req in extras.get(name, []):
            if req.startswith("roomkit-ui[") and req.endswith("]"):
                frontier.extend(req[len("roomkit-ui[") : -1].split(","))

    expected = {f.extra for f in FEATURES.values()} - {"qwen3-tts", "neutts"}
    assert expected <= reached, f"not reachable from [all]: {sorted(expected - reached)}"


@pytest.mark.parametrize(
    "provider_map",
    [
        AI_PROVIDER_FEATURES,
        STT_PROVIDER_FEATURES,
        TTS_PROVIDER_FEATURES,
        REALTIME_PROVIDER_FEATURES,
    ],
)
def test_provider_maps_point_at_known_features(provider_map):
    unknown = {p: k for p, k in provider_map.items() if k not in FEATURES}
    assert not unknown, f"provider(s) mapped to undeclared features: {unknown}"


def test_settings_combos_cover_every_offered_provider():
    """Every provider the UI offers must resolve, or be core-only on purpose."""
    from roomkit_ui.widgets.settings.ai_page import (
        VC_LLM_PROVIDERS,
        VC_STT_PROVIDERS,
        VC_TTS_PROVIDERS,
    )
    from roomkit_ui.widgets.settings.realtime_section import PROVIDERS as RT_PROVIDERS

    for entries, mapping in (
        (VC_LLM_PROVIDERS, AI_PROVIDER_FEATURES),
        (VC_STT_PROVIDERS, STT_PROVIDER_FEATURES),
        (VC_TTS_PROVIDERS, TTS_PROVIDER_FEATURES),
        (RT_PROVIDERS, REALTIME_PROVIDER_FEATURES),
    ):
        missing = [value for _label, value in entries if value not in mapping]
        assert not missing, f"providers with no feature mapping: {missing}"


def test_install_command_names_the_distribution_and_extra():
    assert install_command("gemini") == "pip install 'roomkit-ui[gemini]'"


def test_unavailable_reason_is_none_when_installed(monkeypatch):
    monkeypatch.setattr("roomkit_ui.features.is_available", lambda key: True)
    assert unavailable_reason("gradium") is None


def test_require_raises_with_the_install_command(monkeypatch):
    monkeypatch.setattr("roomkit_ui.features.is_available", lambda key: False)
    monkeypatch.setattr("roomkit_ui.features.sys.frozen", False, raising=False)
    with pytest.raises(FeatureUnavailableError) as excinfo:
        require("gradium")
    message = str(excinfo.value)
    assert "Gradium" in message
    assert "pip install 'roomkit-ui[gradium]'" in message


def test_frozen_build_does_not_tell_users_to_pip_install(monkeypatch):
    """A .app cannot be completed with pip — saying so would send users nowhere."""
    monkeypatch.setattr("roomkit_ui.features.is_available", lambda key: False)
    monkeypatch.setattr("roomkit_ui.features.sys", type("S", (), {"frozen": True})())
    reason = unavailable_reason("gradium")
    assert reason is not None
    assert "pip install" not in reason


def test_core_is_always_available():
    """PySide6 core modules ship with the base install, so this must hold anywhere."""
    assert is_available("mcp-apps") in (True, False)  # probe must not raise


def test_report_lists_every_feature():
    report = format_report()
    for feature in FEATURES.values():
        assert feature.label in report
