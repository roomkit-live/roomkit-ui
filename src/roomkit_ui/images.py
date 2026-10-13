"""Bounded, self-contained images shared by drafts, history and RoomKit."""

from __future__ import annotations

import base64
import binascii
from dataclasses import asdict, dataclass
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize, Qt
from PySide6.QtGui import QImage, QImageReader, QPainter

MAX_IMAGES = 4
MAX_SOURCE_BYTES = 20 * 1024 * 1024
MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_EDGE = 2048
_FORMATS = {b"png", b"jpeg", b"jpg", b"webp", b"gif", b"bmp", b"heic", b"heif"}


@dataclass(frozen=True)
class ImageAttachment:
    name: str
    data_url: str

    def snapshot(self) -> dict:
        return asdict(self)

    def image(self) -> QImage:
        return QImage.fromData(self.bytes())

    @property
    def mime_type(self) -> str:
        """``image/png`` or ``image/jpeg``, as its data URL says."""
        return self.data_url.split(";", 1)[0].removeprefix("data:")

    def bytes(self) -> bytes:
        try:
            prefix, encoded = self.data_url.split(",", 1)
            if prefix not in ("data:image/png;base64", "data:image/jpeg;base64"):
                raise ValueError
            if len(encoded) > (MAX_IMAGE_BYTES + 2) // 3 * 4:
                raise ValueError
            return base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("This image is invalid or too large.") from exc

    @classmethod
    def restore(cls, value: dict) -> ImageAttachment:
        if not isinstance(value, dict) or not all(
            isinstance(value.get(key), str) for key in ("name", "data_url")
        ):
            raise ValueError("Invalid saved image.")
        image = cls(value["name"][:200], value["data_url"])
        image.bytes()  # Never load remote or local-file URLs from saved history.
        return image

    @classmethod
    def from_file(cls, path: str) -> ImageAttachment:
        source = Path(path)
        if not source.is_file() or source.stat().st_size > MAX_SOURCE_BYTES:
            raise ValueError("Choose an image smaller than 20 MB.")
        reader = QImageReader(str(source))
        if bytes(reader.format().data()).lower() not in _FORMATS or not reader.canRead():
            raise ValueError("Choose a PNG, JPEG, WebP, GIF, BMP or HEIC image.")
        size = reader.size()
        if not size.isValid() or size.width() * size.height() > 80_000_000:
            raise ValueError("This image is too large to open.")
        reader.setAutoTransform(True)
        if max(size.width(), size.height()) > MAX_EDGE:
            reader.setScaledSize(size.scaled(QSize(MAX_EDGE, MAX_EDGE), Qt.KeepAspectRatio))
        return cls.from_image(reader.read(), source.name)

    @classmethod
    def from_image(cls, image: QImage, name: str = "Pasted image") -> ImageAttachment:
        if image.isNull():
            raise ValueError("This image could not be opened.")
        if max(image.width(), image.height()) > MAX_EDGE:
            image = image.scaled(MAX_EDGE, MAX_EDGE, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        # A fresh raster carries no source path, GPS or other embedded metadata.
        clean = QImage(
            image.size(), QImage.Format_ARGB32 if image.hasAlphaChannel() else QImage.Format_RGB32
        )
        clean.fill(Qt.transparent if image.hasAlphaChannel() else Qt.white)
        painter = QPainter(clean)
        painter.drawImage(0, 0, image)
        painter.end()
        fmt = "PNG" if image.hasAlphaChannel() else "JPEG"
        while True:
            data = QByteArray()
            buffer = QBuffer(data)
            buffer.open(QIODevice.WriteOnly)
            if not clean.save(buffer, fmt, 88):  # type: ignore[call-overload]
                raise ValueError("This image could not be prepared.")
            buffer.close()
            if data.size() <= MAX_IMAGE_BYTES:
                break
            clean = clean.scaled(
                clean.width() * 3 // 4,
                clean.height() * 3 // 4,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
        mime = "image/png" if fmt == "PNG" else "image/jpeg"
        return cls(
            name[:200], f"data:{mime};base64,{base64.b64encode(data.data()).decode('ascii')}"
        )


def restore_images(values: list[dict]) -> tuple[ImageAttachment, ...]:
    if not isinstance(values, list) or len(values) > MAX_IMAGES:
        raise ValueError("Invalid saved images.")
    return tuple(ImageAttachment.restore(value) for value in values)
