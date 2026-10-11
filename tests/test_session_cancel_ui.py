"""A session being built can be cancelled from the ordinary conversation controls."""

from roomkit_ui.engine_state import EngineState
from roomkit_ui.widgets.conversation_composer import ConversationComposer


def _clicks(bar: ConversationComposer) -> list[str]:
    seen: list[str] = []
    bar.start_requested.connect(lambda: seen.append("start"))
    bar.stop_requested.connect(lambda: seen.append("stop"))
    return seen


def test_cancel_while_connecting_asks_to_stop(qapp):
    bar = ConversationComposer()
    seen = _clicks(bar)

    bar.set_state(EngineState.CONNECTING)
    bar._live_button.click()

    assert seen == ["stop"]
    bar.deleteLater()


def test_the_button_starts_again_once_idle(qapp):
    bar = ConversationComposer()
    seen = _clicks(bar)

    for state in (EngineState.CONNECTING, EngineState.STOPPING, EngineState.IDLE):
        bar.set_state(state)
    bar._live_button.click()

    assert seen == ["start"]
    bar.deleteLater()
