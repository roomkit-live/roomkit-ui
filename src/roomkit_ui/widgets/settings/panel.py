"""Settings dialog with vertical tab navigation."""

from __future__ import annotations

from functools import partial

from PySide6.QtCore import QSize
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLineEdit,
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
from roomkit_ui.widgets.settings.audio_debug_page import _AudioDebugPage
from roomkit_ui.widgets.settings.cli_tools_page import _CliToolsPage
from roomkit_ui.widgets.settings.dictation_page import _DictationPage
from roomkit_ui.widgets.settings.general_page import _GeneralPage
from roomkit_ui.widgets.settings.mcp_page import _MCPPage
from roomkit_ui.widgets.settings.models_page import _ModelsPage
from roomkit_ui.widgets.settings.skills import _SkillsPage
from roomkit_ui.widgets.settings.speakers_page import _SpeakersPage
from roomkit_ui.widgets.settings.telemetry_page import _TelemetryPage
from roomkit_ui.widgets.settings.wakeword_page import _WakeWordPage


def _mirror_text(fields: list[QLineEdit], text: str) -> None:
    """Copy a user edit to the other fields.  setText() emits no textEdited,
    so mirroring never loops; the edited field is skipped so its cursor stays.
    """
    for field in fields:
        if field.text() != text:
            field.setText(text)


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
            "Speakers",
            "Dictation",
            "Wake Word",
            "AI Models",
            "Skills",
            "MCP Servers",
            "CLI Tools",
            "Audio Debug",
            "Telemetry",
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
        self._speakers = _SpeakersPage(settings)
        self._dictation = _DictationPage(settings)
        self._wakeword = _WakeWordPage(settings)
        self._models = _ModelsPage(settings)
        self._skills = _SkillsPage(settings)
        self._mcp = _MCPPage(settings)
        self._cli_tools = _CliToolsPage(settings)
        self._audio_debug = _AudioDebugPage(settings)
        self._telemetry = _TelemetryPage(settings)
        self._about = _AboutPage()
        self._pages = (
            self._general,
            self._ai,
            self._attitudes,
            self._speakers,
            self._dictation,
            self._wakeword,
            self._models,
            self._skills,
            self._mcp,
            self._cli_tools,
            self._audio_debug,
            self._telemetry,
            self._about,
        )

        # Populate the AI tab's attitude combo from the attitudes page
        self._ai.populate_attitude_combo(self._attitudes.all_attitude_names())
        self._link_api_key_fields()
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
    _SPEAKERS_TAB = 3
    _DICTATION_TAB = 4
    _WAKEWORD_TAB = 5
    _SKILLS_TAB = 7
    _AUDIO_DEBUG_TAB = 10

    def _link_api_key_fields(self) -> None:
        """Mirror each shared API key across every tab that edits it.

        One key shows up on several tabs (realtime, voice channel,
        dictation), each copy loaded with the saved value.  Left apart,
        the save had to pick one: a new key typed on the Dictation tab lost
        to the untouched realtime copy, and a cleared key came back.
        Mirrored, the copies always hold the same value.
        """
        groups = self._ai.api_key_fields()
        groups["openai_api_key"].append(self._dictation.openai_api_key)
        groups["deepgram_api_key"].append(self._dictation.deepgram_api_key)
        for fields in groups.values():
            for field in fields:
                field.textEdited.connect(partial(_mirror_text, fields))

    def _on_tab_changed(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        if index == self._AI_TAB:
            self._ai.refresh_vc_model_combos()
            self._ai.populate_attitude_combo(self._attitudes.all_attitude_names())
        elif index == self._DICTATION_TAB:
            self._dictation.refresh_model_combo()
        elif index == self._WAKEWORD_TAB:
            self._wakeword.refresh()
        elif index == self._SKILLS_TAB:
            self._skills._refresh_skills()
        elif index == self._AUDIO_DEBUG_TAB:
            self._audio_debug.refresh_files()

    def done(self, result: int) -> None:
        # Every way out funnels through done(): Esc and reject() call it
        # directly, and the title-bar close reaches it via reject().  A
        # closeEvent hook would miss Esc — QDialog never sends a QCloseEvent
        # for it — and the user's changes would be discarded.
        self._save()
        super().done(result)

    def _save(self) -> None:
        from roomkit_ui.theme import get_stylesheet

        # Collect settings from each page that has them
        settings: dict = {}
        for page in self._pages:
            if hasattr(page, "get_settings"):
                settings.update(page.get_settings())

        # The copies of a shared key are mirrored (_link_api_key_fields), so
        # any one of them is the key — an emptied one included.  Pop every
        # temp copy all the same: a leftover would be persisted in plaintext
        # by save_settings().
        def merge_key(*temp_names: str) -> str:
            values: list[str] = [settings.pop(name, "") for name in temp_names]
            return values[0]

        settings["openai_api_key"] = merge_key(
            "_rt_openai_key", "_vc_openai_key", "_dict_openai_key"
        )
        settings["api_key"] = merge_key("_rt_gemini_key", "_vc_gemini_key")
        settings["deepgram_api_key"] = merge_key(
            "_rt_deepgram_key", "_vc_deepgram_key", "_dict_deepgram_key"
        )
        # The VC TTS page writes elevenlabs_api_key directly; the realtime
        # copy mirrors it.
        settings.pop("_rt_elevenlabs_key", None)

        save_settings(settings)

        # Apply the new theme stylesheet immediately
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(get_stylesheet(settings["theme"]))
