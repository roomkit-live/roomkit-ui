"""Skills, external servers and local tools share one Settings destination."""

from PySide6.QtWidgets import QWidget

from roomkit_ui.widgets.settings.cli_tools_page import _CliToolsPage
from roomkit_ui.widgets.settings.controls import SettingsTabs, page_layout
from roomkit_ui.widgets.settings.mcp_page import _MCPPage
from roomkit_ui.widgets.settings.skills import _SkillsPage
from roomkit_ui.widgets.settings.tool_search_section import ToolSearchSection


class IntegrationsPage(QWidget):
    def __init__(self, settings: dict, parent=None) -> None:
        super().__init__(parent)
        layout = page_layout(
            self, "Integrations", "Give your assistant the tools and skills it needs."
        )
        self.skills = _SkillsPage(settings)
        self.mcp = _MCPPage(settings)
        self.cli = _CliToolsPage(settings)
        self.tabs = SettingsTabs(
            [
                ("MCP servers", self.mcp),
                ("CLI tools", self.cli),
                ("Skills", self.skills),
            ]
        )
        layout.addWidget(self.tabs)
        # Every tool counts, whatever its source: one setting below the tabs.
        self.tool_search = ToolSearchSection(settings)
        layout.addWidget(self.tool_search)
        layout.addStretch()

    def refresh(self) -> None:
        self.skills._refresh_skills()
        self.mcp.catalog.refresh()
        self.cli.catalog.refresh()

    def reveal_search_target(self, control: str = "") -> None:
        current = self.tabs.bar.currentIndex()
        if current == 2:
            view = 1 if "_marketplace_tab" in control else 2 if "sources" in control else 0
            self.skills.show_view(view)
            self.skills._show_overview()
            self.skills._my_skills_tab.search.clear()
            self.skills._my_skills_tab.availability.setCurrentIndex(0)
            self.skills.sources.search.clear()
        else:
            page = self.mcp if current == 0 else self.cli
            page._show_list()
            page.catalog.search.clear()

    def get_settings(self) -> dict:
        return {
            **self.skills.get_settings(),
            **self.mcp.get_settings(),
            **self.cli.get_settings(),
            **self.tool_search.get_settings(),
        }
