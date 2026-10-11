"""A missing component said where it is missing, with the button that adds it:
under a provider combo, and in the chat when a session could not start."""

import sys

import pytest
import shiboken6
from PySide6.QtWidgets import QApplication, QComboBox

from roomkit_ui import component_installer as ci
from roomkit_ui import features
from roomkit_ui.components import Installer, InstallPlan
from roomkit_ui.widgets import install_offer
from roomkit_ui.widgets.chat_view import ChatView
from roomkit_ui.widgets.install_offer import InstallOffer
from roomkit_ui.widgets.settings.feature_hints import offer_install, populate_provider_combo

ENTRIES = [("Anthropic", "anthropic"), ("Google Gemini", "gemini")]
FEATURE_MAP = {"anthropic": "anthropic", "gemini": "gemini"}


@pytest.fixture
def gemini_missing(qapp, monkeypatch):
    """Gemini reads as missing until an install ends; installs run a one-liner."""
    state = {"installed": False}
    monkeypatch.setattr(
        features,
        "missing_modules",
        lambda key: ("google.genai",) if key == "gemini" and not state["installed"] else (),
    )
    monkeypatch.setattr(ci.features, "refresh", lambda: state.update(installed=True))
    plan = InstallPlan(
        Installer.APP, argv=(sys.executable, "-c", "print('ok')"), command="pip install x"
    )
    monkeypatch.setattr(ci, "install_plan", lambda _c: plan)
    monkeypatch.setattr(install_offer, "install_plan", lambda _c: plan)
    monkeypatch.setattr(ci, "_installer", ci.ComponentInstaller())
    return state


def _combo() -> QComboBox:
    combo = QComboBox()
    populate_provider_combo(combo, ENTRIES, FEATURE_MAP)
    return combo


def test_the_offer_shows_only_while_a_missing_provider_is_picked(gemini_missing):
    combo = _combo()
    offer = offer_install(combo, ENTRIES, FEATURE_MAP)
    try:
        assert offer.isHidden()  # Anthropic is installed

        combo.setCurrentIndex(1)

        assert not offer.isHidden()
        assert offer._label.text() == "Google Gemini is not installed."
        assert offer._button.text() == "Install"
    finally:
        shiboken6.delete(offer)
        shiboken6.delete(combo)


def test_installing_from_the_offer_relabels_the_combo(gemini_missing, qtbot):
    combo = _combo()
    combo.setCurrentIndex(1)
    offer = offer_install(combo, ENTRIES, FEATURE_MAP)
    try:
        assert combo.itemText(1) == "Google Gemini — not installed"

        with qtbot.waitSignal(offer.installed, timeout=10000):
            offer._button.click()

        assert combo.itemText(1) == "Google Gemini"
        assert offer._label.text() == "Google Gemini is installed."
        assert not offer._button.isVisibleTo(offer)
    finally:
        shiboken6.delete(offer)
        shiboken6.delete(combo)


def test_in_a_checkout_the_offer_copies_the_command(gemini_missing, monkeypatch):
    plan = InstallPlan(Installer.COMMAND, command="uv sync --inexact --extra gemini")
    monkeypatch.setattr(install_offer, "install_plan", lambda _c: plan)
    offer = InstallOffer("gemini")
    try:
        assert offer._button.text() == "Copy command"
        offer._button.click()
        assert QApplication.clipboard().text() == "uv sync --inexact --extra gemini"
    finally:
        shiboken6.delete(offer)


def test_a_frozen_build_says_why_and_offers_no_button(gemini_missing, monkeypatch):
    plan = InstallPlan(Installer.NONE, note="It needs a Python install.")
    monkeypatch.setattr(install_offer, "install_plan", lambda _c: plan)
    offer = InstallOffer("gemini")
    try:
        assert offer._label.text() == "Google Gemini is not installed. It needs a Python install."
        assert offer._button.isHidden()
    finally:
        shiboken6.delete(offer)


def test_an_exclusive_extra_is_sent_to_the_components_tab(gemini_missing, monkeypatch):
    plan = InstallPlan(Installer.APP, argv=("x",), command="x", conflicts=("Smart Turn",))
    monkeypatch.setattr(install_offer, "install_plan", lambda _c: plan)
    offer = InstallOffer("gemini")
    try:
        offer._button.click()

        assert ci.installer().running is None
        assert "Settings → Components" in offer._label.text()
    finally:
        shiboken6.delete(offer)


def test_a_session_that_could_not_start_offers_the_install_in_the_chat(gemini_missing, qtbot):
    chat = ChatView()
    try:
        chat.add_install_offer("gemini")
        (offer,) = chat.findChildren(InstallOffer)
        assert offer._label.text() == (
            "The session could not start: Google Gemini is not installed."
        )

        with qtbot.waitSignal(offer.installed, timeout=10000):
            offer._button.click()

        assert offer._label.text() == "Google Gemini is installed. Start the session again."
    finally:
        shiboken6.delete(chat)
