"""How this app was installed: the facts a component install or an update builds on."""

import json
import sys

import pytest

from roomkit_ui import install_env
from roomkit_ui.install_env import (
    InstallKind,
    install_kind,
    uv_tool_install_argv,
    uv_tool_receipt,
    with_extra,
)

RECEIPT = """\
[tool]
requirements = [
    { name = "roomkit-ui", extras = ["all", "smart-turn"] },
    { name = "rich", specifier = ">=13" },
]
python = "3.12"
entrypoints = [
    { name = "roomkit-ui", install-path = "/home/u/.local/bin/roomkit-ui", from = "roomkit-ui" },
]
"""


def _tool_env(tmp_path, receipt=RECEIPT, name="roomkit-ui"):
    env = tmp_path / "tools" / name
    env.mkdir(parents=True)
    (env / "uv-receipt.toml").write_text(receipt)
    return env


def test_a_receipt_says_what_the_tool_environment_was_made_with(tmp_path):
    env = _tool_env(tmp_path)

    receipt = uv_tool_receipt(env)

    assert receipt.extras == ("all", "smart-turn")
    assert receipt.python == "3.12"
    assert receipt.specifier == ""
    assert receipt.with_requirements == ("rich>=13",)
    assert receipt.rebuildable
    # uv acts on this very environment, whatever UV_TOOL_DIR the app was started with.
    assert receipt.environment() == (
        ("UV_TOOL_DIR", str(tmp_path / "tools")),
        ("UV_TOOL_BIN_DIR", "/home/u/.local/bin"),
    )


def test_a_receipt_extra_spelled_otherwise_is_still_exclusive(tmp_path):
    """uv records an extra as typed: "smart_turn" is smart-turn, which
    qwen3-tts must replace rather than join."""
    receipt = uv_tool_receipt(_tool_env(tmp_path, RECEIPT.replace('"smart-turn"', '"Smart_Turn"')))

    assert receipt.extras == ("all", "smart-turn")
    assert with_extra(receipt.extras, "qwen3-tts") == ("all", "qwen3-tts")


def test_a_receipt_of_another_tool_or_folder_is_not_ours(tmp_path):
    assert uv_tool_receipt(_tool_env(tmp_path, name="httpx")) is None
    other = RECEIPT.replace('name = "roomkit-ui", extras', 'name = "httpx", extras')
    assert uv_tool_receipt(_tool_env(tmp_path / "b", other)) is None
    assert uv_tool_receipt(tmp_path) is None  # no receipt at all
    assert uv_tool_receipt(_tool_env(tmp_path / "c", "not toml [")) is None


@pytest.mark.parametrize(
    "change",
    [
        ('{ name = "rich", specifier = ">=13" }', '{ name = "rich", git = "https://x/rich" }'),
        (
            'python = "3.12"',
            'python = "3.12"\nconstraints = [{ name = "idna", specifier = "<4" }]',
        ),
        ('python = "3.12"', 'python = "3.12"\n[tool.options]\nindex-url = "https://mirror/"'),
    ],
    ids=["git source", "constraints", "an index URL"],
)
def test_a_receipt_a_reinstall_would_lose_part_of_is_not_rebuilt(tmp_path, change):
    receipt = uv_tool_receipt(_tool_env(tmp_path, RECEIPT.replace(*change)))

    assert receipt is not None and not receipt.rebuildable


def test_the_link_mode_alone_keeps_a_receipt_rebuildable(tmp_path):
    text = RECEIPT + '\n[tool.options]\nlink-mode = "copy"\n'

    assert uv_tool_receipt(_tool_env(tmp_path, text)).rebuildable


def test_the_install_keeps_the_environment_python_and_never_pins_the_app(tmp_path):
    pinned = RECEIPT.replace(
        'extras = ["all", "smart-turn"] }', 'extras = ["all"], specifier = ">=0.3" }'
    )
    receipt = uv_tool_receipt(_tool_env(tmp_path, pinned))

    argv = uv_tool_install_argv("/bin/uv", receipt, ("all", "gemini"))

    assert argv == (
        "/bin/uv",
        "tool",
        "install",
        "--python",
        "3.12",
        "--with",
        "rich>=13",
        "roomkit-ui[all,gemini]>=0.3",  # the user's own constraint stays
    )
    # An update moves the app: --upgrade, and the user's constraint goes.
    upgrade = uv_tool_install_argv("/bin/uv", receipt, ("all",), upgrade=True)
    assert upgrade[:6] == ("/bin/uv", "tool", "install", "--upgrade", "--python", "3.12")
    assert upgrade[-1] == "roomkit-ui[all]"


def test_without_a_recorded_python_the_running_one_is_named(tmp_path):
    receipt = uv_tool_receipt(_tool_env(tmp_path, RECEIPT.replace('python = "3.12"\n', "")))

    argv = uv_tool_install_argv("uv", receipt, ())

    assert argv[3:5] == ("--python", "{}.{}".format(*sys.version_info[:2]))
    assert argv[-1] == "roomkit-ui"


def test_an_exclusive_extra_replaces_the_other_and_others_join():
    assert with_extra(("all", "smart-turn"), "neutts") == ("all", "neutts")
    assert with_extra(("all", "smart-turn"), "gemini") == ("all", "smart-turn", "gemini")
    assert with_extra(("all", "gemini"), "gemini") == ("all", "gemini")
    assert with_extra((), "neutts") == ("neutts",)


# -- what kind of install ------------------------------------------------------------------


@pytest.fixture
def python_install(monkeypatch, tmp_path):
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(install_env, "editable_checkout", lambda: None)
    monkeypatch.setattr(install_env.sys, "prefix", str(tmp_path / "env"))
    (tmp_path / "env").mkdir()
    return monkeypatch


def test_a_uv_tool_environment_is_known_by_its_receipt(python_install, tmp_path):
    env = _tool_env(tmp_path)
    python_install.setattr(install_env.sys, "prefix", str(env))

    assert install_kind() is InstallKind.UV_TOOL


def test_a_pipx_environment_is_known_by_its_metadata(python_install, tmp_path):
    metadata = {"main_package": {"package": "roomkit-ui", "package_or_url": "roomkit-ui[all]"}}
    (tmp_path / "env" / "pipx_metadata.json").write_text(json.dumps(metadata))

    assert install_kind() is InstallKind.PIPX


def test_any_other_environment_is_pip(python_install, tmp_path):
    (tmp_path / "env" / "pipx_metadata.json").write_text("{not json")

    assert install_kind() is InstallKind.PIP


def test_a_checkout_is_a_checkout(python_install, tmp_path):
    python_install.setattr(install_env, "editable_checkout", lambda: tmp_path)

    assert install_kind() is InstallKind.CHECKOUT


def test_a_built_app_from_the_homebrew_cask_says_so(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(install_env.sys, "platform", "darwin")
    monkeypatch.setattr(install_env, "_HOMEBREW_PREFIXES", (str(tmp_path),))
    monkeypatch.delenv("HOMEBREW_PREFIX", raising=False)

    assert install_kind() is InstallKind.FROZEN
    (tmp_path / "Caskroom" / "roomkit-ui").mkdir(parents=True)
    assert install_kind() is InstallKind.HOMEBREW
