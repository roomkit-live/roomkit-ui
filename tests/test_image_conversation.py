"""Image input reaches RoomKit intact and survives a saved conversation."""

import json

import pytest
from PySide6.QtCore import QMimeData, Qt, QUrl
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from roomkit.providers.ai.base import AIImagePart, AITextPart
from test_engine_text import SETTINGS, TestProvider
from test_engine_text import setup_text as setup_text
from test_text_conversation import configure, until

from roomkit_ui.conversations import Conversation, ConversationStore
from roomkit_ui.engine_state import EngineState
from roomkit_ui.images import MAX_IMAGES, ImageAttachment, restore_images
from roomkit_ui.widgets.conversation_composer import ConversationComposer
from roomkit_ui.widgets.main_window import MainWindow


@pytest.fixture
def picture():
    image = QImage(120, 80, QImage.Format_RGB32)
    image.fill(QColor("#7161cd"))
    return image


class VisionProvider(TestProvider):
    @property
    def supports_vision(self):
        return True


def image_parts(context):
    return [
        part
        for message in context.messages
        if isinstance(message.content, list)
        for part in message.content
        if isinstance(part, AIImagePart)
    ]


def test_clipboard_image_then_text_and_file_drop_share_the_same_draft(qtbot, picture, tmp_path):
    composer = ConversationComposer()
    qtbot.addWidget(composer)
    composer.set_text_availability("")
    composer.resize(420, 200)
    composer.show()
    editor = composer._input
    editor.setFocus()
    QApplication.clipboard().setImage(picture)
    editor.paste()
    assert len(composer.images) == 1
    assert editor.toPlainText() == ""
    assert composer._live_button.accessibleName() == "Send message"
    QApplication.clipboard().setText("Compare these photos")
    editor.paste()
    assert editor.toPlainText() == "Compare these photos"
    path = tmp_path / "example.png"
    picture.save(str(path))
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path))])
    assert editor.canInsertFromMimeData(mime)
    editor.insertFromMimeData(mime)
    assert len(composer.images) == 2
    assert composer.images[1].name == "example.png"
    composer._attachments.remove(0)
    assert len(composer.images) == 1 and composer.images[0].name == "example.png"
    assert editor.toPlainText() == "Compare these photos"
    composer.clear_draft()
    assert not composer.images and editor.toPlainText() == ""


def test_limits_invalid_files_and_configuration_keep_existing_draft(qtbot, picture, tmp_path):
    composer = ConversationComposer()
    qtbot.addWidget(composer)
    composer.set_text_availability("")
    tray = composer._attachments
    for _ in range(MAX_IMAGES + 1):
        tray.add_image(picture)
    assert len(composer.images) == MAX_IMAGES
    assert "4 images" in tray._notice.text()
    tray.remove(0)
    invalid = tmp_path / "bad.png"
    invalid.write_text("not an image")
    tray.add_files([str(invalid)])
    assert len(composer.images) == MAX_IMAGES - 1
    assert tray._notice.text()
    composer.set_image_availability("Choose a vision model")
    sends = []
    composer.send_requested.connect(sends.append)
    composer._send()
    assert sends == [] and len(composer.images) == MAX_IMAGES - 1
    composer.set_image_availability("")
    composer._send()
    assert sends == [""]  # Image-only messages are valid, never start Live.


def test_normalized_image_has_no_metadata_and_needs_no_source_file(picture, tmp_path):
    picture.setText("location", "private metadata")
    path = tmp_path / "original.png"
    picture.save(str(path))
    image = ImageAttachment.from_file(str(path))
    path.unlink()
    restored = restore_images([image.snapshot()])[0]
    assert restored.image().size() == picture.size()
    assert not restored.image().textKeys()
    with pytest.raises(ValueError):
        restore_images([{"name": "remote", "data_url": "https://example.com/picture.png"}])


@pytest.mark.parametrize("persistent", [True, False])
async def test_images_reach_the_provider_and_resume_with_history(
    qtbot, monkeypatch, setup_text, picture, persistent
):
    settings = {**SETTINGS, "conversation_memory": persistent}
    configure(monkeypatch, settings)
    window = MainWindow()
    qtbot.addWidget(window)
    monkeypatch.setattr(window._history, "suggest_title", lambda **_: None)
    provider = VisionProvider()
    setup_text(provider, window._engine)
    window._controls._attachments.add_image(picture)
    window._controls._input.setPlainText("What do you see?")
    QTest.keyClick(window._controls._input, Qt.Key_Return)
    await window._request_task
    await until(lambda: not window._start_pending)
    parts = provider.contexts[0].messages[-1].content
    assert any(isinstance(part, AITextPart) and "What do you see?" in part.text for part in parts)
    assert len(image_parts(provider.contexts[0])) == 1
    snapshot = window._chat.snapshot()
    assert snapshot[0]["images"][0]["data_url"] == image_parts(provider.contexts[0])[0].url
    assert not window._controls.images
    conversation_id = window._history.current.id
    assert window._history.store.path.exists() == persistent
    window._on_send("And the color?")
    await window._request_task
    await until(lambda: not window._start_pending)
    assert len(image_parts(provider.contexts[-1])) == 1
    window._history.new()
    await until(lambda: not window._start_pending)
    window._history.select(conversation_id)
    assert window._chat.snapshot()[0]["images"] == snapshot[0]["images"]
    provider2 = VisionProvider()
    setup_text(provider2, window._engine)
    window._on_send("Remember the photo?")
    await window._request_task
    await until(lambda: not window._start_pending)
    assert len(image_parts(provider2.contexts[0])) == 1
    assert window._engine.state == EngineState.READY


async def test_image_only_message_and_unsupported_provider(setup_text, picture):
    image = ImageAttachment.from_image(picture)
    provider = VisionProvider()
    engine = setup_text(provider)
    await engine.start(SETTINGS, text="", images=(image,))
    assert len(image_parts(provider.contexts[0])) == 1
    await engine.stop()
    plain = TestProvider()
    engine = setup_text(plain)
    errors = []
    engine.error_occurred.connect(errors.append)
    await engine.start(SETTINGS, text="Describe", images=(image,))
    assert engine.state == EngineState.ERROR
    assert plain.contexts == [] and plain.closed
    assert "does not accept images" in errors[0]


def test_history_roundtrip_contains_bytes_only_when_persistent(picture):
    image = ImageAttachment.from_image(picture)
    store = ConversationStore()
    conversation = Conversation(
        entries=[
            {
                "kind": "message",
                "role": "user",
                "text": "",
                "images": [image.snapshot()],
            }
        ]
    )
    conversation.update(conversation.entries)
    store.save(conversation)
    assert conversation.title == "Photo"
    saved = ConversationStore().get(conversation.id)
    assert saved.entries[0]["images"] == [image.snapshot()]
    assert json.dumps(saved.entries)
