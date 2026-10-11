"""A local reasoning model answers at once unless thinking is asked for.

Qwen3 and DeepSeek-R1 reason before they answer: on a laptop, seconds of
silence before a voice reply. "Model thinking" (off by default) turns it off
the way each server reads it — vLLM through the chat template's
``enable_thinking``, Ollama's /v1 through ``reasoning_effort: "none"``, since
it ignores the template kwargs. These read the request that reaches the wire.
"""

import json

import httpx
import pytest
import roomkit.providers.vllm as vllm
import shiboken6
from roomkit.providers.ai.base import AIContext, AIMessage

from roomkit_ui.providers import local
from roomkit_ui.settings import _DEFAULTS
from roomkit_ui.widgets.settings.voice_setup import VoiceSetup

_OLLAMA = "http://localhost:11434/v1"
_VLLM = "http://gpu-box:8000/v1"


async def _request_body(monkeypatch, **settings) -> dict:
    """The JSON body a one-line turn sends to the local server."""
    sent: list[dict] = []

    def answer(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "c1",
                "object": "chat.completion",
                "created": 0,
                "model": "qwen3:8b",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "Hi!"},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    real = vllm.create_vllm_provider
    monkeypatch.setattr(
        vllm,
        "create_vllm_provider",
        lambda config: real(config, transport=httpx.MockTransport(answer)),
    )
    provider = local.create({"vc_local_model": "qwen3:8b", **settings})
    await provider.generate(AIContext(messages=[AIMessage(role="user", content="Say hi.")]))
    return sent[0]


async def test_ollama_is_told_not_to_think_by_default(monkeypatch):
    body = await _request_body(monkeypatch, vc_local_base_url=_OLLAMA)

    assert body["reasoning_effort"] == "none"


async def test_vllm_is_told_through_its_chat_template(monkeypatch):
    body = await _request_body(monkeypatch, vc_local_base_url=_VLLM)

    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert "reasoning_effort" not in body  # vLLM's schema may refuse "none"


@pytest.mark.parametrize("base_url", [_OLLAMA, _VLLM])
async def test_thinking_on_sends_nothing_and_leaves_the_model_its_default(monkeypatch, base_url):
    body = await _request_body(monkeypatch, vc_local_base_url=base_url, vc_local_thinking=True)

    assert "reasoning_effort" not in body
    assert "chat_template_kwargs" not in body


@pytest.mark.parametrize(
    ("base_url", "ollama"),
    [
        (_OLLAMA, True),
        ("http://127.0.0.1:11434/v1", True),
        (_VLLM, False),
        ("http://localhost:11434x/v1", False),  # not a port at all
    ],
)
def test_ollama_is_recognised_by_its_port(base_url, ollama):
    fields = local.thinking_fields(base_url, thinking=False)

    assert ("extra_body" in fields) is ollama


@pytest.mark.parametrize("thinking", [True, False])
def test_the_settings_page_keeps_the_choice(qapp, thinking):
    page = VoiceSetup({**_DEFAULTS, "vc_local_thinking": thinking})
    try:
        assert page.get_settings()["vc_local_thinking"] is thinking
    finally:
        shiboken6.delete(page)
