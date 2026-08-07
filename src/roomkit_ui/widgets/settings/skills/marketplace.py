"""skills.sh marketplace tab."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from roomkit_ui.skills_sh_client import BASE_URL, SkillsShClient, SkillsShSkill
from roomkit_ui.theme import colors
from roomkit_ui.widgets.settings.skills.widgets import FlowLayout, SkillCard

logger = logging.getLogger(__name__)

InstallCallback = Callable[[SkillsShSkill], Awaitable[None]]
InstalledCheck = Callable[[SkillsShSkill], bool]


class MarketplaceTab(QWidget):
    """Self-contained skills.sh marketplace tab content."""

    def __init__(
        self,
        *,
        on_install_source: InstallCallback | None = None,
        is_source_installed: InstalledCheck | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._cb_install_source = on_install_source
        self._cb_is_source_installed = is_source_installed
        self._loaded = False
        self._results: list[SkillsShSkill] = []
        self._search_timer: QTimer | None = None
        self._installing_source: str | None = None

        c = colors()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(8)

        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        search_icon = QLabel("\U0001f50d")
        search_icon.setStyleSheet("background: transparent; font-size: 14px;")
        search_row.addWidget(search_icon)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Search skills.sh...")
        self._search_input.textChanged.connect(self._on_search_changed)
        search_row.addWidget(self._search_input, 1)

        open_btn = QPushButton("Open skills.sh")
        open_btn.setCursor(Qt.PointingHandCursor)
        open_btn.setFixedHeight(28)
        open_btn.setStyleSheet(
            f"QPushButton {{ font-size: 11px; font-weight: 600;"
            f" background: {c['BG_SECONDARY']}; color: {c['ACCENT_BLUE']};"
            f" border: 1px solid {c['SEPARATOR']}; border-radius: 6px;"
            # Plain string: "}}" would stay literal and break the whole sheet.
            " padding: 0 10px; }"
            f"QPushButton:hover {{ background: {c['BG_TERTIARY']}; }}"
        )
        open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(BASE_URL)))
        search_row.addWidget(open_btn)
        layout.addLayout(search_row)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet(
            f"font-size: 11px; color: {c['TEXT_SECONDARY']}; background: transparent;"
        )
        layout.addWidget(self._status)

        self._container = QWidget()
        self._flow = FlowLayout(self._container, h_spacing=10, v_spacing=10)

        scroll = QScrollArea()
        scroll.setWidget(self._container)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        layout.addWidget(scroll, 1)

    @property
    def loaded(self) -> bool:
        return self._loaded

    def load(self) -> None:
        """Mark the marketplace tab as ready."""
        self._loaded = True
        self._status.setText("Search skills.sh. GitHub and well-known sources can be installed.")

    def _on_search_changed(self, text: str) -> None:
        if self._search_timer:
            self._search_timer.stop()
        self._search_timer = QTimer()
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(lambda: self._do_search(text))
        self._search_timer.start(400)

    def _do_search(self, query: str) -> None:
        query = query.strip()
        if len(query) < 2:
            self._results = []
            self._clear_cards()
            self._status.setText("Type at least 2 characters to search skills.sh.")
            return
        self._status.setText("Searching...")
        asyncio.ensure_future(self._run_search(query))

    async def _run_search(self, query: str) -> None:
        try:
            client = SkillsShClient()
            results = await client.search(query, limit=50)
            self._results = results
            self._render(results)
            self._status.setText(f"{len(results)} results")
        except Exception as exc:
            logger.exception("skills.sh search failed")
            self._status.setText(f"Search failed: {exc}")

    def _clear_cards(self) -> None:
        while self._flow.count():
            item = self._flow.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

    def _render(self, items: list[SkillsShSkill]) -> None:
        self._clear_cards()

        for skill in items:
            installed = self._is_skill_installed(skill)
            card = SkillCard(
                name=skill.name,
                description=skill.source,
                marketplace=True,
                installed=installed,
                downloads=skill.installs,
                slug=skill.skill_id,
            )
            if card.action_btn and not installed:
                card.action_btn.clicked.connect(
                    lambda _checked, s=skill, c=card: self._install_skill_source(s, c)
                )
            self._flow.addWidget(card)

        self._container.updateGeometry()

    def _is_skill_installed(self, skill: SkillsShSkill) -> bool:
        if self._cb_is_source_installed is None:
            return False
        return self._cb_is_source_installed(skill)

    def _install_skill_source(self, skill: SkillsShSkill, card: SkillCard) -> None:
        if self._installing_source or self._cb_install_source is None:
            return
        self._installing_source = skill.id
        if card.action_btn:
            card.action_btn.setText("Installing...")
            card.action_btn.setEnabled(False)
        asyncio.ensure_future(self._do_install(skill, card))

    async def _do_install(self, skill: SkillsShSkill, card: SkillCard) -> None:
        try:
            if self._cb_install_source is None:
                raise RuntimeError("No installer configured")
            await self._cb_install_source(skill)
            if card.action_btn:
                c = colors()
                card.action_btn.setText("Installed \u2713")
                card.action_btn.setStyleSheet(
                    f"QPushButton {{ font-size: 11px; font-weight: 600;"
                    f" background: {c['BG_TERTIARY']}; color: {c['TEXT_SECONDARY']};"
                    " border: none; border-radius: 6px; padding: 0 12px; }}"
                )
        except Exception as exc:
            logger.exception("Failed to install skills.sh source %s", skill.source)
            if card.action_btn:
                card.action_btn.setText("Retry")
                card.action_btn.setEnabled(True)
            self._status.setText(f"Install failed: {exc}")
        finally:
            self._installing_source = None
