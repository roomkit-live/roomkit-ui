"""Voice-channel cloud model dropdowns keep whatever model was saved."""

import pytest
import shiboken6

from roomkit_ui.settings import _DEFAULTS
from roomkit_ui.widgets.settings.vc_cloud_fields import ELEVENLABS_MODELS, VC_ANTHROPIC_MODELS
from roomkit_ui.widgets.settings.voice_setup import VoiceSetup


@pytest.fixture
def page_over(qapp):
    """Build an AI page over the defaults plus *overrides*; destroy it after."""
    pages: list[VoiceSetup] = []

    def _build(**overrides) -> VoiceSetup:
        pages.append(VoiceSetup({**_DEFAULTS, **overrides}))
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

    assert page.get_settings()["elevenlabs_model"] == "eleven_v4"


# -- lineups come from roomkit's catalogs ---------------------------------------


def test_the_claude_lineup_is_the_catalogs_current_models():
    from roomkit.providers.anthropic.models import MODELS

    ids = [model_id for _label, model_id in VC_ANTHROPIC_MODELS]
    deprecated = {m.id for m in MODELS if m.deprecated}
    assert "claude-sonnet-5-5" in ids
    assert not deprecated & set(ids)
    # The dated Haiku 4.5 and its alias share a name: one entry, the first listed.
    assert "claude-haiku-4-5-20251001" in ids
    assert "claude-haiku-4-5" not in ids
    assert ("Claude Sonnet 5.5", "claude-sonnet-5-5") in VC_ANTHROPIC_MODELS


def test_the_openai_lineup_leaves_out_models_that_refuse_a_voice_turn():
    from roomkit_ui.widgets.settings.vc_cloud_fields import VC_OPENAI_MODELS

    ids = [model_id for _label, model_id in VC_OPENAI_MODELS]
    assert "gpt-4o" in ids
    assert "gpt-5.5" in ids
    assert "gpt-5.5-pro" not in ids  # Responses API only
    assert "gpt-6.1-sol" not in ids  # takes no tools on Chat Completions
    assert "gpt-5" not in ids  # deprecated


def test_the_gemini_lineup_leaves_out_deprecated_models():
    from roomkit_ui.widgets.settings.vc_cloud_fields import VC_GEMINI_MODELS

    ids = [model_id for _label, model_id in VC_GEMINI_MODELS]
    assert "gemini-3.8-flash" in ids
    assert "gemini-2.5-pro" not in ids


def test_a_saved_deprecated_claude_model_is_kept_and_named_deprecated(page_over):
    page = page_over(vc_anthropic_model="claude-sonnet-4-20250514")
    combo = page._cloud.vc_anthropic_model

    assert combo.currentText() == "Claude Sonnet 4 (deprecated)"
    assert page.get_settings()["vc_anthropic_model"] == "claude-sonnet-4-20250514"


def test_editable_lineups_show_ids_and_keep_a_typed_one(page_over):
    page = page_over(vc_openai_model="ft:gpt-4o:acme", vc_gemini_model="gemini-3.8-flash")
    cloud = page._cloud

    assert cloud.vc_openai_model.currentText() == "ft:gpt-4o:acme"
    assert cloud.vc_gemini_model.currentText() == "gemini-3.8-flash"
    settings = page.get_settings()
    assert settings["vc_openai_model"] == "ft:gpt-4o:acme"
    assert settings["vc_gemini_model"] == "gemini-3.8-flash"


@pytest.mark.parametrize("model_id", ["eleven_v4", "eleven_v4_turbo"])
def test_the_v4_models_are_offered(page_over, model_id):
    page = page_over(elevenlabs_model=model_id)

    assert page.get_settings()["elevenlabs_model"] == model_id
    assert page._cloud.elevenlabs_model.count() == len(ELEVENLABS_MODELS)


@pytest.mark.parametrize("streams", [True, False])
def test_the_stream_input_toggle_keeps_its_value(page_over, streams):
    page = page_over(elevenlabs_stream_input=streams)

    assert page.get_settings()["elevenlabs_stream_input"] is streams


def test_the_stream_input_toggle_shows_with_elevenlabs_only(page_over):
    page = page_over(vc_tts_provider="elevenlabs")
    toggle = page._cloud.elevenlabs_stream_input
    assert not toggle.isHidden()

    page._cloud.update_tts_visibility("piper")
    assert toggle.isHidden()


def test_gradium_disclosure_tracks_provider_and_preserves_hidden_edits(page_over):
    page = page_over(conversation_mode="voice_channel", vc_stt_provider="gradium")
    page.show()
    cloud = page._cloud
    cloud.gradium_advanced.button.click()
    assert cloud.gradium_speed.isVisible()
    cloud.gradium_speed.setText("1.2")
    page.vc_stt_provider.setCurrentIndex(0)
    assert not cloud.gradium_advanced.isVisible()
    page.vc_stt_provider.setCurrentIndex(1)
    assert not cloud.gradium_advanced.button.isChecked()
    cloud.gradium_advanced.button.click()
    assert cloud.gradium_speed.isVisible()
    assert page.get_settings()["gradium_speed"] == "1.2"
