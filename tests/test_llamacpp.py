"""llama.cpp: one server per configuration, outliving the sessions that use it."""

import asyncio
import json
import threading

import httpx
import pytest
from roomkit.providers.ai.base import AIContext, AIMessage

from roomkit_ui.engine_vc_helpers import start_local_llm
from roomkit_ui.providers import create_ai_provider, llm_settings
from roomkit_ui.providers import llamacpp as factory
from roomkit_ui.settings import _DEFAULTS


class _FakeServer:
    """Stands in for roomkit's LlamaServer: records where and how often it runs."""

    instances: list["_FakeServer"] = []

    def __init__(self, config):
        self.config = config
        self.running = False
        self.starts = 0
        self.stops = 0
        self.threads: set[str] = set()
        _FakeServer.instances.append(self)

    async def start(self):
        self.threads.add(threading.current_thread().name)
        if not self.running:
            self.starts += 1
            self.running = True

    async def stop(self):
        self.stops += 1
        self.running = False


@pytest.fixture(autouse=True)
def fake_server(monkeypatch):
    monkeypatch.setattr("roomkit.providers.llamacpp.server.LlamaServer", _FakeServer)
    _FakeServer.instances = []
    factory._servers.clear()
    yield
    for server in {id(s): s for _, s in factory._servers.values()}.values():
        server.shutdown()
    factory._servers.clear()


def _provider(**settings):
    return create_ai_provider("llamacpp", settings)


async def _settle():
    for _ in range(20):
        await asyncio.sleep(0.01)


def test_the_default_model_is_roomkits_documented_one():
    provider = _provider()

    assert provider.name == "llamacpp"
    assert provider.model_name == "unsloth/Qwen3-4B-Instruct-2507-GGUF:Q4_K_M"
    server = _FakeServer.instances[0]
    assert provider.base_url == f"http://127.0.0.1:{server.config.port}/v1"


async def test_sessions_share_one_server_started_off_the_app_loop():
    first = _provider(vc_llamacpp_model="me/model-GGUF:Q4_K_M")
    await first.start()
    await first.close()  # the session ends: its HTTP client goes, the server stays
    second = _provider(vc_llamacpp_model="me/model-GGUF:Q4_K_M")
    await second.start()

    assert len(_FakeServer.instances) == 1
    server = _FakeServer.instances[0]
    assert server.starts == 1
    assert server.stops == 0
    assert server.threads == {"llama-server"}
    assert second.base_url == first.base_url


async def test_a_new_configuration_stops_the_old_server():
    await _provider(vc_llamacpp_model="a/model-GGUF:Q4_K_M").start()
    await _provider(vc_llamacpp_model="b/model-GGUF:Q4_K_M").start()
    await _settle()

    old, new = _FakeServer.instances
    assert old.stops == 1
    assert new.running
    assert new.config.model == "b/model-GGUF:Q4_K_M"


def test_the_context_window_reaches_the_server_and_garbage_falls_back():
    _provider(vc_llamacpp_context="24576")
    assert _FakeServer.instances[-1].config.context_size == 24576

    _provider(vc_llamacpp_context="lots")
    assert _FakeServer.instances[-1].config.context_size == 8192


async def _request_body(monkeypatch, **settings) -> dict:
    """The JSON body a one-line turn sends to llama-server."""
    from roomkit.providers.openai.ai import OpenAIAIProvider

    sent: list[dict] = []

    def answer(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "c1",
                "object": "chat.completion",
                "created": 0,
                "model": "qwen3",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "Hi!"},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    real = OpenAIAIProvider._sdk_http_client
    monkeypatch.setattr(
        OpenAIAIProvider,
        "_sdk_http_client",
        staticmethod(lambda module, _transport: real(module, httpx.MockTransport(answer))),
    )
    provider = _provider(**settings)
    try:
        await provider.generate(AIContext(messages=[AIMessage(role="user", content="Say hi.")]))
    finally:
        await provider.close()
    return sent[0]


async def test_a_reasoning_model_answers_at_once_by_default(monkeypatch):
    body = await _request_body(monkeypatch)

    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert body["max_tokens"] == 1024


async def test_thinking_on_asks_for_it_and_leaves_it_the_window(monkeypatch):
    body = await _request_body(monkeypatch, vc_llamacpp_thinking=True, vc_llamacpp_context="16384")

    assert body["chat_template_kwargs"] == {"enable_thinking": True}
    # The reasoning counts against the cap: 1024 could all go to it.
    assert body["max_tokens"] == 16384


async def test_switching_thinking_keeps_the_running_server():
    await _provider().start()
    await _provider(vc_llamacpp_thinking=True).start()

    assert len(_FakeServer.instances) == 1


# -- the background tasks' model ------------------------------------------------------


def _tasks_provider(**settings):
    own = llm_settings({**settings, "vc_background_model": "llamacpp"}, "background")
    return factory.create(own, role="background")


async def test_the_tasks_share_the_conversations_server_when_they_run_the_same():
    await _provider(vc_llamacpp_model="me/model-GGUF:Q8_0").start()
    await _tasks_provider(vc_llamacpp_model="me/model-GGUF:Q8_0").start()

    assert len(_FakeServer.instances) == 1


async def test_the_tasks_get_their_own_server_and_the_conversation_keeps_its():
    conversation = _provider(vc_llamacpp_model="a/model-GGUF:Q4_K_M")
    await conversation.start()
    await _tasks_provider(vc_background_llamacpp_model="b/model-GGUF:Q8_0").start()
    await _settle()

    first, second = _FakeServer.instances
    assert first.running and second.running
    assert second.config.model == "b/model-GGUF:Q8_0"
    assert conversation.base_url == f"http://127.0.0.1:{first.config.port}/v1"


async def test_a_server_another_role_still_uses_is_not_stopped():
    await _provider(vc_llamacpp_model="a/model-GGUF:Q4_K_M").start()
    await _tasks_provider(vc_llamacpp_model="a/model-GGUF:Q4_K_M").start()
    # The conversation moves to another model: the tasks still run on the first.
    await _provider(vc_llamacpp_model="b/model-GGUF:Q4_K_M").start()
    await _settle()

    shared, new = _FakeServer.instances
    assert shared.stops == 0
    assert new.running


def test_the_tasks_take_think_llms_gguf_and_context_unless_set_and_think():
    tasks = {**_DEFAULTS, "vc_background_model": "llamacpp"}
    inherited = llm_settings(
        {**tasks, "vc_llamacpp_model": "/m/a.gguf", "vc_llamacpp_context": "16384"},
        "background",
    )
    own = llm_settings(
        {
            **tasks,
            "vc_llamacpp_model": "/m/a.gguf",
            "vc_background_llamacpp_model": "/m/b.gguf",
            "vc_background_llamacpp_context": "32768",
            "vc_background_llamacpp_thinking": False,
            "vc_llamacpp_thinking": True,
        },
        "background",
    )

    assert inherited["vc_llamacpp_model"] == "/m/a.gguf"
    assert inherited["vc_llamacpp_context"] == "16384"
    assert inherited["vc_llamacpp_thinking"] is True  # nobody waits on a task
    assert own["vc_llamacpp_model"] == "/m/b.gguf"
    assert own["vc_llamacpp_context"] == "32768"
    assert own["vc_llamacpp_thinking"] is False


async def test_a_session_starts_the_server_before_it_opens_the_mic():
    provider = _provider()
    statuses: list[str] = []

    await start_local_llm(provider, statuses.append)

    assert _FakeServer.instances[0].running
    assert statuses == ["Starting llama.cpp — the first run downloads the model…"]


async def test_other_providers_have_nothing_to_start():
    statuses: list[str] = []

    await start_local_llm(
        create_ai_provider("anthropic", {"anthropic_api_key": "k"}), statuses.append
    )

    assert statuses == []


def test_the_settings_page_offers_llamacpp_with_its_fields(qapp):
    import shiboken6

    from roomkit_ui.settings import _DEFAULTS
    from roomkit_ui.widgets.settings.voice_setup import VC_LLM_PROVIDERS, VoiceSetup

    page = VoiceSetup(
        {
            **_DEFAULTS,
            "vc_llm_provider": "llamacpp",
            "vc_llamacpp_model": "/models/qwen.gguf",
            "vc_llamacpp_context": "16384",
            "vc_llamacpp_thinking": True,
        }
    )
    try:
        local = page._local
        assert ("llama.cpp (local GGUF)", "llamacpp") in VC_LLM_PROVIDERS
        assert not local.vc_llamacpp_model.isHidden()
        assert not local.vc_llamacpp_thinking.isHidden()
        assert local.vc_local_base_url.isHidden()  # the vLLM / Ollama rows
        assert local.vc_local_thinking.isHidden()
        out = page.get_settings()
        assert out["vc_llm_provider"] == "llamacpp"
        assert out["vc_llamacpp_model"] == "/models/qwen.gguf"
        assert out["vc_llamacpp_context"] == "16384"
        assert out["vc_llamacpp_thinking"] is True
    finally:
        shiboken6.delete(page)
