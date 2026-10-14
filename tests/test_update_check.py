"""When the app looks for a newer release, what it remembers, and the update
offered in About and on the home screen.  The check's network call is a fake;
the update runs a Python one-liner where uv or pip would."""

import sys

import pytest
import shiboken6
from PySide6.QtWidgets import QApplication

from roomkit_ui import component_installer as ci
from roomkit_ui import update_check
from roomkit_ui.components import Installer, InstallPlan
from roomkit_ui.install_env import InstallKind
from roomkit_ui.settings import load_setting, load_settings, save_settings
from roomkit_ui.update_check import CHECK_EVERY, UpdateService
from roomkit_ui.updates import LatestRelease
from roomkit_ui.widgets import update_notice
from roomkit_ui.widgets.settings import about_page
from roomkit_ui.widgets.update_notice import UpdateNotice

NOW = 1_800_000_000.0


class FakeRelease:
    """The endpoint: answers *found*, or raises *error*; records the ETag sent."""

    def __init__(self, found=None, error=None):
        self.found = found or LatestRelease("0.4.0", '"v1"')
        self.error = error
        self.etags: list[str] = []

    async def __call__(self, kind, etag):
        self.etags.append(etag)
        if self.error is not None:
            raise self.error
        return self.found


@pytest.fixture
def service(qapp, monkeypatch):
    """The app's update service, for a pip install running 0.3.1."""
    fresh = UpdateService(
        kind=InstallKind.PIP, current="0.3.1", fetch=FakeRelease(), clock=lambda: NOW
    )
    monkeypatch.setattr(update_check, "_service", fresh)
    monkeypatch.setattr(ci, "_installer", ci.ComponentInstaller())
    return fresh


def test_a_check_is_due_once_a_day_and_only_when_switched_on(service):
    assert service.due()  # never checked
    save_settings({"update_checked_at": str(int(NOW - 3600))})
    assert not service.due()
    save_settings({"update_checked_at": str(int(NOW - CHECK_EVERY))})
    assert service.due()
    save_settings({"update_check": False})
    assert not service.due()
    assert not service.check_if_due()


def test_a_source_checkout_is_never_checked(qapp):
    checkout = UpdateService(kind=InstallKind.CHECKOUT, current="0.3.1", fetch=FakeRelease())

    assert not checkout.due()


async def test_a_check_remembers_what_it_found_and_offers_it(service):
    await service.check()

    assert load_setting("update_latest") == "0.4.0"
    assert load_setting("update_etag") == '"v1"'
    assert float(load_setting("update_checked_at")) == NOW
    assert service.latest == service.notice == "0.4.0"
    assert not service.due()


async def test_the_next_check_sends_the_etag_and_an_unchanged_answer_keeps_the_release(service):
    save_settings({"update_latest": "0.4.0", "update_etag": '"v1"'})
    service._fetch = fake = FakeRelease(LatestRelease(None, '"v1"', unchanged=True))

    await service.check()

    assert fake.etags == ['"v1"']
    assert service.latest == "0.4.0"


async def test_offline_the_check_says_nothing_and_tries_again_later(service):
    import httpx

    service._fetch = FakeRelease(error=httpx.ConnectError("no route to host"))

    await service.check()  # no exception

    assert service.latest == ""
    assert service.error == "no route to host"
    assert service.due()  # a failure is no check


async def test_a_dismissed_release_stays_quiet_until_a_newer_one(service):
    await service.check()
    service.dismiss()

    assert service.notice == "" and service.latest == "0.4.0"
    service._fetch = FakeRelease(LatestRelease("0.5.0", '"v2"'))
    await service.check()
    assert service.notice == "0.5.0"


def test_the_running_version_or_an_older_one_is_no_update(service):
    save_settings({"update_latest": "0.3.1"})

    assert service.latest == ""


def test_no_update_runs_under_an_open_session(service, monkeypatch):
    plan = InstallPlan(Installer.APP, argv=(sys.executable, "-c", "pass"), command="uv x")
    monkeypatch.setattr(update_check.updates, "update_plan", lambda kind: plan)
    service.set_session_open(True)

    assert service.run_update().startswith("End the session first")
    assert not ci.installer().busy


async def test_the_update_runs_on_the_installer_and_offers_a_restart(service, qtbot, monkeypatch):
    plan = InstallPlan(Installer.APP, argv=(sys.executable, "-c", "print('done')"), command="uv x")
    monkeypatch.setattr(update_check.updates, "update_plan", lambda kind: plan)
    versions = iter(["0.3.1", "0.4.0"])  # before, then on disk after
    monkeypatch.setattr(ci, "current_version", lambda: next(versions))

    with qtbot.waitSignal(ci.installer().finished, timeout=10000) as done:
        assert service.run_update() == ""

    assert done.args == [
        ci.UPDATE,
        True,
        "RoomKit UI 0.4.0 is installed: restart RoomKit UI to use it.",
    ]
    assert ci.installer().last_result is None  # the Components page's stays its own


def test_an_update_with_nothing_new_says_so(service, qtbot, monkeypatch):
    plan = InstallPlan(Installer.APP, argv=(sys.executable, "-c", "pass"), command="uv x")
    monkeypatch.setattr(ci, "current_version", lambda: "0.3.1")

    with qtbot.waitSignal(ci.installer().finished, timeout=10000) as done:
        ci.installer().update(plan)

    assert done.args[1] is False
    assert done.args[2].startswith("Nothing to update")


# -- About ---------------------------------------------------------------------------------


def test_the_about_switch_round_trips_through_settings(service):
    page = about_page._AboutPage({"update_check": False})
    try:
        assert not page.update_check.isChecked()
        page.update_check.setChecked(True)
        save_settings(page.get_settings())
        assert load_settings()["update_check"] is True
        page.update_check.setChecked(False)
        save_settings(page.get_settings())
        assert load_settings()["update_check"] is False
    finally:
        shiboken6.delete(page)


def test_about_offers_a_newer_release_with_its_notes(service, monkeypatch):
    save_settings({"update_latest": "0.4.0"})
    plan = InstallPlan(Installer.APP, argv=("uv",), command="uv tool upgrade roomkit-ui")
    monkeypatch.setattr(update_check.updates, "update_plan", lambda kind: plan)
    page = about_page._AboutPage({})
    try:
        assert page.update_status.text() == "RoomKit UI 0.4.0 is available."
        assert page.update_button.isVisibleTo(page)
        assert page.update_button.text() == "Update"
        assert page.release_notes.isVisibleTo(page)
        assert not page.restart_button.isVisibleTo(page)
    finally:
        shiboken6.delete(page)


def test_about_says_up_to_date_after_a_check(service):
    save_settings({"update_checked_at": str(int(NOW)), "update_latest": "0.3.1"})
    page = about_page._AboutPage({})
    try:
        assert page.update_status.text() == "RoomKit UI is up to date."
        assert not page.update_button.isVisibleTo(page)
        assert page.check_now.isVisibleTo(page)
    finally:
        shiboken6.delete(page)


# -- the home screen's notice --------------------------------------------------------------


@pytest.fixture
def command_plan(monkeypatch):
    plan = InstallPlan(
        Installer.COMMAND,
        command="brew upgrade --cask roomkit-ui",
        note="Installed with Homebrew.",
    )
    monkeypatch.setattr(update_check.updates, "update_plan", lambda kind: plan)
    return plan


def test_the_notice_offers_the_release_and_a_dismiss_keeps_it_quiet(service, command_plan):
    save_settings({"update_latest": "0.4.0"})
    notice = UpdateNotice()
    try:
        assert not notice.isHidden()
        assert notice._label.text() == "RoomKit UI 0.4.0 is available."
        assert notice._update.text() == "Copy command"

        notice._dismiss.click()

        assert notice.isHidden()
        assert load_setting("update_dismissed") == "0.4.0"
    finally:
        shiboken6.delete(notice)


def test_the_notice_hides_in_a_session(service, command_plan):
    save_settings({"update_latest": "0.4.0"})
    notice = UpdateNotice()
    try:
        notice.set_session_open(True)
        assert notice.isHidden()
        notice.set_session_open(False)
        assert not notice.isHidden()
    finally:
        shiboken6.delete(notice)


def test_where_the_user_updates_the_command_is_copied(service, command_plan):
    save_settings({"update_latest": "0.4.0"})
    notice = UpdateNotice()
    try:
        notice._update.click()

        assert QApplication.clipboard().text() == "brew upgrade --cask roomkit-ui"
        assert "Installed with Homebrew." in notice._label.text()
    finally:
        shiboken6.delete(notice)


def test_nothing_newer_no_notice(service):
    notice = UpdateNotice()
    try:
        assert notice.isHidden()
        assert update_notice.update_service() is service
    finally:
        shiboken6.delete(notice)
