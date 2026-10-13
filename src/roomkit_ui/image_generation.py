"""Images the assistant draws (Settings → Conversation → Images).

roomkit gives image generation a provider surface of its own (RFC §25): any
conversation model, spoken or typed, draws through it with one tool,
``generate_image``. A drawing goes to the chat as an entry of the
assistant's, and the model gets a line of text: it need not see the image to
say it is there, and a spoken turn should not wait on reading it back.

roomkit never retries a paid generation: one that fails is reported, and a
request the provider cannot express is refused before anything is billed.
"""

from __future__ import annotations

import importlib
import json
import logging
from dataclasses import dataclass
from typing import Any

from roomkit_ui.features import IMAGE_PROVIDER_FEATURES, require
from roomkit_ui.images import ImageAttachment

logger = logging.getLogger(__name__)

# (label, image_provider) — the Images tab's choices.
IMAGE_PROVIDERS: list[tuple[str, str]] = [
    ("Off", ""),
    ("OpenAI", "openai"),
    ("Google Gemini", "gemini"),
    ("xAI Grok", "xai"),
    ("Meta Muse", "meta"),
]


@dataclass(frozen=True)
class _Vendor:
    label: str
    key: str  # the settings key of its API key
    model: str  # its model until the user picks one
    catalog: str  # the module of its offline MODELS: data, no vendor SDK


_VENDORS = {
    "openai": _Vendor(
        "OpenAI", "openai_api_key", "gpt-image-2", "roomkit.providers.openai.image_models"
    ),
    "gemini": _Vendor(
        "Google Gemini",
        "api_key",
        "gemini-nano-banana-2.1",
        "roomkit.providers.gemini.image_models",
    ),
    "xai": _Vendor(
        "xAI", "xai_api_key", "grok-imagine-image-2.0", "roomkit.providers.xai.image_models"
    ),
    "meta": _Vendor(
        "Meta", "meta_api_key", "muse-image-1.0", "roomkit.providers.meta.image_models"
    ),
}

GENERATE_IMAGE_TOOL: dict = {
    "type": "function",
    "name": "generate_image",
    "description": (
        "Draw an image and show it to the user in the chat: when they ask for a "
        "picture, a drawing, an illustration or a photo of something. Set edit to "
        "change an image of this conversation (the latest, one they shared or one "
        "you drew, or the drawing image_id names) rather than draw a new one. You "
        "get back its id, size and dominant colours, and see the image. It shows in "
        "the chat on its own: say in a few words what you drew, never describe it "
        "at length."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": (
                    "What to draw, in detail: subject, setting, style, mood. "
                    "For an edit, the change to make."
                ),
            },
            "size": {
                "type": "string",
                "description": (
                    "WIDTHxHEIGHT: 1024x1024 square, 1536x1024 landscape, "
                    "1024x1536 portrait. Leave it out for the default."
                ),
            },
            "edit": {
                "type": "boolean",
                "description": (
                    "True to change an image of this conversation instead of drawing a new one."
                ),
            },
            "image_id": {
                "type": "string",
                "description": (
                    "With edit, the drawing to change, by the id it came back "
                    "with (img_1…). Leave it out for the latest image."
                ),
            },
        },
        "required": ["prompt"],
    },
}


# The settings a model's drawings take, by field (image_<provider>_<field>).
IMAGE_CONTROL_FIELDS = ("size", "aspect_ratio", "resolution", "quality", "thinking")

# Sizes offered for a model that takes any size (gpt-image-2, Muse), the ones
# its catalog's rules accept: a square, landscape and portrait, then larger.
_FLEXIBLE_SIZES = (
    "1024x1024",
    "1536x1024",
    "1024x1536",
    "2048x2048",
    "2048x1152",
    "1152x2048",
    "3840x2160",
    "2160x3840",
)
_SHAPES = {1: "square", 2: "landscape", 0: "portrait"}
_LEVELS = {"xhigh": "Extra high", "1k": "1K", "2k": "2K"}
# xAI's catalog declares no controls: its config's, as roomkit documents them.
_XAI_RESOLUTIONS = ("1k", "2k")
_XAI_QUALITIES = ("low", "medium")
_XAI_QUALITY_MODEL = "grok-imagine-image-2.0"


@dataclass(frozen=True)
class ImageControl:
    """One setting a model's drawings take, as its catalog declares it.

    *field* names it in the settings; *option* is the ``ImageOptions`` field
    it sets, *config* the provider config's (xAI), and neither for the size,
    the default of the call's own ``size``. *choices* are ``(label, value)``,
    the model's default ("") first.
    """

    field: str
    label: str
    choices: tuple[tuple[str, str], ...]
    option: str = ""
    config: str = ""


def image_controls(provider: str, model_id: str) -> list[ImageControl]:
    """The settings *model_id* takes, from roomkit's offline catalog: none
    for a model it does not know."""
    vendor = _VENDORS.get(provider)
    if vendor is None:
        return []
    if provider == "xai":
        xai = [
            ImageControl(
                "resolution", "Resolution", _labelled(_XAI_RESOLUTIONS), config="resolution"
            )
        ]
        if model_id == _XAI_QUALITY_MODEL:
            xai.append(
                ImageControl("quality", "Quality", _labelled(_XAI_QUALITIES), config="quality")
            )
        return xai
    try:
        from roomkit.providers.image.options import image_model_entry

        models = importlib.import_module(vendor.catalog).MODELS
        caps = getattr(image_model_entry(models, model_id), "image", None)
    except Exception:
        return []
    if caps is None:
        return []
    controls: list[ImageControl] = []
    sizes = [s for s in caps.sizes if s != "auto"]
    if caps.flexible_size:
        sizes += [s for s in _FLEXIBLE_SIZES if s not in sizes and _fits(caps, s)]
    if sizes:
        choices = (("Model default", ""), *((_size_label(s), s) for s in sizes))
        controls.append(ImageControl("size", "Size", choices))
    if caps.aspect_ratios:
        controls.append(
            ImageControl("aspect_ratio", "Shape", _labelled(caps.aspect_ratios), "aspect_ratio")
        )
    if caps.image_sizes:
        controls.append(
            ImageControl("resolution", "Resolution", _labelled(caps.image_sizes), "image_size")
        )
    qualities = [q for q in caps.qualities if q != "auto"]
    if qualities:
        controls.append(ImageControl("quality", "Quality", _labelled(qualities), "quality"))
    if caps.thinking_levels:
        controls.append(
            ImageControl("thinking", "Thinking", _labelled(caps.thinking_levels), "thinking_level")
        )
    return controls


def _labelled(values: Any) -> tuple[tuple[str, str], ...]:
    return (
        ("Model default", ""),
        *((_LEVELS.get(v, v[:1].upper() + v[1:]), v) for v in values),
    )


def _fits(caps: Any, size: str) -> bool:
    try:
        caps.validate_size(size)
    except ValueError:
        return False
    return True


def _size_label(size: str) -> str:
    width, height = (int(edge) for edge in size.split("x"))
    shape = _SHAPES[(width > height) * 2 or int(width == height)]
    return f"{width}×{height} ({shape})"


def image_models(provider: str) -> list[tuple[str, str]]:
    """``(display name, model id)`` of *provider*'s current image models, from
    roomkit's offline catalog; empty when it cannot be read."""
    vendor = _VENDORS.get(provider)
    if vendor is None:
        return []
    try:
        models = importlib.import_module(vendor.catalog).MODELS
    except Exception:
        return []
    return [(model.display_name or model.id, model.id) for model in models if not model.deprecated]


def default_image_model(provider: str) -> str:
    return _VENDORS[provider].model


def image_model(settings: dict, provider: str) -> str:
    """The model *provider* draws with: the Images tab's, else its default."""
    return str(settings.get(f"image_{provider}_model") or _VENDORS[provider].model)


def images_requested(settings: dict) -> bool:
    """Whether the Images tab picked a provider (whether it can run or not)."""
    return settings.get("image_provider", "") in _VENDORS


def create_image_studio(settings: dict) -> ImageStudio:
    """The session's image provider, as the Images tab sets it.

    Raises:
        FeatureUnavailableError: its backend is not installed.
        ValueError: its API key is missing.
    """
    provider = str(settings.get("image_provider", ""))
    vendor = _VENDORS[provider]
    require(IMAGE_PROVIDER_FEATURES[provider])
    key = str(settings.get(vendor.key) or "").strip()
    if not key:
        raise ValueError(f"{vendor.label} has no API key (Settings → Providers & keys).")
    model = image_model(settings, provider)
    # The Images tab's settings this model takes; one it does not, ignored.
    chosen: dict[str, str] = {}
    config: dict[str, str] = {}
    options: dict[str, str] = {}
    for control in image_controls(provider, model):
        value = str(settings.get(f"image_{provider}_{control.field}") or "")
        if value not in {v for _label, v in control.choices[1:]}:
            continue
        chosen[control.field] = value
        if control.config:
            config[control.config] = value
        elif control.option:
            options[control.option] = value
    images = _build_provider(provider, key, model, config)
    return ImageStudio(images, provider, size=chosen.get("size", ""), options=options)


def _build_provider(provider: str, api_key: str, model: str, config: dict[str, str]) -> Any:
    from pydantic import SecretStr

    key = SecretStr(api_key)
    if provider == "openai":
        from roomkit.providers.openai.config import OpenAIImageConfig
        from roomkit.providers.openai.image import OpenAIImageProvider

        return OpenAIImageProvider(OpenAIImageConfig(api_key=key, model=model))
    if provider == "gemini":
        from roomkit.providers.gemini.config import GeminiImageConfig
        from roomkit.providers.gemini.image import GeminiImageProvider

        return GeminiImageProvider(GeminiImageConfig(api_key=key, model=model))
    if provider == "xai":
        from roomkit.providers.xai.config import XAIImageConfig
        from roomkit.providers.xai.image import XAIImageProvider

        return XAIImageProvider(
            XAIImageConfig.model_validate({"api_key": key, "model": model, **config})
        )
    from roomkit.providers.meta.config import MetaImageConfig
    from roomkit.providers.meta.image import MetaImageProvider

    # Meta answers WebP by default, which Qt may have no plugin to read.
    return MetaImageProvider(MetaImageConfig(api_key=key, model=model, output_format="jpeg"))


# The long side of the copy the conversation model is given to look at: plenty
# to read a picture, at a fraction of a full image's tokens (about 1,400 at
# 1024 px for Claude) on each turn roomkit keeps it in view (RMK-708).
_MODEL_EDGE = 768
# The colours a drawing's palette names, most present first.
_PALETTE_SIZE = 5
# The images an edit can name by id: the session's latest drawings.
_IDS_KEPT = 20


@dataclass
class Drawing:
    """What one generate_image call drew."""

    images: tuple[ImageAttachment, ...]
    ids: tuple[str, ...]
    revised_prompt: str | None
    usage: dict


class ImageStudio:
    """The session's image provider, and the images an edit can change: the
    last one drawn or shared, or a drawing named by its id."""

    def __init__(
        self,
        provider: Any,
        provider_name: str,
        *,
        size: str = "",
        options: dict[str, str] | None = None,
    ) -> None:
        self.provider = provider
        self.provider_name = provider_name
        # The Images tab's defaults: the size a call names none takes, and
        # the options (quality, shape, resolution, thinking) every call does.
        self.size = size
        self.options = dict(options or {})
        self.last: ImageAttachment | None = None
        self._drawn: dict[str, ImageAttachment] = {}
        self._count = 0

    @property
    def model(self) -> str:
        return str(getattr(self.provider, "model_name", "") or "")

    def pricing(self) -> Any:
        """Its model's catalog ``ModelPricing``, or None (priced per image)."""
        try:
            entry = self.provider.catalog_entry()
        except Exception:
            return None
        return getattr(entry, "pricing", None) if entry is not None else None

    async def draw(
        self,
        prompt: str,
        *,
        size: str | None = None,
        edit: bool = False,
        image_id: str | None = None,
    ) -> Drawing:
        """Draw *prompt*, or change an image with it when *edit*: the one
        *image_id* names, else the last.

        Raises:
            ToolRefusedError: nothing was drawn nor billed (no prompt, no image
                to change, a size the provider cannot make).
            ToolFailedError: the provider failed; it may have billed.
        """
        from roomkit import ImageGenerationError, ToolFailedError, ToolRefusedError
        from roomkit.providers.ai.base import ProviderError

        if not prompt.strip():
            raise ToolRefusedError("Say what to draw.")
        references = None
        if edit:
            source = self._drawn.get(image_id) if image_id else self.last
            if source is None:
                raise ToolRefusedError(
                    f"No image {image_id} in this conversation: draw a new one."
                    if image_id
                    else "There is no image in this conversation to change: draw a new one."
                )
            if not getattr(self.provider, "supports_editing", False):
                raise ToolRefusedError(f"{self.model} cannot change an image: draw a new one.")
            references = [_image_part(source)]
        try:
            results = await self._generate(prompt, (size or "").strip(), references)
        except ImageGenerationError as exc:
            # Never retried: any image it delivered was billed, so it is shown.
            if not exc.results:
                raise ToolFailedError(str(exc)) from exc
            results = list(exc.results)
        except ProviderError as exc:
            raise ToolFailedError(str(exc)) from exc
        except ValueError as exc:  # refused before anything was billed
            raise ToolRefusedError(str(exc)) from exc
        try:
            images = tuple(_attachment(result) for result in results)
        except ValueError as exc:
            raise ToolFailedError(
                f"The image came back in a form the app cannot show: {exc}"
            ) from exc
        ids = tuple(self._keep(image) for image in images)
        self.last = images[-1]
        first = results[0]
        return Drawing(images, ids, first.revised_prompt, dict(first.usage or {}))

    async def _generate(self, prompt: str, size: str, references: Any) -> Any:
        """One call, with the Images tab's defaults: a size the assistant
        names wins over the default size, the shape and the resolution."""
        options = dict(self.options)
        if size:
            options.pop("aspect_ratio", None)
            options.pop("image_size", None)
        size = size or self.size
        if not options:
            return await self.provider.generate(
                prompt, size=size or None, reference_images=references
            )
        from roomkit import ImageOptions

        return await self.provider.generate_with_options(
            prompt,
            size=size or None,
            reference_images=references,
            options=ImageOptions.model_validate(options),
        )

    def _keep(self, image: ImageAttachment) -> str:
        self._count += 1
        image_id = f"img_{self._count}"
        self._drawn[image_id] = image
        while len(self._drawn) > _IDS_KEPT:
            del self._drawn[next(iter(self._drawn))]
        return image_id

    async def close(self) -> None:
        try:
            await self.provider.close()
        except Exception:
            logger.debug("closing the image provider failed", exc_info=True)


def drawing_result(drawing: Drawing) -> list[Any]:
    """What the model gets of a drawing: what it is, in text (its id, size,
    dominant colours and the prompt it was drawn from), then a smaller copy to
    look at. roomkit gives a model that does not see the text alone, and keeps
    the latest images in view on the next turns (RMK-708)."""
    from roomkit.providers.ai.base import AITextPart

    described = []
    for image_id, image in zip(drawing.ids, drawing.images, strict=True):
        picture = image.image()
        described.append(
            {
                "id": image_id,
                "size": f"{picture.width()}x{picture.height()}",
                "palette": palette(picture),
            }
        )
    reply: dict[str, Any] = {
        "shown": len(drawing.images),
        "images": described,
        "note": "The image is in the chat. Say in a few words what you drew.",
    }
    if drawing.revised_prompt:
        reply["drawn_from"] = drawing.revised_prompt
    text = AITextPart(text=json.dumps(reply, ensure_ascii=False))
    return [text, *(_model_copy(image) for image in drawing.images)]


def palette(picture: Any, count: int = _PALETTE_SIZE) -> list[dict[str, Any]]:
    """The dominant colours of *picture* (a QImage), most present first, each
    ``{"color": "#rrggbb", "share": 0.31}``: what a request about its colours
    needs, read without looking at it."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage

    small = picture.scaled(48, 48, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    small = small.convertToFormat(QImage.Format_RGB32)
    # Pixels by colour bucket (3 bits a channel), with their sums for the mean.
    buckets: dict[int, list[int]] = {}
    for y in range(small.height()):
        for x in range(small.width()):
            pixel = small.pixel(x, y)
            r, g, b = (pixel >> 16) & 255, (pixel >> 8) & 255, pixel & 255
            sums = buckets.setdefault((r >> 5) << 6 | (g >> 5) << 3 | b >> 5, [0, 0, 0, 0])
            sums[0] += r
            sums[1] += g
            sums[2] += b
            sums[3] += 1
    total = small.width() * small.height() or 1
    ranked = sorted(buckets.values(), key=lambda sums: -sums[3])[:count]
    return [
        {
            "color": f"#{r // n:02x}{g // n:02x}{b // n:02x}",
            "share": round(n / total, 2),
        }
        for r, g, b, n in ranked
    ]


def _attachment(result: Any) -> ImageAttachment:
    """A generated image as the chat keeps any image: PNG or JPEG, metadata
    stripped, bounded in size (``ImageAttachment.from_image``)."""
    from PySide6.QtGui import QImage

    return ImageAttachment.from_image(QImage.fromData(result.decoded()), "Generated image")


def _model_copy(image: ImageAttachment) -> Any:
    """*image* for the model to look at, its long side at most _MODEL_EDGE."""
    from PySide6.QtCore import Qt
    from roomkit.providers.ai.base import AIImagePart

    picture = image.image()
    if max(picture.width(), picture.height()) > _MODEL_EDGE:
        small = picture.scaled(
            _MODEL_EDGE, _MODEL_EDGE, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        image = ImageAttachment.from_image(small, image.name)
    return AIImagePart(url=image.data_url, mime_type=image.mime_type)


def _image_part(image: ImageAttachment) -> Any:
    from roomkit.providers.ai.base import AIImagePart

    return AIImagePart(url=image.data_url, mime_type=image.mime_type)
