"""Image previews shared by the composer and saved messages."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from roomkit_ui.widgets.camera_dialog import CameraDialog
    from roomkit_ui.widgets.camera_process import CameraProcess

from PySide6.QtCore import QMimeData, QPoint, QSize, QStandardPaths, Qt, Signal, Slot
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from roomkit_ui.icons import svg_icon
from roomkit_ui.images import MAX_IMAGES, ImageAttachment
from roomkit_ui.theme import colors
from roomkit_ui.theme_live import bind_theme, themed_style
from roomkit_ui.widgets.menus import menu_action, popup_above


def save_image(image: ImageAttachment, parent: QWidget) -> None:
    """Save *image* where the user picks, as the chat keeps it (PNG or JPEG):
    its bytes as they are, never encoded again."""
    png = image.mime_type == "image/png"
    suffix = ".png" if png else ".jpg"
    folder = QStandardPaths.writableLocation(QStandardPaths.PicturesLocation) or str(Path.home())
    stem = Path(image.name).stem.strip() or "Image"
    path, _ = QFileDialog.getSaveFileName(
        parent,
        "Save Image",
        str(Path(folder) / f"{stem}{suffix}"),
        "PNG image (*.png)" if png else "JPEG image (*.jpg *.jpeg)",
    )
    if not path:
        return
    target = Path(path)
    if target.suffix.lower() not in ((".png",) if png else (".jpg", ".jpeg")):
        target = target.with_name(target.name + suffix)
    try:
        target.write_bytes(image.bytes())
    except (OSError, ValueError) as exc:
        QMessageBox.warning(parent, "Save Image", f"The image could not be saved: {exc}")


def show_image(image: ImageAttachment, parent: QWidget) -> None:
    dialog = QDialog(parent)
    dialog.setAttribute(Qt.WA_DeleteOnClose)
    dialog.setWindowTitle(image.name)
    layout = QVBoxLayout(dialog)
    label = QLabel()
    label.setAlignment(Qt.AlignCenter)
    screen = parent.screen().availableGeometry().size()
    size = QSize(min(900, screen.width() - 80), min(700, screen.height() - 150))
    label.setPixmap(
        QPixmap.fromImage(image.image()).scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    )
    layout.addWidget(label)
    buttons = QHBoxLayout()
    save = QPushButton("Save…")
    save.setIcon(svg_icon("arrow-down-tray", colors()["TEXT_PRIMARY"], 18))
    save.setAccessibleName(f"Save image: {image.name}")
    save.clicked.connect(lambda: save_image(image, dialog))
    close = QPushButton("Close")
    close.clicked.connect(dialog.accept)
    buttons.addWidget(save)
    buttons.addStretch()
    buttons.addWidget(close)
    layout.addLayout(buttons)
    dialog.open()


class ImagePreview(QToolButton):
    def __init__(self, image: ImageAttachment, *, size: int = 72, parent=None) -> None:
        super().__init__(parent)
        pixmap = QPixmap.fromImage(image.image())
        icon_size = QSize(size - 8, size - 8)
        if size > 100 and not pixmap.isNull():
            icon_size = pixmap.size().scaled(icon_size, Qt.KeepAspectRatio)
        self.setFixedSize(icon_size + QSize(8, 8))
        self.setIconSize(icon_size)
        self.setIcon(QIcon(pixmap))
        self.setToolTip(image.name)
        self.setAccessibleName(f"View image: {image.name}")
        self.setCursor(Qt.PointingHandCursor)
        themed_style(
            self,
            lambda c: (
                f"QToolButton {{ background: {c['BG_TERTIARY']};"
                " border: 1px solid transparent; border-radius: 10px; padding: 3px; }"
                f"QToolButton:focus {{ border-color: {c['ACCENT_BRAND']}; }}"
            ),
        )
        self.clicked.connect(lambda: show_image(image, self))
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(lambda pos: self._menu(image, pos))

    def _menu(self, image: ImageAttachment, pos: QPoint) -> None:
        menu = QMenu(self)
        save = menu_action(menu, "Save image…", "arrow-down-tray")
        save.triggered.connect(lambda: save_image(image, self))
        menu.setAttribute(Qt.WA_DeleteOnClose)
        menu.popup(self.mapToGlobal(pos))


class ImageAttachments(QWidget):
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.images: tuple[ImageAttachment, ...] = ()
        self._unavailable = ""
        self._camera: CameraDialog | CameraProcess | None = None
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(4, 4, 4, 0)
        self._row = QHBoxLayout()
        self._row.setSpacing(8)
        self._row.addStretch()
        self._layout.addLayout(self._row)
        self._notice = QLabel()
        self._notice.setWordWrap(True)
        self._notice.hide()
        themed_style(
            self._notice,
            lambda c: f"color: {c['TEXT_SECONDARY']}; background: transparent; font-size: 12px;",
        )
        self._layout.addWidget(self._notice)
        self.hide()

    def set_availability(self, reason: str) -> None:
        self._unavailable = reason
        if reason and self._camera is not None:
            self._camera.reject()

    def menu(self, button: QWidget) -> None:
        menu = QMenu(button)
        files = menu_action(menu, "Choose images…", "photo")
        camera = menu_action(menu, "Take a photo…", "camera")
        files.triggered.connect(self._choose_files)
        camera.triggered.connect(self._open_camera)
        menu.setAttribute(Qt.WA_DeleteOnClose)
        popup_above(menu, button)

    def _choose_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Add images", "", "Images (*.png *.jpg *.jpeg *.webp *.gif *.bmp *.heic *.heif)"
        )
        self.add_files(paths)

    def add_files(self, paths: list[str]) -> None:
        for path in paths:
            self._add(lambda path=path: ImageAttachment.from_file(path))

    def add_image(self, image: QImage, name: str = "Pasted image") -> None:
        self._add(lambda: ImageAttachment.from_image(image, name))

    def add_mime(self, mime: QMimeData) -> None:
        paths = [url.toLocalFile() for url in mime.urls() if url.isLocalFile()]
        if paths:
            self.add_files(paths)
        elif mime.hasImage():
            image = mime.imageData()
            if isinstance(image, QPixmap):
                image = image.toImage()
            if isinstance(image, QImage):
                self.add_image(image)

    def _add(self, load) -> None:
        if self._unavailable:
            self.notice(self._unavailable)
            return
        if len(self.images) >= MAX_IMAGES:
            self.notice(f"You can add up to {MAX_IMAGES} images per message.")
            return
        try:
            image = load()
        except (ValueError, OSError) as exc:
            self.notice(str(exc))
            return
        self.images = (*self.images, image)
        self._notice.clear()
        self._render()

    def notice(self, message: str) -> None:
        self._notice.setText(message)
        self._notice.setVisible(bool(message))
        self.show()

    def remove(self, index: int) -> None:
        self.images = self.images[:index] + self.images[index + 1 :]
        self._notice.clear()
        self._render()

    def clear(self) -> None:
        self.close_camera()
        self.images = ()
        self._notice.clear()
        self._render()

    def close_camera(self) -> None:
        if self._camera is not None:
            self._camera.reject()

    def _render(self) -> None:
        self._notice.setVisible(bool(self._notice.text()))
        while self._row.count() > 1:
            item = self._row.takeAt(0)
            if item is not None and (widget := item.widget()) is not None:
                widget.hide()
                widget.deleteLater()
        for index, image in enumerate(self.images):
            preview = ImagePreview(image)
            remove = QToolButton(preview)
            remove.setFixedSize(22, 22)
            remove.move(50, 0)

            def refresh_icon(button: QToolButton = remove) -> None:
                button.setIcon(svg_icon("x-mark", colors()["TEXT_PRIMARY"], 14))

            bind_theme(remove, refresh_icon, name="icon")
            remove.setAccessibleName(f"Remove image: {image.name}")
            remove.setToolTip("Remove image")
            remove.clicked.connect(lambda _checked=False, index=index: self.remove(index))
            themed_style(
                remove,
                lambda c: (
                    f"QToolButton {{ background: {c['BG_SECONDARY']};"
                    " border: none; border-radius: 11px; }"
                ),
            )
            self._row.insertWidget(index, preview)
        self.setVisible(bool(self.images) or bool(self._notice.text()))
        self.changed.emit()

    def _open_camera(self) -> None:
        from roomkit_ui.widgets.camera_process import create_camera

        if self._unavailable:
            self.notice(self._unavailable)
        elif len(self.images) >= MAX_IMAGES:
            self.notice(f"You can add up to {MAX_IMAGES} images per message.")
        elif self._camera is not None:
            self._camera.raise_()
        else:
            camera = create_camera(self, self.notice)
            self._camera = camera
            camera.photo_selected.connect(self._camera_photo_selected)
            camera.finished.connect(self._camera_closed)
            camera.open()

    @Slot(object)
    def _camera_photo_selected(self, photo: ImageAttachment) -> None:
        self._add(lambda: photo)

    @Slot()
    def _camera_closed(self) -> None:
        camera, self._camera = self._camera, None
        if camera is not None:
            camera.deleteLater()
