"""An image shared while Live, from a file or the camera, as in a typed
conversation: a turn of the user's the assistant answers aloud."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from PySide6.QtGui import QColor, QImage

from roomkit_ui.engine_state import EngineState
from roomkit_ui.images import ImageAttachment
from roomkit_ui.widgets.conversation_composer import ConversationComposer


@pytest.fixture
def picture(qapp) -> ImageAttachment:
    image = QImage(64, 48, QImage.Format_RGB32)
    image.fill(QColor("#336699"))
    return ImageAttachment.from_image(image, "photo.jpg")


def test_live_shows_a_share_button_beside_the_mic(qtbot, picture):
    composer = ConversationComposer()
    qtbot.addWidget(composer)
    composer.show()
    shared: list[tuple] = []
    composer.images_shared.connect(shared.append)

    composer.set_state(EngineState.ACTIVE)
    button = composer._attachment_button
    assert button.isVisible() and button.isEnabled()
    assert button.accessibleName() == "Share an image"

    composer._attachments._add(lambda: picture)  # chosen from a file or the camera

    assert shared == [(picture,)]
    assert composer.images == ()  # no draft: it went to the session


def test_a_session_that_cannot_see_says_why(qtbot, picture):
    composer = ConversationComposer()
    qtbot.addWidget(composer)
    composer.show()
    shared: list[tuple] = []
    composer.images_shared.connect(shared.append)

    composer.set_state(EngineState.ACTIVE)
    composer.set_live_image_availability("This voice cannot see images.")

    assert not composer._attachment_button.isEnabled()
    assert composer._attachment_button.toolTip() == "This voice cannot see images."
    composer._attachments._add(lambda: picture)
    assert shared == []


async def test_a_voice_channel_session_gets_the_image_as_the_users_turn(qapp, picture):
    from roomkit.models.event import CompositeContent, MediaContent

    from roomkit_ui.engine import Engine

    engine = Engine()
    kit = SimpleNamespace(process_inbound=AsyncMock())
    engine._kit, engine._channel, engine._session = kit, SimpleNamespace(), object()
    engine._room_id = "thread"

    await engine._share_images((picture,))

    ((message,), options) = kit.process_inbound.call_args
    assert options == {"room_id": "thread"}
    assert (message.channel_id, message.sender_id) == ("voice", "local-user")
    assert isinstance(message.content, CompositeContent)
    (media,) = message.content.parts
    assert isinstance(media, MediaContent) and media.url == picture.data_url


async def test_a_realtime_voice_answers_once_every_image_is_in(qapp, picture):
    from roomkit_ui.engine import Engine

    engine = Engine()
    session = object()
    channel = SimpleNamespace(inject_image=AsyncMock())
    engine._kit, engine._channel, engine._session = object(), channel, session

    await engine._share_images((picture, picture))

    calls = channel.inject_image.call_args_list
    assert [call.kwargs["silent"] for call in calls] == [True, False]
    assert calls[0].args == (session, picture.bytes(), "image/jpeg")


def test_only_a_voice_that_injects_images_can_see_one():
    from roomkit.providers.gemini.realtime import GeminiLiveProvider
    from roomkit.voice.realtime.mock import MockRealtimeProvider

    from roomkit_ui.engine_realtime import _injects_images

    assert _injects_images(object.__new__(GeminiLiveProvider))
    assert not _injects_images(object.__new__(MockRealtimeProvider))
