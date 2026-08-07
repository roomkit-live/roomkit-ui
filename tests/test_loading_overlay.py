"""The startup curtain: covers the window, narrates steps, fades away."""

import time

from PySide6.QtWidgets import QApplication, QWidget

from roomkit_ui.widgets.loading_overlay import LoadingOverlay


def _pump(seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.005)


def test_overlay_covers_parent_and_updates_status(qapp):
    parent = QWidget()
    parent.resize(420, 700)
    parent.show()  # hidden widgets defer their Resize events
    overlay = LoadingOverlay(parent)
    try:
        assert overlay.isHidden()  # nothing until a session connects

        overlay.set_status("Reading CLI tools…")
        overlay.show_loading()
        assert not overlay.isHidden()
        assert overlay.geometry() == parent.rect()
        assert overlay._status.text() == "Reading CLI tools…"

        parent.resize(420, 900)
        QApplication.processEvents()
        assert overlay.geometry() == parent.rect()
    finally:
        parent.deleteLater()


def test_dismiss_fades_then_hides(qapp):
    parent = QWidget()
    parent.resize(420, 700)
    overlay = LoadingOverlay(parent)
    try:
        overlay.show_loading()
        overlay.dismiss()
        # Fading, not gone yet — the curtain lifts rather than vanishes.
        assert not overlay.isHidden()
        _pump(0.5)
        assert overlay.isHidden()
        assert not overlay._spinner._timer.isActive()
    finally:
        parent.deleteLater()


def test_show_during_fade_cancels_the_dismiss(qapp):
    parent = QWidget()
    parent.resize(420, 700)
    overlay = LoadingOverlay(parent)
    try:
        overlay.show_loading()
        overlay.dismiss()
        overlay.show_loading()  # user restarted a session mid-fade
        _pump(0.5)
        assert not overlay.isHidden()
    finally:
        parent.deleteLater()
