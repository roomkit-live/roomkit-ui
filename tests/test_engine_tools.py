"""Tests for engine_tools pure helpers and the set_attitude lookup."""

import json

import pytest

from roomkit_ui import settings as settings_module
from roomkit_ui.engine import Engine
from roomkit_ui.engine_tools import compose_attitude_prompt


def test_compose_attitude_prompt_appends_section():
    out = compose_attitude_prompt("base prompt", "be cheerful")
    assert out.startswith("base prompt")
    assert "# Attitude" in out
    assert out.endswith("be cheerful")


def test_compose_attitude_prompt_empty_attitude_is_verbatim():
    assert compose_attitude_prompt("base prompt", "") == "base prompt"


def test_compose_attitude_prompt_empty_base():
    assert compose_attitude_prompt("", "") == ""
    assert "# Attitude" in compose_attitude_prompt("", "x")


# -- set_attitude reads the session's settings, not the keyring -------------
# load_settings() reads every secret from the OS keyring, synchronously on the
# event loop (a Keychain prompt on macOS), for one JSON list.


@pytest.fixture
def engine(qapp, monkeypatch):
    def keyring_read():
        raise AssertionError("set_attitude must not reload settings mid-session")

    monkeypatch.setattr(settings_module, "load_settings", keyring_read)
    eng = Engine()
    eng._session_settings = {
        "custom_attitudes": json.dumps([{"name": "Pirate", "text": "Talk like a pirate."}])
    }
    return eng


async def test_a_custom_attitude_comes_from_the_session_settings(engine):
    result = json.loads(await engine._apply_attitude_by_name("pirate"))

    assert result["status"] == "ok"
    assert result["attitude"] == "Pirate"
    assert engine._attitude == "Talk like a pirate."


async def test_an_unknown_attitude_lists_the_custom_ones_too(engine):
    result = json.loads(await engine._apply_attitude_by_name("Grumpy cat"))

    assert "error" in result
    assert "Pirate" in result["available"]
