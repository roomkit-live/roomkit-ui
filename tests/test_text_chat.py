"""Readiness is local and specific to the selected conversation model."""

import pytest

from roomkit_ui.text_chat import text_chat_unavailable


@pytest.fixture(autouse=True)
def installed(monkeypatch):
    monkeypatch.setattr("roomkit_ui.text_chat.is_available", lambda _feature: True)


@pytest.mark.parametrize(
    "provider,key",
    [
        ("anthropic", "anthropic_api_key"),
        ("openai", "openai_api_key"),
        ("gemini", "api_key"),
    ],
)
def test_selected_ai_key_is_required_even_if_live_is_configured(provider, key):
    settings = {"vc_llm_provider": provider, "conversation_mode": "realtime"}
    assert "key" in text_chat_unavailable(settings)
    settings[key] = "   "
    assert text_chat_unavailable(settings)
    settings[key] = "test-only"
    assert text_chat_unavailable(settings) == ""


def test_an_unrelated_key_cannot_enable_the_input():
    assert text_chat_unavailable({"vc_llm_provider": "anthropic", "api_key": "test-only"})
    assert text_chat_unavailable(
        {
            "vc_llm_provider": "openai",
            "openai_api_key": "test-only",
            "vc_openai_model": "",
        }
    )


@pytest.mark.parametrize("url", ["", "localhost", "ftp://host", "http://[bad", "http://host:bad"])
def test_local_server_requires_model_and_valid_endpoint(url):
    assert text_chat_unavailable({"vc_llm_provider": "local"})
    assert text_chat_unavailable(
        {
            "vc_llm_provider": "local",
            "vc_local_model": "a-model",
            "vc_local_base_url": url,
        }
    )
    assert not text_chat_unavailable({"vc_llm_provider": "local", "vc_local_model": "a-model"})


def test_llamacpp_default_and_local_model_path(tmp_path):
    assert not text_chat_unavailable({"vc_llm_provider": "llamacpp"})
    model = tmp_path / "model.gguf"
    settings = {"vc_llm_provider": "llamacpp", "vc_llamacpp_model": str(model)}
    assert text_chat_unavailable(settings)
    model.touch()
    assert not text_chat_unavailable(settings)


def test_missing_backend_does_not_claim_to_be_ready(monkeypatch):
    monkeypatch.setattr("roomkit_ui.text_chat.is_available", lambda _feature: False)
    assert "Install" in text_chat_unavailable({"anthropic_api_key": "test-only"})
    assert text_chat_unavailable({"vc_llm_provider": "unknown"})
