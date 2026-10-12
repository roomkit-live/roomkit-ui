"""The LLM tab's thinking and effort reach the voice channel's AIChannel."""

import pytest
import shiboken6
from roomkit.channels.ai import AIChannel
from roomkit.providers.ai.mock import MockAIProvider
from vc_harness import StreamingInputTTS, open_session, until

from roomkit_ui.engine_vc_helpers import (
    CLAUDE_EFFORTS,
    CLAUDE_THINKING,
    GEMINI_THINKING_LEVELS,
    reasoning_options,
)
from roomkit_ui.settings import _DEFAULTS
from roomkit_ui.widgets.settings import vc_cloud_fields
from roomkit_ui.widgets.settings.vc_cloud_fields import (
    CLAUDE_EFFORT_OPTIONS,
    CLAUDE_THINKING_OPTIONS,
    GEMINI_THINKING_OPTIONS,
    gemini_reasoning_note,
)
from roomkit_ui.widgets.settings.voice_setup import VC_LLM_PROVIDERS, VoiceSetup

# -- settings → AIChannel ------------------------------------------------------


@pytest.mark.parametrize("provider", ["anthropic", "gemini", "openai"])
def test_a_cloud_model_gets_room_for_its_reply_and_nothing_else(provider):
    """roomkit's 1024 tokens cut replies and tool calls: Claude 5.x and
    Gemini 3.x reason when the turn says nothing, and that counts."""
    assert reasoning_options(dict(_DEFAULTS), provider) == {"max_tokens": 16_000}


@pytest.mark.parametrize("provider", ["local", "llamacpp"])
def test_a_local_model_keeps_its_servers_budget(provider):
    assert reasoning_options(dict(_DEFAULTS), provider) == {}


def test_claude_takes_thinking_and_effort_apart():
    settings = {"vc_anthropic_thinking": "off", "vc_anthropic_effort": "low"}

    assert reasoning_options(settings, "anthropic") == {
        "enable_thinking": False,
        "reasoning_effort": "low",
        "max_tokens": 16_000,
    }


def test_claude_on_gets_room_to_think():
    assert reasoning_options({"vc_anthropic_thinking": "on"}, "anthropic") == {
        "enable_thinking": True,
        "max_tokens": 16_000,
    }


@pytest.mark.parametrize("thinking", ["", "on", "off"])
@pytest.mark.parametrize("effort", ["xhigh", "max"])
def test_a_deep_claude_effort_gets_room_to_think(effort, thinking):
    settings = {"vc_anthropic_effort": effort, "vc_anthropic_thinking": thinking}
    options = reasoning_options(settings, "anthropic")

    assert options["reasoning_effort"] == effort
    assert options["max_tokens"] == 64_000


def test_gemini_off_is_roomkits_none():
    assert reasoning_options({"vc_gemini_thinking": "none"}, "gemini") == {
        "reasoning_effort": "none",
        "max_tokens": 16_000,
    }


def test_each_provider_reads_only_its_own_settings():
    settings = {
        "vc_anthropic_thinking": "off",
        "vc_anthropic_effort": "max",
        "vc_gemini_thinking": "high",
    }

    assert reasoning_options(settings, "gemini") == {
        "reasoning_effort": "high",
        "max_tokens": 16_000,
    }
    assert reasoning_options(settings, "openai") == {"max_tokens": 16_000}


def test_a_value_roomkit_does_not_know_is_left_out():
    settings = {"vc_anthropic_thinking": "yes", "vc_anthropic_effort": "turbo"}

    assert reasoning_options(settings, "anthropic") == {"max_tokens": 16_000}
    assert reasoning_options({"vc_gemini_thinking": "max"}, "gemini") == {"max_tokens": 16_000}


@pytest.mark.parametrize(
    ("thinking", "effort"), [("off", "max"), ("on", "low")], ids=["off", "on"]
)
def test_the_aichannel_takes_them(thinking, effort):
    options = reasoning_options(
        {"vc_anthropic_thinking": thinking, "vc_anthropic_effort": effort}, "anthropic"
    )

    channel = AIChannel("ai", provider=MockAIProvider(), **options)

    assert channel._reasoning_effort == effort
    for name, value in options.items():
        assert getattr(channel, f"_{name}") == value


# -- the LLM tab -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("options", "accepted"),
    [
        (CLAUDE_THINKING_OPTIONS, CLAUDE_THINKING),
        (CLAUDE_EFFORT_OPTIONS, CLAUDE_EFFORTS),
        (GEMINI_THINKING_OPTIONS, GEMINI_THINKING_LEVELS),
    ],
)
def test_the_tab_offers_what_the_engine_sends(options, accepted):
    assert [value for _label, value in options] == ["", *accepted]


@pytest.fixture
def page_over(qapp):
    pages: list[VoiceSetup] = []

    def _build(**overrides) -> VoiceSetup:
        pages.append(VoiceSetup({**_DEFAULTS, **overrides}))
        return pages[-1]

    yield _build
    for page in pages:
        shiboken6.delete(page)


def _select_llm(page: VoiceSetup, provider: str) -> None:
    page.vc_provider.setCurrentIndex([v for _l, v in VC_LLM_PROVIDERS].index(provider))


def test_the_saved_choices_come_back(page_over):
    saved = {
        "vc_anthropic_thinking": "off",
        "vc_anthropic_effort": "xhigh",
        "vc_gemini_thinking": "minimal",
    }

    settings = page_over(**saved).get_settings()

    assert {key: settings[key] for key in saved} == saved


def test_the_block_shows_the_chosen_providers_rows_only(page_over):
    page = page_over(conversation_mode="voice_channel", vc_llm_provider="anthropic")
    cloud = page._cloud

    assert not cloud.vc_reasoning.isHidden()
    assert not cloud.vc_anthropic_effort.isHidden()
    assert cloud.vc_gemini_thinking.isHidden()

    _select_llm(page, "gemini")
    assert not cloud.vc_gemini_thinking.isHidden()
    assert cloud.vc_anthropic_thinking.isHidden()

    for provider in ("openai", "local", "llamacpp"):
        _select_llm(page, provider)
        assert cloud.vc_reasoning.isHidden(), provider


def test_a_claude_model_without_effort_keeps_the_pick_disabled(page_over, monkeypatch):
    def tags(_catalog, model_id):
        return {"effort_refused"} if model_id == "claude-haiku-4-5-20251001" else set()

    monkeypatch.setattr(vc_cloud_fields, "_catalog_tags", tags)
    page = page_over(vc_llm_provider="anthropic", vc_anthropic_effort="high")
    cloud = page._cloud
    assert cloud.vc_anthropic_effort.isEnabled()

    cloud.vc_anthropic_model.setCurrentIndex(
        cloud.vc_anthropic_model.findData("claude-haiku-4-5-20251001")
    )

    assert not cloud.vc_anthropic_effort.isEnabled()
    assert "takes no effort" in cloud._vc_reasoning_note.text()
    assert page.get_settings()["vc_anthropic_effort"] == "high"


def test_a_claude_model_that_always_thinks_says_what_off_does(page_over, monkeypatch):
    monkeypatch.setattr(vc_cloud_fields, "_catalog_tags", lambda *_: {"reasoning_floor_low"})

    page = page_over(vc_llm_provider="anthropic")

    assert "Off runs it at low effort" in page._cloud._vc_reasoning_note.text()


def test_the_gemini_note_follows_the_typed_model(page_over):
    page = page_over(vc_llm_provider="gemini", vc_gemini_model="gemini-3.8-flash")
    cloud = page._cloud

    cloud.vc_gemini_model.setCurrentText("gemini-3.1-pro-preview")

    assert cloud._vc_reasoning_note.text() == gemini_reasoning_note("gemini-3.1-pro-preview")
    assert "always thinks" in cloud._vc_reasoning_note.text()


@pytest.mark.parametrize(
    ("model_id", "caveat"),
    [
        ("gemini-2.5-flash", "only Off"),
        ("gemini-3.8-flash", "Minimal runs as Low"),
        ("gemini-3.6-flash", None),
        ("a-model-roomkit-does-not-list", None),
    ],
)
def test_gemini_caveats_come_from_roomkits_catalog(model_id, caveat):
    note = gemini_reasoning_note(model_id)

    if caveat is None:
        assert note == vc_cloud_fields._GEMINI_REASONING_HINT
    else:
        assert caveat in note


def test_every_caveat_of_a_claude_model_is_said(page_over, monkeypatch):
    # Sonnet 5.5 in roomkit 0.98's catalog.
    tags = {"thinking_off_between_tools", "thinking_off_effort_high"}
    monkeypatch.setattr(vc_cloud_fields, "_catalog_tags", lambda *_: tags)

    note = page_over(vc_llm_provider="anthropic")._cloud._vc_reasoning_note.text()

    assert "between tool calls" in note
    assert "Extra high and Max run as High" in note


async def test_the_model_is_asked_with_room_for_its_turn(qapp):
    vc = await open_session(
        tts=StreamingInputTTS(),
        reply=["Hi!"],
        ai_options=reasoning_options(dict(_DEFAULTS), "anthropic"),
    )
    try:
        await vc.speak()
        await until(lambda: vc.ai.contexts)

        assert vc.ai.contexts[0].max_tokens == 16_000
    finally:
        await vc.kit.close()
