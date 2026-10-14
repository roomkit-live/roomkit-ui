"""A model's files, download progress and actions, without selecting a provider."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QProgressBar, QPushButton, QVBoxLayout, QWidget

from roomkit_ui.widgets.settings.controls import StatusBadge, label
from roomkit_ui.widgets.settings.model_jobs import DownloadState
from roomkit_ui.widgets.settings.model_library import LibraryModel


class _ModelRow(QWidget):
    def __init__(
        self,
        model: LibraryModel,
        *,
        allow_delete: bool = True,
        badge: tuple[str, str] | None = None,
    ) -> None:
        super().__init__()
        self.setObjectName("settingsLibraryItem")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName(model.name)
        self.model = model
        self._allow_delete = allow_delete
        self.phase = "available"
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(8)
        heading = QHBoxLayout()
        heading.addWidget(label(model.name, "settingsRowTitle"), 1)
        self.status_label = StatusBadge()
        heading.addWidget(self.status_label)
        layout.addLayout(heading)
        layout.addWidget(label(model.detail, "settingsHint"))
        actions = QHBoxLayout()
        actions.addWidget(label(model.size, "settingsHint"))
        # A second, lasting fact beside the size (whether it fits this computer).
        self.badge = StatusBadge()
        # Hide only: its layout has no widget yet, and showing a parentless
        # widget opens it as a window of its own (a flash on Windows).
        if badge is None:
            self.badge.hide()
        else:
            self.badge.set_status(*badge)
        actions.addWidget(self.badge)
        actions.addStretch(1)
        self.action_btn = QPushButton("Download")
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.hide()
        self.delete_btn = QPushButton("Delete files")
        for button, verb in (
            (self.action_btn, "Download"),
            (self.cancel_btn, "Cancel the download of"),
            (self.delete_btn, "Delete"),
        ):
            button.setAutoDefault(False)
            button.setCursor(Qt.PointingHandCursor)
            button.setAccessibleName(f"{verb} {model.name}")
            actions.addWidget(button)
        layout.addLayout(actions)
        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("settingsDownloadProgress")
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setAccessibleName(f"Download progress for {model.name}")
        layout.addWidget(self.progress_bar)
        self.error = label("", "settingsError")
        self.error.setTextFormat(Qt.PlainText)
        layout.addWidget(self.error)

    def refresh(self, state: DownloadState | None) -> None:
        self.phase = (
            state.phase if state else "downloaded" if self.model.downloaded() else "available"
        )
        active = self.phase in {"resolving", "downloading"}
        self.action_btn.setVisible(self.phase in {"available", "error"})
        self.action_btn.setText("Retry download" if self.phase == "error" else "Download")
        self.cancel_btn.setVisible(active and self.model.cancellable)
        self.delete_btn.setVisible(self._allow_delete and self.phase == "downloaded")
        self.progress_bar.setVisible(active)
        self.progress_bar.setRange(0, 0 if self.phase == "resolving" else 100)
        self.progress_bar.setValue(state.percent if state else 0)
        text, tone = {
            "available": ("Not downloaded", "neutral"),
            "downloaded": ("Downloaded", "success"),
            "resolving": ("Preparing…", "active"),
            "downloading": (f"Downloading · {state.percent if state else 0}%", "active"),
            "error": ("Download failed", "error"),
        }[self.phase]
        self.status_label.set_status(text, tone)
        self.error.setText(state.error if state else "")
        self.error.setVisible(bool(state and state.error))
