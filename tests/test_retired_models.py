"""A retired default moves on with the default; a deliberate pick stays, and is flagged."""

from PySide6.QtCore import QSettings

from roomkit_ui.engine_vc_helpers import announce_llm_model
from roomkit_ui.providers import create_ai_provider
from roomkit_ui.settings import _DEFAULTS, load_settings, save_settings, take_model_notices


def _stored(key: str):
    return QSettings().value(f"room/{key}")


def test_the_default_claude_model_is_sonnet_5_5():
    assert _DEFAULTS["vc_anthropic_model"] == "claude-sonnet-5-5"
    provider = create_ai_provider("anthropic", {"anthropic_api_key": "k"})
    assert provider.model_name == "claude-sonnet-5-5"


def test_the_retired_default_moves_to_its_successor_and_says_so_once():
    save_settings({"vc_anthropic_model": "claude-sonnet-4-5-20250929"})

    assert load_settings()["vc_anthropic_model"] == "claude-sonnet-5-5"
    assert _stored("vc_anthropic_model") == "claude-sonnet-5-5"  # persisted, not per load
    notices = take_model_notices()
    assert len(notices) == 1
    assert "Claude Sonnet 4.5 retires on 2026-11-30" in notices[0]
    assert take_model_notices() == []


def test_a_deliberate_deprecated_pick_is_kept():
    # Claude Sonnet 4 was never the saved default: only the dropdown set it.
    save_settings({"vc_anthropic_model": "claude-sonnet-4-20250514"})

    assert load_settings()["vc_anthropic_model"] == "claude-sonnet-4-20250514"
    assert take_model_notices() == []


def test_a_current_model_is_left_alone():
    save_settings({"vc_anthropic_model": "claude-haiku-4-5-20251001"})

    assert load_settings()["vc_anthropic_model"] == "claude-haiku-4-5-20251001"
    assert take_model_notices() == []


def _announced(model: str) -> list[str]:
    provider = create_ai_provider(
        "anthropic", {"anthropic_api_key": "k", "vc_anthropic_model": model}
    )
    notices: list[str] = []
    announce_llm_model(provider, notices.append)
    return notices


def test_a_session_on_a_deprecated_model_says_it_will_stop_answering():
    notices = _announced("claude-sonnet-4-20250514")

    assert notices == [
        "Claude Sonnet 4 is deprecated by its vendor and will stop answering. "
        "Pick another model in Settings → AI Provider → LLM."
    ]


def test_a_session_on_a_current_model_says_nothing():
    assert _announced("claude-sonnet-5-5") == []


def test_the_migration_notice_reaches_the_next_session_once():
    save_settings({"vc_anthropic_model": "claude-sonnet-4-5-20250929"})
    model = load_settings()["vc_anthropic_model"]

    first = _announced(model)
    assert len(first) == 1 and "Claude Sonnet 5.5" in first[0]
    assert _announced(model) == []


class _NoCatalog:
    def catalog_entry(self):
        raise RuntimeError("no catalog")


def test_a_provider_without_a_catalog_is_not_announced():
    notices: list[str] = []
    announce_llm_model(_NoCatalog(), notices.append)
    assert notices == []


def test_the_shut_down_gemini_default_moves_to_a_catalog_model():
    from roomkit.providers.gemini.models import MODELS

    save_settings({"vc_gemini_model": "gemini-2.0-flash"})

    model = load_settings()["vc_gemini_model"]
    assert model == _DEFAULTS["vc_gemini_model"] == "gemini-3.8-flash"
    assert model in {m.id for m in MODELS if not m.deprecated}
    assert any("Gemini 2.0 Flash is no longer offered" in n for n in take_model_notices())
