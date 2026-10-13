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


def test_typed_messages_on_a_model_of_their_own_need_its_key():
    settings = {
        "vc_llm_provider": "anthropic",
        "anthropic_api_key": "test-only",
        "text_llm_provider": "openai",
        "text_openai_model": "gpt-5.5",
    }

    assert text_chat_unavailable(settings) == "Add your OpenAI key in Settings…"
    settings["openai_api_key"] = "test-only"
    assert text_chat_unavailable(settings) == ""


def test_the_text_chat_tab_sets_the_model_of_typed_messages(qapp):
    from roomkit_ui.widgets.settings.text_chat_setup import TextChatSetup

    page = TextChatSetup({"vc_local_model": "qwen3:8b", "text_anthropic_model": "x"})
    llm = page.llm

    assert llm.current() == ""  # Think · LLM's until another is chosen
    assert page.get_settings() == {"text_llm_provider": "", "text_anthropic_model": "x"}
    llm.provider.setCurrentIndex([value for _, value in llm.entries].index("local"))
    model, tools = llm.fields["local_model"], llm.fields["local_tools"]
    assert not model.isHidden() and not tools.isHidden()
    assert "qwen3:8b" in model.placeholderText()
    model.setText(" gemma4:12b ")
    tools.setChecked(False)

    assert page.get_settings() == {
        "text_llm_provider": "local",
        "text_anthropic_model": "x",
        "text_local_base_url": "",
        "text_local_model": "gemma4:12b",
        "text_local_tools": False,
        "text_local_thinking": False,
    }
