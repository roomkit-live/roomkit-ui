"""Speaker enrolment records on the microphone the sessions listen on."""

from __future__ import annotations

import sys
import types

import pytest

from roomkit_ui import enrollment, settings


class FakeStream:
    opened_with: dict = {}

    def __init__(self, **kwargs) -> None:
        FakeStream.opened_with = kwargs
        self._callback = kwargs["callback"]
        self._block = kwargs["blocksize"]

    def __enter__(self):
        self._callback(b"\x00\x01" * self._block, self._block, None, None)
        return self

    def __exit__(self, *_exc) -> None:
        pass


class FakeExtractor:
    def __init__(self, config) -> None:
        pass

    def create_stream(self):
        return types.SimpleNamespace(
            accept_waveform=lambda **_kw: None, input_finished=lambda: None
        )

    def is_ready(self, _stream) -> bool:
        return True

    def compute(self, _stream):
        return [0.1, 0.2]


@pytest.fixture
def fakes(monkeypatch):
    monkeypatch.setitem(
        sys.modules, "sounddevice", types.SimpleNamespace(RawInputStream=FakeStream)
    )
    monkeypatch.setitem(
        sys.modules,
        "sherpa_onnx",
        types.SimpleNamespace(
            SpeakerEmbeddingExtractorConfig=lambda **kw: kw,
            SpeakerEmbeddingExtractor=lambda config: FakeExtractor(config),
        ),
    )
    FakeStream.opened_with = {}


async def test_enrolment_records_on_the_configured_input_device(fakes, monkeypatch):
    """Before: it always opened the system default microphone."""
    monkeypatch.setattr(settings, "load_settings", lambda: {"input_device": 3})

    embedding = await enrollment.record_and_extract("/model.onnx", duration=0.01)

    assert embedding == [0.1, 0.2]
    assert FakeStream.opened_with["device"] == 3


async def test_multi_take_enrolment_uses_it_too(fakes, monkeypatch):
    monkeypatch.setattr(settings, "load_settings", lambda: {"input_device": 5})

    with pytest.raises(ValueError):  # 10 ms is too short to segment
        await enrollment.record_and_extract_multi("/model.onnx", duration=0.01)

    assert FakeStream.opened_with["device"] == 5


async def test_no_configured_device_means_the_system_default(fakes, monkeypatch):
    monkeypatch.setattr(settings, "load_settings", lambda: {"input_device": None})

    await enrollment.record_and_extract("/model.onnx", duration=0.01)

    assert FakeStream.opened_with["device"] is None
