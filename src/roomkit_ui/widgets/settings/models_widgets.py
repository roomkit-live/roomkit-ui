"""Row widgets for the AI Models settings page."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)


class _ModelRow(QWidget):
    """A single row in the local model list: radio + name + type + size + action + progress."""

    def __init__(self, model, c: dict, show_radio: bool = True, parent=None) -> None:
        super().__init__(parent)
        from roomkit_ui.model_manager import is_model_downloaded

        self.model = model
        self._c = c

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(4)

        # Top line: radio + info + buttons
        top = QHBoxLayout()
        top.setSpacing(8)

        self.radio = QRadioButton()
        if not show_radio:
            self.radio.hide()
        top.addWidget(self.radio)

        name_label = QLabel(model.name)
        name_label.setStyleSheet("font-size: 13px; font-weight: 500; background: transparent;")
        top.addWidget(name_label)

        type_label = QLabel(model.type)
        type_label.setStyleSheet(
            f"font-size: 11px; color: {c['TEXT_SECONDARY']};"
            f" background: {c['BG_TERTIARY']}; border-radius: 4px;"
            f" padding: 1px 6px;"
        )
        top.addWidget(type_label)

        size_label = QLabel(model.size)
        size_label.setStyleSheet(
            f"font-size: 11px; color: {c['TEXT_SECONDARY']}; background: transparent;"
        )
        top.addWidget(size_label)

        top.addStretch()

        self.status_label = QLabel()
        self.status_label.setStyleSheet(
            f"font-size: 12px; color: {c['ACCENT_GREEN']}; background: transparent;"
        )
        top.addWidget(self.status_label)

        self.action_btn = QPushButton()
        self.action_btn.setCursor(Qt.PointingHandCursor)
        self.action_btn.setFixedHeight(26)
        top.addWidget(self.action_btn)

        self.delete_btn = QPushButton("Delete")
        self.delete_btn.setCursor(Qt.PointingHandCursor)
        self.delete_btn.setFixedHeight(26)
        self.delete_btn.setStyleSheet(
            f"QPushButton {{ font-size: 12px; padding: 2px 10px;"
            f" background: transparent; border: 1px solid {c['ACCENT_RED']};"
            f" color: {c['ACCENT_RED']}; border-radius: 4px; }}"
            f"QPushButton:hover {{ background: {c['ACCENT_RED']};"
            f" color: white; }}"
        )
        top.addWidget(self.delete_btn)

        outer.addLayout(top)

        # Progress bar (hidden by default)
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setStyleSheet(
            f"QProgressBar {{ background: {c['BG_TERTIARY']};"
            f" border: none; border-radius: 3px; }}"
            f"QProgressBar::chunk {{ background: {c['ACCENT_BLUE']};"
            f" border-radius: 3px; }}"
        )
        self.progress_bar.hide()
        outer.addWidget(self.progress_bar)

        self._refresh_state(is_model_downloaded(model.id))

    def _refresh_state(self, downloaded: bool) -> None:
        c = self._c
        self.progress_bar.hide()
        if downloaded:
            self.status_label.setText("\u2713 Ready")
            self.status_label.setStyleSheet(
                f"font-size: 12px; color: {c['ACCENT_GREEN']}; background: transparent;"
            )
            self.action_btn.hide()
            self.delete_btn.show()
        else:
            self.status_label.setText("")
            self.action_btn.setText("Download")
            self.action_btn.setStyleSheet(
                f"QPushButton {{ font-size: 12px; padding: 2px 10px;"
                f" background: {c['ACCENT_BLUE']}; color: white;"
                f" border: none; border-radius: 4px; }}"
                f"QPushButton:hover {{ opacity: 0.8; }}"
            )
            self.action_btn.setEnabled(True)
            self.action_btn.show()
            self.delete_btn.hide()

    def set_downloading(self, pct: int) -> None:
        self.action_btn.hide()
        self.delete_btn.hide()
        if self.progress_bar.maximum() == 0:
            self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(pct)
        self.progress_bar.show()
        self.status_label.setText(f"{pct}%")
        self.status_label.setStyleSheet(
            f"font-size: 12px; color: {self._c['TEXT_SECONDARY']}; background: transparent;"
        )

    def set_resolving(self) -> None:
        self.action_btn.hide()
        self.delete_btn.hide()
        self.progress_bar.setRange(0, 0)  # indeterminate
        self.progress_bar.show()
        self.status_label.setText("Resolving\u2026")
        self.status_label.setStyleSheet(
            f"font-size: 12px; color: {self._c['TEXT_SECONDARY']}; background: transparent;"
        )

    def set_downloaded(self) -> None:
        self.progress_bar.setRange(0, 100)  # restore determinate mode
        self._refresh_state(True)

    def set_not_downloaded(self) -> None:
        self.progress_bar.setRange(0, 100)
        self._refresh_state(False)

    def set_error(self) -> None:
        self.progress_bar.hide()
        self.progress_bar.setRange(0, 100)
        self.action_btn.setText("Retry")
        self.action_btn.setStyleSheet(
            f"QPushButton {{ font-size: 12px; padding: 2px 10px;"
            f" background: {self._c['ACCENT_BLUE']}; color: white;"
            f" border: none; border-radius: 4px; }}"
            f"QPushButton:hover {{ opacity: 0.8; }}"
        )
        self.action_btn.setEnabled(True)
        self.action_btn.show()
        self.status_label.setText("Error")
        self.status_label.setStyleSheet(
            f"font-size: 12px; color: {self._c['ACCENT_RED']}; background: transparent;"
        )
