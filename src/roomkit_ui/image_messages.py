"""Image content for the current turn and bounded visual context on resuming."""

from __future__ import annotations

from datetime import UTC, datetime

from roomkit.models.event import CompositeContent, EventContent, MediaContent, TextContent
from roomkit.providers.ai.base import AIImagePart, AIMessage, AITextPart

from roomkit_ui.images import MAX_IMAGES, ImageAttachment, restore_images
from roomkit_ui.memory import _SessionWindow


def message_content(text: str, images: tuple[ImageAttachment, ...]):
    if not images:
        return TextContent(body=text)
    parts: list[EventContent] = [TextContent(body=text)] if text else []
    parts.extend(
        MediaContent(
            url=image.data_url, mime_type=image.data_url.split(";", 1)[0][5:], filename=image.name
        )
        for image in images
    )
    return CompositeContent(parts=parts)


class ImageSessionWindow(_SessionWindow):
    def __init__(self, entries: list[dict], *, vision: bool) -> None:
        super().__init__(datetime.now(UTC), 50)
        self._images: list[AIMessage] = []
        remaining = MAX_IMAGES
        if vision:
            for entry in reversed(entries[-50:]):
                if entry.get("role") != "user" or not entry.get("images"):
                    continue
                images = restore_images(entry["images"])[-remaining:]
                self._images.insert(
                    0,
                    AIMessage(
                        role="user",
                        content=[
                            AITextPart(
                                text="Previously shared images (conversation context only):"
                            ),
                            *(
                                AIImagePart(
                                    url=image.data_url,
                                    mime_type=image.data_url.split(";", 1)[0][5:],
                                )
                                for image in images
                            ),
                        ],
                    ),
                )
                remaining -= len(images)
                if not remaining:
                    break

    async def retrieve(self, room_id, current_event, context, *, channel_id=None):
        result = await super().retrieve(room_id, current_event, context, channel_id=channel_id)
        result.messages[:0] = self._images
        return result
