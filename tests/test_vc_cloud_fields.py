"""Voice-channel cloud model dropdowns keep whatever model was saved."""

import pytest
import shiboken6

from roomkit_ui.settings import _DEFAULTS
from roomkit_ui.widgets.settings.ai_page import _AIPage
from roomkit_ui.widgets.settings.vc_cloud_fields import VC_ANTHROPIC_MODELS


@pytest.fixture
def page_over(qapp):
    """Build an AI page over the defaults plus *overrides*; destroy it after."""
    pages: list[_AIPage] = []

    def _build(**overrides) -> _AIPage:
        pages.append(_AIPage({**_DEFAULTS, **overrides}))
        return pages[-1]

    yield _build
    for page in pages:
        shiboken6.delete(page)


@pytest.mark.parametrize(
    ("key", "model_id"),
    [
        ("vc_anthropic_model", "claude-opus-4-1-20250805"),  # retired from the lineup
        ("deepgram_model", "nova-3-medical"),
        ("elevenlabs_model", "eleven_ttv_v3"),
    ],
)
def test_a_saved_model_outside_the_lineup_is_kept(page_over, key, model_id):
    page = page_over(**{key: model_id})

    assert page.get_settings()[key] == model_id


def test_a_saved_model_in_the_lineup_is_selected_not_duplicated(page_over):
    page = page_over(vc_anthropic_model="claude-haiku-4-5-20251001")
    combo = page._cloud.vc_anthropic_model

    assert combo.currentData() == "claude-haiku-4-5-20251001"
    assert combo.findData("claude-haiku-4-5-20251001") == combo.currentIndex()
    assert combo.count() == len(VC_ANTHROPIC_MODELS)


def test_an_empty_elevenlabs_model_still_means_the_first_item(page_over):
    page = page_over(elevenlabs_model="")

    assert page.get_settings()["elevenlabs_model"] == "eleven_v3"
