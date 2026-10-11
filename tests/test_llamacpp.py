"""llama.cpp: one server per configuration, outliving the sessions that use it."""

import asyncio
import threading

import pytest

from roomkit_ui.engine_vc_helpers import start_local_llm
from roomkit_ui.providers import create_ai_provider
from roomkit_ui.providers import llamacpp as factory


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
    factory._shared = None
    yield
    if factory._shared is not None:
        factory._shared[1].shutdown()
    factory._shared = None


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
        }
    )
    try:
        local = page._local
        assert ("llama.cpp (local GGUF)", "llamacpp") in VC_LLM_PROVIDERS
        assert not local.vc_llamacpp_model.isHidden()
        assert local.vc_local_base_url.isHidden()  # the vLLM / Ollama rows
        out = page.get_settings()
        assert out["vc_llm_provider"] == "llamacpp"
        assert out["vc_llamacpp_model"] == "/models/qwen.gguf"
        assert out["vc_llamacpp_context"] == "16384"
    finally:
        shiboken6.delete(page)
