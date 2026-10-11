"""How this install takes a component: an optional backend, one extra of the app."""

import importlib.metadata
import sys

import pytest

from roomkit_ui import components as comp
from roomkit_ui import features
from roomkit_ui.components import Installer, component_of, components, install_plan
from roomkit_ui.features import FEATURES

VERSION = importlib.metadata.version("roomkit-ui")


@pytest.fixture
def environment(monkeypatch):
    """A pip/pipx/uv-tool install: not frozen, not a source checkout."""
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(comp, "_editable_checkout", lambda: None)
    monkeypatch.setattr(comp.shutil, "which", lambda *_a, **_k: "/usr/bin/uv")
    return monkeypatch


def test_each_feature_comes_with_exactly_one_component():
    found = [key for c in components() for key in c.features]

    assert sorted(found) == sorted(FEATURES)
    assert len({c.extra for c in components()}) == len(components())
    assert component_of("openai-realtime").features == ("openai", "openai-realtime")
    assert component_of("hotkey").extra == "dictation"


def test_the_app_installs_its_own_extra_pinned_to_its_version(environment):
    plan = install_plan(component_of("gemini"))

    assert plan.how is Installer.APP
    assert plan.argv == (
        "/usr/bin/uv",
        "pip",
        "install",
        "--python",
        sys.executable,
        f"roomkit-ui[gemini]=={VERSION}",
    )
    assert plan.command.endswith(f"'roomkit-ui[gemini]=={VERSION}'")


def test_without_uv_the_environments_pip_installs_it(environment):
    environment.setattr(comp.shutil, "which", lambda *_a, **_k: None)
    environment.setattr(comp.importlib.util, "find_spec", lambda name: object())

    plan = install_plan(component_of("gemini"))

    assert plan.argv == (sys.executable, "-m", "pip", "install", f"roomkit-ui[gemini]=={VERSION}")


def test_without_uv_or_pip_the_user_gets_the_command(environment):
    environment.setattr(comp.shutil, "which", lambda *_a, **_k: None)
    environment.setattr(comp.importlib.util, "find_spec", lambda name: None)

    plan = install_plan(component_of("gemini"))

    assert plan.how is Installer.COMMAND
    assert plan.command == f"pip install 'roomkit-ui[gemini]=={VERSION}'"


def test_a_source_checkout_gets_the_uv_sync_that_keeps_what_is_there(monkeypatch, tmp_path):
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(comp, "_editable_checkout", lambda: tmp_path)

    plan = install_plan(component_of("gemini"))

    assert plan.how is Installer.COMMAND
    assert plan.command == "uv sync --inexact --extra gemini"
    assert str(tmp_path) in plan.note


def test_this_checkout_is_recognised_as_one():
    # The test suite runs from the source tree, installed editable.
    checkout = comp._editable_checkout()

    assert checkout is not None
    assert (checkout / "pyproject.toml").exists()


def test_a_frozen_build_installs_nothing(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    plan = install_plan(component_of("pocket-tts"))

    assert plan.how is Installer.NONE
    assert plan.argv == ()
    assert "not part of this build" in plan.note


def test_an_exclusive_extra_names_the_one_it_would_break(environment):
    environment.setattr(
        features,
        "missing_modules",
        lambda key: () if key == "smart-turn" else ("absent",),
    )

    plan = install_plan(component_of("neutts"))

    assert plan.conflicts == ("Smart Turn detector",)
    assert install_plan(component_of("gemini")).conflicts == ()


def test_a_uv_tool_install_is_told_an_upgrade_leaves_it_out(environment, tmp_path):
    (tmp_path / "uv-receipt.toml").write_text("[tool]\n")
    environment.setattr(comp.sys, "prefix", str(tmp_path))

    plan = install_plan(component_of("gemini"))

    assert "uv tool install 'roomkit-ui[gemini]'" in plan.note


def test_heavy_components_say_so_and_some_need_a_restart():
    assert "PyTorch" in component_of("pocket-tts").note
    assert component_of("mcp-apps").needs_restart
    assert not component_of("gemini").needs_restart
    assert component_of("gemini").note == ""
