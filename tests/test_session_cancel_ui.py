"""A session being built can be cancelled from the window.

The center button read "Cancel" while connecting but emitted start_requested
(its _is_active was False), and the loading overlay covered the control bar
anyway — a start that hung on an MCP server could not be stopped.
"""

from PySide6.QtWidgets import QWidget

from roomkit_ui.engine_state import EngineState
from roomkit_ui.widgets.control_bar import ControlBar
from roomkit_ui.widgets.loading_overlay import LoadingOverlay


def _clicks(bar: ControlBar) -> list[str]:
    seen: list[str] = []
    bar.start_requested.connect(lambda: seen.append("start"))
    bar.stop_requested.connect(lambda: seen.append("stop"))
    return seen


def test_cancel_while_connecting_asks_to_stop(qapp):
    bar = ControlBar()
    seen = _clicks(bar)

    bar.set_state(EngineState.CONNECTING)
    bar._center_btn.click()

    assert seen == ["stop"]
    bar.deleteLater()


def test_the_button_starts_again_once_idle(qapp):
    bar = ControlBar()
    seen = _clicks(bar)

    for state in (EngineState.CONNECTING, EngineState.STOPPING, EngineState.IDLE):
        bar.set_state(state)
    bar._center_btn.click()

    assert seen == ["start"]
    bar.deleteLater()


def test_the_loading_overlay_offers_a_cancel(qapp):
    parent = QWidget()
    overlay = LoadingOverlay(parent)
    cancelled: list[bool] = []
    overlay.cancel_requested.connect(lambda: cancelled.append(True))

    overlay.show_loading()
    overlay._cancel.click()

    assert cancelled == [True]
    parent.deleteLater()
