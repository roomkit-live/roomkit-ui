"""ClawHub Marketplace tab — search, browse, and install skills."""

from __future__ import annotations

import asyncio
import logging

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from roomkit_ui.theme import colors
from roomkit_ui.widgets.settings.skills.widgets import FlowLayout, SkillCard

logger = logging.getLogger(__name__)


class MarketplaceTab(QWidget):
    """Self-contained ClawHub marketplace tab content."""

    def __init__(self, *, on_installed=None, parent=None) -> None:
        super().__init__(parent)
        self._cb_installed = on_installed
        self._loaded = False
        self._skills: list = []
        self._cursor: str | None = None
        self._installing_slug: str | None = None
        self._search_timer: QTimer | None = None

        c = colors()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(8)

        # Search bar
        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        search_icon = QLabel("\U0001f50d")
        search_icon.setStyleSheet("background: transparent; font-size: 14px;")
        search_row.addWidget(search_icon)
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Search skills...")
        self._search_input.textChanged.connect(self._on_search_changed)
        search_row.addWidget(self._search_input, 1)
        layout.addLayout(search_row)

        # Marketplace status
        self._status = QLabel("")
        self._status.setStyleSheet(
            f"font-size: 11px; color: {c['TEXT_SECONDARY']}; background: transparent;"
        )
        layout.addWidget(self._status)

        # Marketplace cards (scroll area)
        self._container = QWidget()
        self._flow = FlowLayout(self._container, h_spacing=10, v_spacing=10)

        scroll = QScrollArea()
        scroll.setWidget(self._container)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        layout.addWidget(scroll, 1)

    @property
    def loaded(self) -> bool:
        return self._loaded

    def load(self) -> None:
        """Fetch the initial marketplace listing."""
        self._status.setText("Loading...")
        asyncio.ensure_future(self._fetch())

    async def _fetch(self) -> None:
        try:
            from roomkit_ui.clawhub_client import ClawHubClient

            client = ClawHubClient()
            items, cursor = await client.list_skills(self._cursor)
            self._skills = items
            self._cursor = cursor
            self._loaded = True
            self._render(items)
            self._status.setText(f"{len(items)} skills")
        except Exception as exc:
            logger.exception("Failed to load marketplace")
            self._status.setText(f"Error: {exc}")

    def _on_search_changed(self, text: str) -> None:
        if self._search_timer:
            self._search_timer.stop()
        self._search_timer = QTimer()
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(lambda: self._do_search(text))
        self._search_timer.start(400)

    def _do_search(self, query: str) -> None:
        query = query.strip()
        if not query:
            if self._skills:
                self._render(self._skills)
                self._status.setText(f"{len(self._skills)} skills")
            else:
                self.load()
            return
        self._status.setText("Searching...")
        asyncio.ensure_future(self._run_search(query))

    async def _run_search(self, query: str) -> None:
        try:
            from roomkit_ui.clawhub_client import ClawHubClient

            client = ClawHubClient()
            results = await client.search(query)
            self._render(results)
            self._status.setText(f"{len(results)} results")
        except Exception as exc:
            logger.exception("Marketplace search failed")
            self._status.setText(f"Error: {exc}")

    def _render(self, items) -> None:
        # Clear existing
        while self._flow.count():
            item = self._flow.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        from roomkit_ui.skill_manager import list_clawhub_installed

        installed_slugs = set(list_clawhub_installed())

        for skill_info in items:
            is_installed = skill_info.slug in installed_slugs
            card = SkillCard(
                name=skill_info.display_name or skill_info.slug,
                description=skill_info.summary or "",
                marketplace=True,
                installed=is_installed,
                downloads=skill_info.downloads,
                version=skill_info.version,
                slug=skill_info.slug,
            )
            if card.action_btn and not is_installed:
                card.action_btn.clicked.connect(
                    lambda _checked, s=skill_info.slug, n=skill_info.display_name, c=card: (
                        self._install_skill(s, n, c)
                    )
                )
            self._flow.addWidget(card)

        self._container.updateGeometry()

    def _install_skill(self, slug: str, name: str, card: SkillCard) -> None:
        if self._installing_slug:
            return
        self._installing_slug = slug
        if card.action_btn:
            card.action_btn.setText("Installing...")
            card.action_btn.setEnabled(False)
        asyncio.ensure_future(self._do_install(slug, name, card))

    async def _do_install(self, slug: str, name: str, card: SkillCard) -> None:
        try:
            from roomkit_ui.clawhub_client import ClawHubClient

            client = ClawHubClient()
            await client.download_skill(slug)
            if card.action_btn:
                c = colors()
                card.action_btn.setText("Installed \u2713")
                card.action_btn.setStyleSheet(
                    f"QPushButton {{ font-size: 11px; font-weight: 600;"
                    f" background: {c['BG_TERTIARY']}; color: {c['TEXT_SECONDARY']};"
                    f" border: none; border-radius: 6px; padding: 0 12px; }}"
                )
            logger.info("Installed ClawHub skill: %s (%s)", name, slug)
            if self._cb_installed:
                self._cb_installed()
        except Exception as exc:
            logger.exception("Failed to install %s", slug)
            if card.action_btn:
                card.action_btn.setText("Error")
                card.action_btn.setEnabled(True)
            self._status.setText(f"Install failed: {exc}")
        finally:
            self._installing_slug = None
