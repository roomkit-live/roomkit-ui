"""The assistant draws (Settings → Conversation → Images): one tool,
generate_image, on the provider the Images tab picks; the drawing is shown in
the chat, and the model is told it is there."""

from __future__ import annotations

import json
from datetime import date

import pytest
from roomkit import (
    ImageGenerationError,
    MockImageProvider,
    ToolFailedError,
    ToolRefusedError,
)
from roomkit.providers.ai.base import ProviderError

from roomkit_ui import image_generation
from roomkit_ui.image_generation import (
    GENERATE_IMAGE_TOOL,
    IMAGE_PROVIDERS,
    ImageStudio,
    create_image_studio,
    image_model,
    image_models,
)
from roomkit_ui.images import ImageAttachment


@pytest.fixture
def studio(qapp) -> ImageStudio:
    return ImageStudio(MockImageProvider(), "openai")


# -- the providers and their models --------------------------------------------------


def test_each_provider_lists_its_models_from_roomkits_catalog():
    for _label, provider in IMAGE_PROVIDERS[1:]:
        ids = [model_id for _name, model_id in image_models(provider)]
        assert image_model({}, provider) in ids, provider
    assert image_model({"image_gemini_model": "gemini-3-pro-image"}, "gemini") == (
        "gemini-3-pro-image"
    )


def test_a_provider_without_its_key_cannot_draw(monkeypatch):
    monkeypatch.setattr(image_generation, "require", lambda _feature: None)

    with pytest.raises(ValueError, match="xAI has no API key"):
        create_image_studio({"image_provider": "xai", "xai_api_key": " "})


def test_a_provider_is_built_with_its_key_and_model(monkeypatch):
    monkeypatch.setattr(image_generation, "require", lambda _feature: None)

    built = create_image_studio(
        {
            "image_provider": "openai",
            "openai_api_key": "test-only",
            "image_openai_model": "gpt-image-1.5",
        }
    )

    assert (built.provider_name, built.model) == ("openai", "gpt-image-1.5")
    assert built.pricing() is not None  # OpenAI's catalog prices its tokens


def test_the_tool_declares_what_a_provider_takes():
    params = GENERATE_IMAGE_TOOL["parameters"]
    assert params["required"] == ["prompt"]
    assert set(params["properties"]) == {"prompt", "size", "edit", "image_id"}
    # Gemini refuses it, and nothing strips it from a built-in's schema.
    assert "additionalProperties" not in json.dumps(GENERATE_IMAGE_TOOL)


# -- drawing ------------------------------------------------------------------------


async def test_a_drawing_becomes_an_image_the_chat_keeps(studio):
    drawing = await studio.draw("A red fox in the snow", size="1024x1024")

    (image,) = drawing.images
    assert isinstance(image, ImageAttachment)
    assert image.data_url.startswith(("data:image/png;base64,", "data:image/jpeg;base64,"))
    assert studio.last is image
    assert studio.provider.calls == [("A red fox in the snow", "1024x1024", 1, [])]


async def test_an_edit_changes_the_last_image(studio):
    first = (await studio.draw("A red fox")).images[0]

    await studio.draw("Make it night", edit=True)

    _prompt, _size, _n, references = studio.provider.calls[-1]
    assert [part.url for part in references] == [first.data_url]


async def test_an_edit_with_no_image_is_refused_before_anything_is_billed(studio):
    with pytest.raises(ToolRefusedError, match="no image in this conversation"):
        await studio.draw("Make it night", edit=True)
    assert studio.provider.calls == []


@pytest.mark.parametrize(
    ("failure", "raised"),
    [
        (ValueError("size 3000x10 is not one this model makes"), ToolRefusedError),
        (ProviderError("quota exceeded", retryable=False), ToolFailedError),
    ],
)
async def test_a_failure_tells_the_model_what_happened(studio, monkeypatch, failure, raised):
    async def fail(*_args, **_kwargs):
        raise failure

    monkeypatch.setattr(studio.provider, "generate", fail)

    with pytest.raises(raised):
        await studio.draw("A red fox")


async def test_an_image_billed_before_a_failure_is_still_shown(studio, monkeypatch):
    from roomkit import ImageAttempt

    billed = await MockImageProvider().generate("x")
    attempts = [
        ImageAttempt(id="a1", index=0, status="succeeded", results=billed),
        ImageAttempt(id="a2", index=1, status="failed", error="quota exceeded"),
    ]

    async def fail(*_args, **_kwargs):
        raise ImageGenerationError("the second call failed", provider="mock", attempts=attempts)

    monkeypatch.setattr(studio.provider, "generate", fail)

    drawing = await studio.draw("Two foxes")

    assert len(drawing.images) == 1


async def test_an_edit_can_name_the_drawing_it_changes(studio):
    first = (await studio.draw("A red fox")).images[0]
    await studio.draw("A blue owl")

    await studio.draw("Make it night", edit=True, image_id="img_1")

    _prompt, _size, _n, references = studio.provider.calls[-1]
    assert [part.url for part in references] == [first.data_url]
    with pytest.raises(ToolRefusedError, match="No image img_9"):
        await studio.draw("Make it night", edit=True, image_id="img_9")


def test_the_palette_names_the_dominant_colours(qapp):
    from PySide6.QtGui import QColor, QImage, QPainter

    picture = QImage(200, 100, QImage.Format_RGB32)
    painter = QPainter(picture)
    painter.fillRect(0, 0, 140, 100, QColor("#d22a1e"))  # 70 % red
    painter.fillRect(140, 0, 60, 100, QColor("#1e3cc8"))  # 30 % blue
    painter.end()

    colours = image_generation.palette(picture)

    assert [c["color"] for c in colours[:2]] == ["#d22a1e", "#1e3cc8"]
    assert abs(colours[0]["share"] - 0.7) < 0.05


def test_the_model_looks_at_a_smaller_copy(qapp):
    from PySide6.QtGui import QColor, QImage

    picture = QImage(1536, 1024, QImage.Format_RGB32)
    picture.fill(QColor("#336699"))
    image = ImageAttachment.from_image(picture, "Generated image")

    (_text, seen) = image_generation.drawing_result(
        image_generation.Drawing((image,), ("img_1",), None, {})
    )

    copy = ImageAttachment("copy", seen.url).image()
    assert (copy.width(), copy.height()) == (768, 512)
    assert image.image().width() == 1536  # the chat keeps the full image


# -- the session --------------------------------------------------------------------


async def test_the_tool_is_declared_only_when_the_assistant_can_draw(qapp, monkeypatch):
    from roomkit_ui.engine import Engine

    engine = Engine()
    notices: list[str] = []
    engine.session_notice.connect(notices.append)

    off = await engine._setup_tools({"image_provider": ""})
    assert "generate_image" not in {tool["name"] for tool in off.builtin}

    def unavailable(_settings):
        raise ValueError("Meta has no API key (Settings → Providers & keys).")

    monkeypatch.setattr("roomkit_ui.engine.create_image_studio", unavailable)
    missing = await engine._setup_tools({"image_provider": "meta"})
    assert "generate_image" not in {tool["name"] for tool in missing.builtin}
    assert notices == [
        "The assistant cannot draw images: Meta has no API key (Settings → Providers & keys)."
    ]

    monkeypatch.setattr(
        "roomkit_ui.engine.create_image_studio",
        lambda _settings: ImageStudio(MockImageProvider(), "openai"),
    )
    on = await engine._setup_tools({"image_provider": "openai"})
    assert "generate_image" in {tool["name"] for tool in on.builtin}
    await engine._close_image_studio()
    assert engine._images is None


async def test_a_drawing_is_shown_in_the_chat_and_the_model_told(qapp):
    from roomkit_ui.engine import Engine

    engine = Engine()
    engine._images = ImageStudio(MockImageProvider(), "openai")
    shown: list[tuple] = []
    engine.image_generated.connect(shown.append)

    finished: list = []
    engine.tool_finished.connect(finished.append)

    reply = await engine._handle_tool_call("generate_image", {"prompt": "A red fox"})

    ((image,),) = shown
    assert isinstance(image, ImageAttachment)
    text, seen = reply  # what it drew, then a copy to look at
    told = json.loads(text.text)
    assert told["shown"] == 1 and told["images"][0]["id"] == "img_1"
    assert seen.url.startswith("data:image/")
    # The chat's tool row shows the text, never the image's bytes.
    assert json.loads(finished[0].text) == told
    assert engine._pending_tool_calls == 0


async def test_a_priced_drawing_counts_in_the_session_cost(qapp):
    from roomkit.providers.ai.base import ModelPricing

    from roomkit_ui.engine import Engine

    engine = Engine()
    costs: list[dict] = []
    engine.session_cost.connect(costs.append)
    pricing = ModelPricing(
        input_per_million=5.0,
        output_per_million=0.0,
        image_output_per_million=40.0,
        verified=date(2026, 10, 12),
    )

    engine._add_image_cost({"output_image_tokens": 1_000_000}, pricing)
    engine._add_image_cost({"cost": 0.25}, None)  # what the vendor reports it billed
    engine._add_image_cost({"output_image_tokens": 5}, None)  # per image, no price

    assert [round(c["cost_usd"], 2) for c in costs] == [40.0, 40.25]


# -- settings and chat --------------------------------------------------------------


def test_the_images_tab_saves_the_provider_and_its_model(qapp):
    from roomkit_ui.widgets.settings.images_setup import ImagesSetup

    page = ImagesSetup({"image_xai_model": "grok-imagine-image"})

    assert page.get_settings() == {"image_provider": "", "image_xai_model": "grok-imagine-image"}
    page.provider.setCurrentIndex([value for _l, value in IMAGE_PROVIDERS].index("gemini"))
    label, combo = page.models["gemini"]
    assert not combo.isHidden() and page.models["openai"][1].isHidden()
    assert combo.currentData() == "gemini-nano-banana-2.1"
    combo.setCurrentIndex(combo.findData("gemini-3-pro-image"))

    assert page.get_settings() == {
        "image_provider": "gemini",
        "image_gemini_model": "gemini-3-pro-image",
        "image_xai_model": "grok-imagine-image",
    }


async def test_a_drawing_has_its_entry_in_the_chat_and_history(qapp, studio):
    from roomkit_ui.widgets.chat_view import ChatView

    drawing = await studio.draw("A red fox")
    view = ChatView()
    try:
        view.add_assistant_images(drawing.images)
        (entry,) = view.snapshot()
        assert entry["role"] == "assistant"
        assert entry["images"][0]["data_url"] == drawing.images[0].data_url
    finally:
        view.deleteLater()


# -- saving an image ----------------------------------------------------------------


async def test_an_image_saves_as_the_chat_keeps_it(qapp, studio, tmp_path, monkeypatch):
    from roomkit_ui.widgets import image_attachments

    image = (await studio.draw("A red fox")).images[0]
    asked: list[str] = []

    def pick(_parent, _title, suggested, _filter):
        asked.append(suggested)
        return str(tmp_path / "fox"), ""  # typed without an extension

    monkeypatch.setattr(image_attachments.QFileDialog, "getSaveFileName", pick)

    image_attachments.save_image(image, None)

    suffix = ".png" if image.mime_type == "image/png" else ".jpg"
    assert asked[0].endswith(f"Generated image{suffix}")
    assert (tmp_path / f"fox{suffix}").read_bytes() == image.bytes()  # not encoded again


async def test_a_save_that_fails_says_so(qapp, studio, tmp_path, monkeypatch):
    from roomkit_ui.widgets import image_attachments

    image = (await studio.draw("A red fox")).images[0]
    warned: list[str] = []
    monkeypatch.setattr(
        image_attachments.QFileDialog,
        "getSaveFileName",
        lambda *_a: (str(tmp_path / "missing" / "fox.png"), ""),
    )
    monkeypatch.setattr(
        image_attachments.QMessageBox, "warning", lambda _p, _t, text: warned.append(text)
    )

    image_attachments.save_image(image, None)

    assert warned and warned[0].startswith("The image could not be saved")


async def test_the_viewer_offers_to_save(qapp, studio, monkeypatch):
    from PySide6.QtWidgets import QDialog, QPushButton, QWidget

    from roomkit_ui.widgets import image_attachments

    image = (await studio.draw("A red fox")).images[0]
    parent = QWidget()
    saved: list[object] = []
    monkeypatch.setattr(image_attachments, "save_image", lambda img, _p: saved.append(img))
    try:
        image_attachments.show_image(image, parent)
        (dialog,) = parent.findChildren(QDialog)
        buttons = {button.text(): button for button in dialog.findChildren(QPushButton)}
        buttons["Save…"].click()
        assert saved == [image]
        dialog.reject()
    finally:
        parent.deleteLater()
