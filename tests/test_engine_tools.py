"""Tests for engine_tools pure helpers."""

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
