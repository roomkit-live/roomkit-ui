"""Is a newer RoomKit UI out, and how does this install take it?  No network:
httpx's MockTransport answers for PyPI and GitHub."""

import sys

import httpx
import pytest

from roomkit_ui import updates
from roomkit_ui.components import Installer
from roomkit_ui.install_env import InstallKind
from roomkit_ui.updates import fetch_latest, final_version, is_newer, update_plan

RECEIPT = """\
[tool]
requirements = [{ name = "roomkit-ui", extras = ["all"] }]
python = "3.12"
"""


@pytest.mark.parametrize(
    ("candidate", "current", "newer"),
    [
        ("0.4.0", "0.3.1", True),
        ("0.10.0", "0.9.9", True),
        ("0.3.1", "0.3.1", False),
        ("0.3.0", "0.3.1", False),
        ("0.4", "0.3.9", True),
        ("0.4.0rc1", "0.3.1", False),  # a pre-release is never offered
        ("0.4.0.dev3", "0.3.1", False),
        ("0.4.0", "0.4.0rc1", True),  # a running pre-release is older than its release
        ("0.4.0", "0.4.0.dev2", True),
        ("0.4.0", "", False),  # nothing to compare with
        ("", "0.3.1", False),
    ],
)
def test_only_a_newer_final_release_counts(candidate, current, newer):
    assert is_newer(candidate, current) is newer


def test_a_final_version_reads_as_numbers():
    assert final_version("v1.2.3") == (1, 2, 3)
    assert final_version("1.2") == (1, 2, 0)
    assert final_version("1.2.3rc1") is None
    assert final_version("1.2.3+local") is None


def _transport(status=200, body=None, headers=None, seen=None):
    def handle(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, json=body, headers=headers or {})

    return httpx.MockTransport(handle)


async def test_a_python_install_reads_pypi_and_keeps_the_etag():
    seen: list[httpx.Request] = []
    body = {"info": {"version": "0.4.0", "yanked": False}}
    transport = _transport(body=body, headers={"ETag": '"abc"'}, seen=seen)

    found = await fetch_latest(InstallKind.UV_TOOL, transport=transport)

    assert found == updates.LatestRelease("0.4.0", '"abc"')
    assert str(seen[0].url) == updates.PYPI_URL
    assert "If-None-Match" not in seen[0].headers


async def test_an_unchanged_answer_is_said_so():
    seen: list[httpx.Request] = []

    found = await fetch_latest(InstallKind.PIP, '"abc"', transport=_transport(304, seen=seen))

    assert found.unchanged and found.version is None and found.etag == '"abc"'
    assert seen[0].headers["If-None-Match"] == '"abc"'


async def test_a_pre_release_on_pypi_or_a_yanked_one_is_not_offered():
    for info in ({"version": "0.5.0b1"}, {"version": "0.5.0", "yanked": True}, {}):
        found = await fetch_latest(InstallKind.PIP, transport=_transport(body={"info": info}))
        assert found.version is None


async def test_a_built_app_reads_the_latest_github_release():
    seen: list[httpx.Request] = []
    body = {"tag_name": "v0.4.0", "draft": False, "prerelease": False}

    found = await fetch_latest(InstallKind.HOMEBREW, transport=_transport(body=body, seen=seen))

    assert found.version == "0.4.0"
    assert str(seen[0].url) == updates.GITHUB_LATEST_URL
    marked = {**body, "prerelease": True}
    prerelease = await fetch_latest(InstallKind.FROZEN, transport=_transport(body=marked))
    assert prerelease.version is None


async def test_a_server_error_raises_for_the_caller_to_stay_quiet_about():
    with pytest.raises(httpx.HTTPStatusError):
        await fetch_latest(InstallKind.PIP, transport=_transport(503))


def test_release_notes_are_the_release_page():
    assert updates.release_notes_url("0.4.0").endswith("/releases/tag/v0.4.0")


# -- how each install takes it -------------------------------------------------------------


@pytest.fixture
def linux(monkeypatch):
    monkeypatch.setattr(updates.sys, "platform", "linux")
    monkeypatch.setattr(updates, "uv_path", lambda: "/usr/bin/uv")
    return monkeypatch


@pytest.fixture
def tool_env(linux, tmp_path):
    env = tmp_path / "tools" / "roomkit-ui"
    env.mkdir(parents=True)
    (env / "uv-receipt.toml").write_text(RECEIPT)
    linux.setattr(updates.sys, "prefix", str(env))
    return env


def test_a_receipt_recording_every_component_is_upgraded_as_it_stands(tool_env, linux):
    linux.setattr(updates, "kept_extras", lambda recorded: tuple(recorded))

    plan = update_plan(InstallKind.UV_TOOL)

    assert plan.how is Installer.APP
    assert plan.argv == ("/usr/bin/uv", "tool", "upgrade", "roomkit-ui")
    assert ("UV_TOOL_DIR", str(tool_env.parent)) in plan.env


def test_components_outside_the_receipt_join_it_on_the_way(tool_env, linux):
    linux.setattr(updates, "kept_extras", lambda recorded: (*recorded, "smart-turn"))

    plan = update_plan(InstallKind.UV_TOOL)

    assert plan.argv == (
        "/usr/bin/uv",
        "tool",
        "install",
        "--upgrade",
        "--python",
        "3.12",
        "roomkit-ui[all,smart-turn]",
    )
    assert plan.command.endswith("'roomkit-ui[all,smart-turn]'")


def test_a_receipt_the_app_cannot_rebuild_is_upgraded_as_it_stands(tool_env, linux):
    (tool_env / "uv-receipt.toml").write_text(
        RECEIPT + 'constraints = [{ name = "idna", specifier = "<4" }]\n'
    )
    linux.setattr(updates, "kept_extras", lambda recorded: (*recorded, "smart-turn"))

    assert update_plan(InstallKind.UV_TOOL).argv[1:3] == ("tool", "upgrade")


def test_on_windows_the_user_runs_it_once_the_app_has_quit(tool_env, linux):
    linux.setattr(updates.sys, "platform", "win32")
    linux.setattr(updates, "kept_extras", lambda recorded: tuple(recorded))

    plan = update_plan(InstallKind.UV_TOOL)

    assert plan.how is Installer.COMMAND
    assert plan.command == "/usr/bin/uv tool upgrade roomkit-ui"
    assert plan.note.startswith("Quit RoomKit UI first")


def test_pipx_upgrades_its_own_environment(linux, tmp_path):
    env = tmp_path / "pipx" / "venvs" / "roomkit-ui"
    env.mkdir(parents=True)
    linux.setattr(updates.sys, "prefix", str(env))
    linux.setattr(updates.shutil, "which", lambda *_a, **_k: "/usr/bin/pipx")

    plan = update_plan(InstallKind.PIPX)

    assert plan.argv == ("/usr/bin/pipx", "upgrade", "roomkit-ui")
    assert plan.env == (("PIPX_HOME", str(tmp_path / "pipx")),)


def test_a_pip_environment_upgrades_the_app_with_what_it_carries(linux):
    linux.setattr(updates, "installed_extras", lambda: ("anthropic", "local-voice"))
    linux.setattr(
        updates,
        "installer_argv",
        lambda spec, upgrade: ("uv", "pip", "install", "-U" if upgrade else "", spec),
    )

    plan = update_plan(InstallKind.PIP)

    assert plan.how is Installer.APP
    assert plan.argv == ("uv", "pip", "install", "-U", "roomkit-ui[anthropic,local-voice]")


def test_the_upgrade_moves_only_the_app_with_uv_pip(linux):
    from roomkit_ui import components

    linux.setattr(components, "uv_path", lambda: "/usr/bin/uv")

    argv = components.installer_argv("roomkit-ui[gemini]", upgrade=True)

    assert argv == (
        "/usr/bin/uv",
        "pip",
        "install",
        "--python",
        sys.executable,
        "--upgrade-package",
        "roomkit-ui",
        "roomkit-ui[gemini]",
    )


def test_a_checkout_a_built_app_and_the_cask_get_what_the_user_does():
    checkout = update_plan(InstallKind.CHECKOUT)
    assert checkout.how is Installer.COMMAND and "git pull" in checkout.command

    assert update_plan(InstallKind.FROZEN).how is Installer.NONE  # the release page

    cask = update_plan(InstallKind.HOMEBREW)
    assert cask.how is Installer.COMMAND
    assert cask.command == "brew upgrade --cask roomkit-ui"
