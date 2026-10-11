"""ElevenLabs hears the reply as the model writes it, where the model can.

With ``stream_input`` the Voice Channel streams each sentence to the TTS over
a WebSocket (``deliver_stream``): first audio ~140 ms after the first
sentence, where the whole reply used to be awaited (2.6-3.9 s). v3 has no
socket and keeps whole-reply synthesis.
"""

import pytest
from roomkit import VoiceChannel
from roomkit.voice.backends.mock import MockVoiceBackend

from roomkit_ui.tts.elevenlabs import create


def _provider(**settings):
    provider, _rate = create({"elevenlabs_api_key": "key", **settings})
    return provider


@pytest.mark.parametrize(
    "model", ["eleven_v4_turbo", "eleven_v4", "eleven_flash_v2_5", "eleven_multilingual_v2"]
)
def test_a_model_with_a_socket_streams_by_default(model):
    provider = _provider(elevenlabs_model=model)

    assert provider.supports_streaming_input
    channel = VoiceChannel("voice", tts=provider, backend=MockVoiceBackend())
    assert channel.supports_streaming_delivery  # the channel streams the reply to it


def test_v4_the_default_model_streams():
    assert _provider(elevenlabs_model="").supports_streaming_input


def test_v3_waits_for_the_whole_reply():
    assert not _provider(elevenlabs_model="eleven_v3").supports_streaming_input


def test_the_toggle_turns_it_off():
    provider = _provider(elevenlabs_model="eleven_v4_turbo", elevenlabs_stream_input=False)

    assert not provider.supports_streaming_input
