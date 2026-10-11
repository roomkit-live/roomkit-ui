"""Installing a component while the app runs: one at a time, for the whole app.

The install runs the plan's argv as a child process; here a Python one-liner
stands in for uv or pip.
"""

import sys

import pytest
import shiboken6
from PySide6.QtWidgets import QApplication

from roomkit_ui import component_installer as ci
from roomkit_ui.components import Installer, InstallPlan, component_of
from roomkit_ui.widgets.settings import components_page


def _plan(code: str) -> InstallPlan:
    argv = (sys.executable, "-c", code)
    return InstallPlan(Installer.APP, argv=argv, command="pip install 'roomkit-ui[x]'")


@pytest.fixture
def runner(qapp, monkeypatch):
    """A fresh installer, as the app's one, running *code* for any component."""
    fresh = ci.ComponentInstaller()
    monkeypatch.setattr(ci, "_installer", fresh)
    script = {"code": "print('Collecting anthropic')\nprint('Installed 3 packages')"}

    def plan(_component):
        return _plan(script["code"])

    monkeypatch.setattr(ci, "install_plan", plan)
    monkeypatch.setattr(components_page, "install_plan", plan)
    fresh.script = script
    return fresh


def test_an_install_reports_its_output_and_success(runner, qtbot):
    lines: list[str] = []
    runner.output.connect(lines.append)

    with qtbot.waitSignal(runner.finished, timeout=10000) as done:
        assert runner.install(component_of("anthropic"))

    assert done.args == ["anthropic", True, "Anthropic (Claude) is installed."]
    assert lines == [
        "$ pip install 'roomkit-ui[x]'",
        "Collecting anthropic",
        "Installed 3 packages",
    ]
    assert runner.running is None
    assert runner.log() == lines


def test_a_failed_install_says_why(runner, qtbot):
    runner.script["code"] = "import sys; print('No matching distribution'); sys.exit(3)"

    with qtbot.waitSignal(runner.finished, timeout=10000) as done:
        runner.install(component_of("gemini"))

    assert done.args == [
        "gemini",
        False,
        "Could not install Google Gemini (exit 3): No matching distribution",
    ]


def test_one_install_at_a_time(runner, qtbot):
    runner.script["code"] = "import time; time.sleep(0.5)"

    with qtbot.waitSignal(runner.finished, timeout=10000):
        assert runner.install(component_of("gemini"))
        assert runner.running == component_of("gemini")
        assert not runner.install(component_of("anthropic"))


def test_a_cancelled_install_says_so(runner, qtbot):
    runner.script["code"] = "import time; time.sleep(30)"

    with qtbot.waitSignal(runner.finished, timeout=10000) as done:
        runner.install(component_of("gemini"))
        runner.cancel()

    assert done.args == ["gemini", False, "Google Gemini: installation cancelled."]


def test_an_installer_that_cannot_run_says_so(runner, qtbot, monkeypatch):
    plan = InstallPlan(Installer.APP, argv=("/nonexistent/uv", "pip"), command="uv pip")
    monkeypatch.setattr(ci, "install_plan", lambda _c: plan)

    with qtbot.waitSignal(runner.finished, timeout=10000) as done:
        runner.install(component_of("gemini"))

    assert done.args[1] is False
    assert any("Could not run the installer" in line for line in runner.log())


def test_a_component_the_app_does_not_install_here_is_not_started(runner, monkeypatch):
    plan = InstallPlan(Installer.COMMAND, command="uv sync --inexact --extra gemini")
    monkeypatch.setattr(ci, "install_plan", lambda _c: plan)

    assert not runner.install(component_of("gemini"))
    assert runner.running is None


def test_a_component_needing_a_restart_says_so(runner, qtbot):
    with qtbot.waitSignal(runner.finished, timeout=10000) as done:
        runner.install(component_of("mcp-apps"))

    assert done.args[2].endswith("restart RoomKit UI to use it.")


def test_a_restart_starts_the_same_command_once_this_one_quit(monkeypatch):
    started: list[tuple[str, list[str]]] = []
    hooks: list = []
    quits: list[bool] = []

    class _App:
        class aboutToQuit:  # noqa: N801 — mirrors the Qt signal
            connect = staticmethod(hooks.append)

        @staticmethod
        def quit():
            quits.append(True)

    monkeypatch.setattr(
        ci.QProcess, "startDetached", staticmethod(lambda p, a: started.append((p, a)))
    )
    monkeypatch.setattr(ci.sys, "orig_argv", ["/usr/bin/python3", "-m", "roomkit_ui"])

    ci.restart_app(_App)
    assert quits == [True] and started == []
    hooks[0]()

    assert started == [("/usr/bin/python3", ["-m", "roomkit_ui"])]


# -- the Components tab -----------------------------------------------------------------


def _row(page, extra):
    return next(r for r in page._rows if r.component.extra == extra)


def test_the_tab_installs_and_shows_the_install_running_then_done(runner, qtbot, monkeypatch):
    monkeypatch.setattr(
        type(component_of("gemini")), "installed", lambda self: self.extra != "gemini"
    )
    page = components_page._ComponentsPage({})
    try:
        row = _row(page, "gemini")
        assert row.status.text() == "Not installed"
        assert row.action.text() == "Install"

        with qtbot.waitSignal(runner.finished, timeout=10000):
            row.action.click()
            assert row.status.text() == "Installing…"
            assert page._cancel.isVisibleTo(page)

        assert "Collecting anthropic" in page._log.toPlainText()
        assert page._progress.text() == "Google Gemini is installed: restart RoomKit UI to use it."
        assert page._restart.isVisibleTo(page)  # still not importable: a restart helps
    finally:
        shiboken6.delete(page)


def test_in_a_checkout_the_tab_copies_the_command(qapp, monkeypatch):
    plan = InstallPlan(Installer.COMMAND, command="uv sync --inexact --extra gemini")
    monkeypatch.setattr(components_page, "install_plan", lambda _c: plan)
    monkeypatch.setattr(
        type(component_of("gemini")), "installed", lambda self: self.extra != "gemini"
    )
    page = components_page._ComponentsPage({})
    try:
        row = _row(page, "gemini")
        assert row.action.text() == "Copy command"

        row.action.click()

        assert QApplication.clipboard().text() == "uv sync --inexact --extra gemini"
        assert row.action.text() == "Copied"
    finally:
        shiboken6.delete(page)


def test_a_tab_opened_mid_install_shows_it_running(runner, qtbot):
    runner.script["code"] = "print('Downloading torch'); import time; time.sleep(30)"
    with qtbot.waitSignal(runner.output, timeout=10000, check_params_cb=lambda s: "torch" in s):
        runner.install(component_of("pocket-tts"))

    page = components_page._ComponentsPage({})
    try:
        assert "Downloading torch" in page._log.toPlainText()
        assert page._progress.text() == "Installing Pocket TTS (local, voice cloning)…"
        assert page._cancel.isVisibleTo(page)
    finally:
        with qtbot.waitSignal(runner.finished, timeout=10000):
            runner.cancel()
        shiboken6.delete(page)
