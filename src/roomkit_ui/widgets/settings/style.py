"""Visual tokens and scoped styles for the native Settings workspace."""

from __future__ import annotations

from PySide6.QtCore import QSettings

from roomkit_ui.theme import get_colors


def settings_colors(theme: str | None = None) -> dict[str, str]:
    if theme is None:
        theme = str(QSettings().value("room/theme", "dark"))
    accent = get_colors(theme)["ACCENT_BRAND"]
    if theme == "light":
        return {
            "surface": "#FFFFFF",
            "sidebar": "#F9F9FB",
            "soft": "#F7F7FA",
            "border": "#E7E7EE",
            "outline": "#C5C5D3",
            "text": "#262633",
            "muted": "#6C6C7E",
            "accent": accent,
            "selected": "#EFEBFA",
            "success": "#216943",
            "success_bg": "#EAF5EE",
            "warning": "#8B6200",
            "warning_bg": "#FBF4E4",
            "error": "#A32B3A",
            "error_bg": "#FCEEF0",
        }
    return {
        "surface": "#201F28",
        "sidebar": "#1A1922",
        "soft": "#282630",
        "border": "#36333F",
        "outline": "#676173",
        "text": "#F0EEF6",
        "muted": "#B0AABD",
        "accent": accent,
        "selected": "#342B4B",
        "success": "#9ADAB1",
        "success_bg": "#263A30",
        "warning": "#E7C980",
        "warning_bg": "#3B3222",
        "error": "#FFA4AD",
        "error_bg": "#432830",
    }


def settings_stylesheet(theme: str) -> str:
    c = settings_colors(theme)
    return f"""
        QDialog#settingsPanel, QDialog#settingsPanel QWidget {{
            background: {c["surface"]}; color: {c["text"]};
        }}
        QDialog#settingsPanel QLabel {{ background: transparent; }}
        QDialog#settingsPanel QWidget#settingsSidebar {{
            background: {c["sidebar"]}; border-right: 1px solid {c["border"]};
        }}
        QDialog#settingsPanel QLabel#settingsBrand {{
            font-size: 25px; font-weight: 600; letter-spacing: -1px;
        }}
        QDialog#settingsPanel QLabel#settingsNavTitle {{
            font-size: 14px; font-weight: 600;
        }}
        QDialog#settingsPanel QListWidget#settingsNavigation {{
            background: {c["sidebar"]}; border: none; outline: none;
            padding: 0 10px; font-size: 13px;
        }}
        QDialog#settingsPanel QListWidget#settingsNavigation::item {{
            border: 1px solid transparent; border-radius: 7px;
            padding: 7px 10px; margin: 1px 0; color: {c["muted"]};
        }}
        QDialog#settingsPanel QListWidget#settingsNavigation::item:selected {{
            background: {c["selected"]}; color: {c["accent"]};
        }}
        QDialog#settingsPanel QListWidget#settingsNavigation::item:hover:enabled {{
            background: {c["soft"]};
        }}
        QDialog#settingsPanel QListWidget#settingsNavigation::item:focus {{
            border-color: {c["accent"]};
        }}
        QDialog#settingsPanel QLabel#settingsNavGroup {{
            color: {c["muted"]}; font-size: 10px; font-weight: 600;
            letter-spacing: 1px; padding: 0 10px;
        }}
        QDialog#settingsPanel QLabel#settingsVersion {{
            color: {c["muted"]}; font-size: 11px; padding: 12px 22px;
        }}
        QDialog#settingsPanel QFrame#settingsToolbar,
        QDialog#settingsPanel QFrame#settingsFooter {{
            border: none; border-bottom: 1px solid {c["border"]};
        }}
        QDialog#settingsPanel QFrame#settingsFooter {{
            border-bottom: none; border-top: 1px solid {c["border"]};
        }}
        QDialog#settingsPanel QLabel#settingsBreadcrumb,
        QDialog#settingsPanel QLabel#settingsSaveHint {{
            color: {c["muted"]}; font-size: 12px;
        }}
        QDialog#settingsPanel QLabel#settingsPageTitle {{
            font-size: 28px; font-weight: 600;
        }}
        QDialog#settingsPanel QLabel#settingsDescription {{
            color: {c["muted"]}; font-size: 13px;
        }}
        QDialog#settingsPanel QLabel#settingsSectionTitle {{
            font-size: 14px; font-weight: 600;
        }}
        QDialog#settingsPanel QLabel#settingsRowTitle {{
            font-size: 14px; font-weight: 500;
        }}
        QDialog#settingsPanel QLabel#settingsChoiceTitle {{
            font-size: 16px; font-weight: 600;
        }}
        QDialog#settingsPanel QLabel#settingsChoiceDescription {{
            font-size: 13px; color: {c["muted"]};
        }}
        QDialog#settingsPanel QFrame#settingsPipelineStep {{
            background: {c["soft"]}; border: 1px solid {c["border"]}; border-radius: 9px;
        }}
        QDialog#settingsPanel QLabel#settingsPipelineCaption {{
            font-size: 10px; color: {c["muted"]};
        }}
        QDialog#settingsPanel QLabel#settingsHint {{
            color: {c["muted"]}; font-size: 12px;
        }}
        QDialog#settingsPanel QLabel#settingsStatus {{
            background: {c["soft"]}; color: {c["muted"]};
            font-size: 11px; padding: 4px 8px; border-radius: 6px;
        }}
        QDialog#settingsPanel QLabel#settingsStatus[tone="success"] {{
            background: {c["success_bg"]}; color: {c["success"]};
        }}
        QDialog#settingsPanel QLabel#settingsStatus[tone="active"] {{
            background: {c["selected"]}; color: {c["accent"]};
        }}
        QDialog#settingsPanel QLabel#settingsStatus[tone="warning"] {{
            background: {c["warning_bg"]}; color: {c["warning"]};
        }}
        QDialog#settingsPanel QFrame#settingsCatalogNotice {{
            background: {c["selected"]}; border: none; border-radius: 9px;
        }}
        QDialog#settingsPanel QLabel#settingsNoticeCopy {{
            color: {c["accent"]}; font-size: 12px;
        }}
        QDialog#settingsPanel QLabel#settingsStatus[tone="error"] {{
            background: {c["error_bg"]}; color: {c["error"]};
        }}
        QDialog#settingsPanel QLabel#settingsError {{
            color: {c["error"]}; font-size: 12px;
        }}
        QDialog#settingsPanel QLabel#settingsFeedback {{
            color: {c["muted"]}; font-size: 12px;
        }}
        QDialog#settingsPanel QLabel#settingsFeedback[tone="success"] {{
            color: {c["success"]};
        }}
        QDialog#settingsPanel QLabel#settingsFeedback[tone="error"] {{
            color: {c["error"]};
        }}
        QDialog#settingsPanel QLabel#settingsFeedback[tone="active"] {{
            color: {c["accent"]};
        }}
        QDialog#settingsPanel QWidget#settingsLibraryItem {{
            background: transparent; border: none;
            border-bottom: 1px solid {c["border"]};
        }}
        QDialog#settingsPanel QWidget#settingsLibraryItem:focus {{
            border: 1px solid {c["accent"]}; border-radius: 7px;
        }}
        QDialog#settingsPanel QProgressBar#settingsDownloadProgress {{
            background: {c["border"]}; border: none; border-radius: 3px;
        }}
        QDialog#settingsPanel QProgressBar#settingsDownloadProgress::chunk {{
            background: {c["accent"]}; border-radius: 3px;
        }}
        QDialog#settingsPanel QFrame#settingsCard {{
            border: 1px solid {c["border"]}; border-radius: 10px;
        }}
        QDialog#settingsPanel QWidget#settingsRow,
        QDialog#settingsPanel QWidget#settingsSection {{
            background: transparent; border: none;
        }}
        QDialog#settingsPanel QFrame#settingsSeparator {{
            background: {c["border"]}; border: none; max-height: 1px;
        }}
        QDialog#settingsPanel QPushButton {{
            border: 1px solid {c["outline"]}; border-radius: 7px;
            padding: 8px 12px; background: {c["surface"]};
        }}
        QDialog#settingsPanel QPushButton:hover {{ background: {c["soft"]}; }}
        QDialog#settingsPanel QPushButton:focus {{ border-color: {c["accent"]}; }}
        QDialog#settingsPanel QPushButton:disabled {{ color: {c["muted"]}; }}
        QDialog#settingsPanel QLabel#settingsCatalogSymbol {{
            background: {c["soft"]}; color: {c["accent"]};
            border: 1px solid {c["border"]}; border-radius: 9px;
            font-size: 16px; font-weight: 600;
        }}
        QDialog#settingsPanel QFrame#settingsCatalogRow {{
            background: transparent; border: none;
        }}
        QDialog#settingsPanel QFrame#settingsCatalogRow[divider="true"] {{
            border-bottom: 1px solid {c["border"]};
        }}
        QDialog#settingsPanel QPushButton#settingsPrimary {{
            background: {c["accent"]}; color: {c["surface"]}; border-color: {c["accent"]};
        }}
        QDialog#settingsPanel QPushButton#settingsRemoveEntry {{
            background: transparent; border: 1px solid transparent;
            color: {c["muted"]}; font-size: 18px; padding: 3px 8px;
        }}
        QDialog#settingsPanel QPushButton#settingsRemoveEntry:hover,
        QDialog#settingsPanel QPushButton#settingsRemoveEntry:focus {{
            color: {c["error"]}; border-color: {c["error"]};
        }}
        QDialog#settingsPanel QPushButton#settingsDanger {{
            color: {c["error"]}; border-color: {c["error"]};
        }}
        QDialog#settingsPanel QPushButton#settingsDanger:hover {{
            background: {c["error_bg"]};
        }}
        QDialog#settingsPanel QPushButton#settingsLink {{
            background: transparent; color: {c["accent"]}; border: 1px solid transparent;
            padding: 6px 8px; font-size: 12px;
        }}
        QDialog#settingsPanel QPushButton#settingsLink:focus {{
            border-color: {c["accent"]};
        }}
        QDialog#settingsPanel QPushButton#settingsDisclosure {{
            text-align: left; background: {c["soft"]}; padding: 12px 14px;
            font-size: 13px; font-weight: 500; border-color: {c["border"]};
        }}
        QDialog#settingsPanel QPushButton#settingsDisclosure:focus {{
            border-color: {c["accent"]};
        }}
        QDialog#settingsPanel QLineEdit, QDialog#settingsPanel QTextEdit,
        QDialog#settingsPanel QComboBox {{
            border: 1px solid {c["outline"]}; border-radius: 7px;
            background: {c["soft"]}; padding: 8px 12px; color: {c["text"]};
        }}
        /* Size the numeric field itself; its internal editor must not get
           a second border/padding or a font taller than the native frame. */
        QDialog#settingsPanel QAbstractSpinBox {{
            border: 1px solid {c["outline"]}; border-radius: 7px;
            background: {c["soft"]}; padding: 8px 12px; color: {c["text"]};
            font-size: 14px; min-height: 1.25em;
        }}
        QDialog#settingsPanel QAbstractSpinBox QLineEdit {{
            border: none; padding: 0; background: transparent;
        }}
        QDialog#settingsPanel QAbstractSpinBox:focus {{ border-color: {c["accent"]}; }}
        QDialog#settingsPanel QComboBox:disabled, QDialog#settingsPanel QLineEdit:disabled {{
            color: {c["muted"]}; border-color: {c["border"]};
        }}
        /* macOS menu frames follow the OS appearance; use a themed list popup. */
        QDialog#settingsPanel QComboBox {{ combobox-popup: 0; }}
        QDialog#settingsPanel QComboBox QAbstractItemView {{
            background: {c["surface"]}; color: {c["text"]};
            border: 1px solid {c["outline"]}; border-radius: 7px;
            selection-background-color: {c["selected"]}; selection-color: {c["accent"]};
            outline: none; padding: 4px;
        }}
        QDialog#settingsPanel QComboBox QAbstractItemView::item {{
            padding: 6px 10px; min-height: 22px;
        }}
        QDialog#settingsPanel QLineEdit[settingsFormField="true"],
        QDialog#settingsPanel QComboBox[settingsFormField="true"] {{
            min-height: 1.25em;
        }}
        QDialog#settingsPanel QLineEdit:focus, QDialog#settingsPanel QTextEdit:focus,
        QDialog#settingsPanel QComboBox:focus {{ border-color: {c["accent"]}; }}
        QDialog#settingsPanel QScrollArea {{ background: transparent; border: none; }}
        QDialog#settingsPanel QFrame#settingsTabHeader {{
            border: none; border-bottom: 1px solid {c["border"]};
        }}
        QDialog#settingsPanel QTabBar#settingsTabs::tab {{
            padding: 10px 0 14px 0; margin-right: 24px;
            color: {c["muted"]}; background: transparent;
            border: none; border-bottom: 2px solid transparent;
        }}
        QDialog#settingsPanel QTabBar#settingsTabs::tab:selected {{
            color: {c["accent"]}; border-bottom-color: {c["accent"]}; font-weight: 600;
        }}
        QDialog#settingsPanel QTabBar#settingsTabs::tab:focus {{
            background: {c["selected"]};
        }}
        QDialog#settingsPanel QListWidget#settingsIntegrationList {{
            border: none; background: transparent; outline: none;
        }}
        QDialog#settingsPanel QListWidget#settingsIntegrationList::item {{
            border: 1px solid {c["border"]}; border-radius: 8px;
            margin: 1px 0;
        }}
        QDialog#settingsPanel QListWidget#settingsIntegrationList::item:selected {{
            border-color: {c["accent"]}; background: {c["selected"]};
        }}
        QDialog#settingsPanel QListWidget#settingsIntegrationList::item:focus {{
            border: 2px solid {c["accent"]};
        }}
        QDialog#settingsPanel QListWidget#settingsSearchResults {{
            border: none; background: transparent; outline: none;
        }}
        QDialog#settingsPanel QListWidget#settingsSearchResults::item {{
            border: 1px solid {c["border"]}; border-radius: 8px;
            padding: 14px; margin-bottom: 8px;
        }}
        QDialog#settingsPanel QListWidget#settingsSearchResults::item:selected {{
            background: {c["selected"]}; color: {c["accent"]};
            border-color: {c["accent"]};
        }}
        QDialog#settingsPanel QLabel#settingsSearchNotice {{
            background: {c["selected"]}; color: {c["accent"]}; font-size: 12px;
        }}
        QDialog#settingsPanel QWidget[settingsSearchHit="true"],
        QDialog#settingsPanel QWidget#settingsLibraryItem[settingsSearchHit="true"] {{
            border: 2px solid {c["accent"]}; border-radius: 7px;
        }}
    """
