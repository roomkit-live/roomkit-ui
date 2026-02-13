"""My Skills tab — source list and skill card grid."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from roomkit_ui.theme import colors
from roomkit_ui.widgets.settings.skills.widgets import FlowLayout, SkillCard


def source_display(src: dict) -> str:
    """Format a source dict for display in the source list."""
    label = src.get("label") or "Unnamed"
    src_type = src.get("type", "git")
    return f"{label} ({src_type})"


class MySkillsTab(QWidget):
    """Self-contained 'My Skills' tab content."""

    def __init__(
        self,
        *,
        on_add_source,
        on_remove_source,
        on_source_activated,
        on_skill_toggled,
        on_refresh,
        on_uninstall,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._cb_skill_toggled = on_skill_toggled
        self._cb_uninstall = on_uninstall

        c = colors()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(8)

        # Source management row
        src_row = QHBoxLayout()
        src_row.setSpacing(8)
        src_label = QLabel("Sources")
        src_label.setStyleSheet(
            f"font-size: 12px; font-weight: 600; color: {c['TEXT_SECONDARY']};"
            f" text-transform: uppercase; letter-spacing: 1px; background: transparent;"
        )
        src_row.addWidget(src_label)
        src_row.addStretch()
        add_src_btn = QPushButton("+ Add Source")
        add_src_btn.setCursor(Qt.PointingHandCursor)
        add_src_btn.setFixedHeight(26)
        add_src_btn.setStyleSheet(
            f"QPushButton {{ font-size: 11px; font-weight: 600;"
            f" background: {c['BG_SECONDARY']}; color: {c['ACCENT_BLUE']};"
            f" border: 1px solid {c['SEPARATOR']}; border-radius: 6px;"
            f" padding: 0 10px; }}"
            f"QPushButton:hover {{ background: {c['BG_TERTIARY']}; }}"
        )
        add_src_btn.clicked.connect(on_add_source)
        src_row.addWidget(add_src_btn)
        manage_btn = QPushButton("\u2699")
        manage_btn.setToolTip("Manage sources")
        manage_btn.setCursor(Qt.PointingHandCursor)
        manage_btn.setFixedSize(26, 26)
        manage_btn.setStyleSheet(
            f"QPushButton {{ font-size: 14px; background: {c['BG_SECONDARY']};"
            f" border: 1px solid {c['SEPARATOR']}; border-radius: 6px; padding: 0; }}"
            f"QPushButton:hover {{ background: {c['BG_TERTIARY']}; }}"
        )
        manage_btn.clicked.connect(self._toggle_source_list)
        src_row.addWidget(manage_btn)
        layout.addLayout(src_row)

        # Collapsible source list
        self._source_list_wrapper = QWidget()
        sl_layout = QVBoxLayout(self._source_list_wrapper)
        sl_layout.setContentsMargins(0, 0, 0, 0)
        sl_layout.setSpacing(4)
        self.source_list = QListWidget()
        self.source_list.setStyleSheet(
            f"QListWidget {{ border: 1px solid {c['SEPARATOR']}; border-radius: 6px; }}"
            f"QListWidget::item {{ padding: 6px 10px; }}"
        )
        self.source_list.setMaximumHeight(120)
        sl_layout.addWidget(self.source_list)

        _btn_style = (
            f"QPushButton {{ font-size: 16px; font-weight: 700;"
            f" color: {c['TEXT_PRIMARY']}; background-color: {c['BG_SECONDARY']};"
            f" border: 1px solid {c['BG_TERTIARY']}; border-radius: 6px;"
            f" padding: 0px; min-width: 26px; min-height: 26px; }}"
            f"QPushButton:hover {{ background-color: {c['BG_TERTIARY']}; }}"
        )
        sl_btn_row = QHBoxLayout()
        sl_btn_row.setSpacing(4)
        remove_btn = QPushButton("\u2212")
        remove_btn.setFixedSize(26, 26)
        remove_btn.setStyleSheet(_btn_style)
        remove_btn.clicked.connect(lambda: on_remove_source(self.source_list.currentRow()))
        sl_btn_row.addWidget(remove_btn)
        sl_btn_row.addStretch()
        sl_layout.addLayout(sl_btn_row)

        self._source_list_wrapper.setVisible(False)
        layout.addWidget(self._source_list_wrapper)

        # My skills cards (scroll area)
        self._container = QWidget()
        self._flow = FlowLayout(self._container, h_spacing=10, v_spacing=10)

        scroll = QScrollArea()
        scroll.setWidget(self._container)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        layout.addWidget(scroll, 1)

        # Refresh button
        refresh_btn = QPushButton("Refresh Skills")
        refresh_btn.setCursor(Qt.PointingHandCursor)
        refresh_btn.clicked.connect(on_refresh)
        layout.addWidget(refresh_btn)

        # Source double-click
        self.source_list.itemDoubleClicked.connect(
            lambda _item: on_source_activated(self.source_list.currentRow())
        )

    def _toggle_source_list(self) -> None:
        self._source_list_wrapper.setVisible(not self._source_list_wrapper.isVisible())

    def refresh(self, sources: list[dict], enabled: set[str]) -> None:
        """Re-scan sources and rebuild the skill card grid."""
        # Clear existing cards
        while self._flow.count():
            item = self._flow.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        # Auto-inject clawhub source if not present
        sources_with_clawhub = list(sources)
        has_clawhub = any(s.get("type") == "clawhub" for s in sources_with_clawhub)
        if not has_clawhub:
            sources_with_clawhub.append({"type": "clawhub", "label": "ClawHub"})

        try:
            from roomkit_ui.skill_manager import discover_all_skills

            skills = discover_all_skills(sources_with_clawhub)
        except Exception:
            skills = []

        for meta, skill_path, source_label in skills:
            card = SkillCard(
                name=meta.name,
                description=meta.description,
                source_label=source_label,
                checked=meta.name in enabled,
                marketplace=False,
            )
            if card.checkbox:
                card.checkbox.toggled.connect(
                    lambda checked, n=meta.name: self._cb_skill_toggled(n, checked)
                )
            # Wire uninstall for ClawHub skills
            if card.action_btn and source_label == "ClawHub":
                card.action_btn.clicked.connect(
                    lambda _checked, slug=skill_path.name: self._cb_uninstall(slug)
                )
            self._flow.addWidget(card)

        self._container.updateGeometry()
