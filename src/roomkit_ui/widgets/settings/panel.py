"""Settings dialog with vertical tab navigation."""

from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from roomkit_ui.settings import load_settings, save_settings
from roomkit_ui.theme import colors
from roomkit_ui.widgets.settings.about_page import _AboutPage
from roomkit_ui.widgets.settings.ai_page import _AIPage
from roomkit_ui.widgets.settings.attitudes_page import _AttitudesPage
from roomkit_ui.widgets.settings.dictation_page import _DictationPage
from roomkit_ui.widgets.settings.general_page import _GeneralPage
from roomkit_ui.widgets.settings.mcp_page import _MCPPage
from roomkit_ui.widgets.settings.models_page import _ModelsPage
from roomkit_ui.widgets.settings.skills import _SkillsPage


class SettingsPanel(QDialog):
    """Modal settings dialog with vertical tab navigation."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setFixedSize(880, 680)
        self.setModal(True)

        settings = load_settings()
        c = colors()

        # ── Sidebar ──
        self._sidebar = QListWidget()
        self._sidebar.setFixedWidth(150)
        self._sidebar.setFrameShape(QListWidget.NoFrame)
        self._sidebar.setStyleSheet(
            f"QListWidget {{ background: transparent; border: none; outline: none; }}"
            f"QListWidget::item {{"
            f"  padding: 10px 14px; border-radius: 8px; color: {c['TEXT_SECONDARY']};"
            f"  font-size: 13px; font-weight: 500;"
            f"}}"
            f"QListWidget::item:selected {{"
            f"  background-color: {c['BG_TERTIARY']}; color: {c['TEXT_PRIMARY']};"
            f"}}"
            f"QListWidget::item:hover:!selected {{"
            f"  background-color: rgba(142, 142, 147, 0.12);"
            f"}}"
        )

        for label in (
            "General",
            "AI Provider",
            "Attitudes",
            "Dictation",
            "AI Models",
            "Skills",
            "MCP Servers",
            "About",
        ):
            item = QListWidgetItem(label)
            item.setSizeHint(item.sizeHint().expandedTo(QSize(0, 38)))
            self._sidebar.addItem(item)

        # ── Pages ──
        self._stack = QStackedWidget()
        self._general = _GeneralPage(settings)
        self._ai = _AIPage(settings)
        self._attitudes = _AttitudesPage(settings)
        self._dictation = _DictationPage(settings)
        self._models = _ModelsPage(settings)
        self._skills = _SkillsPage(settings)
        self._mcp = _MCPPage(settings)
        self._about = _AboutPage()
        self._pages = (
            self._general,
            self._ai,
            self._attitudes,
            self._dictation,
            self._models,
            self._skills,
            self._mcp,
            self._about,
        )

        # Populate the AI tab's attitude combo from the attitudes page
        self._ai.populate_attitude_combo(self._attitudes.all_attitude_names())
        for page in self._pages:
            scroll = QScrollArea()
            scroll.setWidget(page)
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QScrollArea.NoFrame)
            scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
            self._stack.addWidget(scroll)

        self._sidebar.currentRowChanged.connect(self._on_tab_changed)
        self._sidebar.setCurrentRow(0)

        # ── Layout ──
        content = QHBoxLayout()
        content.setSpacing(0)
        content.addWidget(self._sidebar)

        # Vertical separator
        sep = QWidget()
        sep.setFixedWidth(1)
        sep.setStyleSheet(f"background-color: {c['SEPARATOR']};")
        content.addWidget(sep)

        right = QVBoxLayout()
        right.setContentsMargins(20, 16, 20, 16)
        right.setSpacing(12)
        right.addWidget(self._stack, 1)
        content.addLayout(right, 1)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addLayout(content)

    _AI_TAB = 1
    _ATTITUDES_TAB = 2
    _DICTATION_TAB = 3
    _SKILLS_TAB = 5

    def _on_tab_changed(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        if index == self._AI_TAB:
            self._ai.refresh_vc_model_combos()
            self._ai.populate_attitude_combo(self._attitudes.all_attitude_names())
        elif index == self._DICTATION_TAB:
            self._dictation.refresh_model_combo()
        elif index == self._SKILLS_TAB:
            self._skills._refresh_skills()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._save()
        super().closeEvent(event)

    def _save(self) -> None:
        from roomkit_ui.theme import get_stylesheet

        # Collect settings from each page that has them
        settings: dict = {}
        for page in self._pages:
            if hasattr(page, "get_settings"):
                settings.update(page.get_settings())

        # Merge API keys: prefer non-empty from any source
        settings["openai_api_key"] = (
            settings.pop("_rt_openai_key", "")
            or settings.pop("_vc_openai_key", "")
            or settings.pop("_dict_openai_key", "")
        )
        settings["api_key"] = settings.pop("_rt_gemini_key", "") or settings.pop(
            "_vc_gemini_key", ""
        )
        settings["deepgram_api_key"] = settings.pop("_vc_deepgram_key", "") or settings.pop(
            "_dict_deepgram_key", ""
        )

        save_settings(settings)

        # Apply the new theme stylesheet immediately
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(get_stylesheet(settings["theme"]))
