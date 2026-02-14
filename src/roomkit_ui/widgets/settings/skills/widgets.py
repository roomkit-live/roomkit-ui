"""Shared UI primitives for the Skills settings page."""

from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QWidgetItem,
)

from roomkit_ui.theme import colors

CARD_WIDTH = 255


# ---------------------------------------------------------------------------
# Flow layout — wraps cards into rows
# ---------------------------------------------------------------------------


class FlowLayout(QLayout):
    """A layout that arranges widgets in a flowing left-to-right, top-to-bottom grid."""

    def __init__(self, parent=None, h_spacing: int = 10, v_spacing: int = 10) -> None:
        super().__init__(parent)
        self.setContentsMargins(0, 0, 0, 0)
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing
        self._items: list[QWidgetItem] = []

    def addItem(self, item):  # noqa: N802
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def hasHeightForWidth(self):  # noqa: N802
        return True

    def heightForWidth(self, width):  # noqa: N802
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect):  # noqa: N802
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self):  # noqa: N802
        return self.minimumSize()

    def minimumSize(self):  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        m = self.contentsMargins()
        effective = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        if not self._items:
            return int(effective.y() - rect.y() + m.bottom())
        avail = effective.width()
        hint_w = self._items[0].sizeHint().width()
        cols = max(1, (avail + self._h_spacing) // (hint_w + self._h_spacing))
        item_w = (avail - (cols - 1) * self._h_spacing) // cols
        x = effective.x()
        y = effective.y()
        row_height = 0
        col = 0
        for item in self._items:
            h = item.sizeHint().height()
            if col >= cols:
                x = effective.x()
                y += row_height + self._v_spacing
                row_height = 0
                col = 0
            if not test_only:
                item.setGeometry(QRect(x, y, item_w, h))
            x += item_w + self._h_spacing
            row_height = max(row_height, h)
            col += 1
        return int(y + row_height - rect.y() + m.bottom())


# ---------------------------------------------------------------------------
# Skill card widget
# ---------------------------------------------------------------------------


class SkillCard(QWidget):
    """A card displaying a single skill in 'my skills' or 'marketplace' mode."""

    def __init__(
        self,
        *,
        name: str,
        description: str,
        source_label: str = "",
        checked: bool = False,
        marketplace: bool = False,
        installed: bool = False,
        downloads: int = 0,
        version: str | None = None,
        slug: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.slug = slug
        self._marketplace = marketplace
        c = colors()

        self.setMinimumWidth(CARD_WIDTH)
        self.setStyleSheet(
            f"SkillCard {{"
            f" background: {c['BG_SECONDARY']};"
            f" border: 1px solid {c['SEPARATOR']};"
            f" border-radius: 10px;"
            f"}}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        # Header row: checkbox (my skills) or just the name (marketplace)
        header = QHBoxLayout()
        header.setSpacing(8)
        if not marketplace:
            self.checkbox = QCheckBox()
            self.checkbox.setChecked(checked)
            header.addWidget(self.checkbox)
        else:
            self.checkbox = None

        name_label = QLabel(name)
        name_label.setStyleSheet(
            f"font-size: 13px; font-weight: 600; color: {c['TEXT_PRIMARY']};"
            " background: transparent;"
        )
        header.addWidget(name_label, 1)
        layout.addLayout(header)

        # Description (2-line clamp)
        if description:
            desc_text = description if len(description) <= 100 else description[:97] + "..."
            desc = QLabel(desc_text)
            desc.setWordWrap(True)
            desc.setMaximumHeight(50)
            desc.setStyleSheet(
                f"font-size: 11px; color: {c['TEXT_SECONDARY']}; background: transparent;"
            )
            layout.addWidget(desc)

        # Footer row
        footer = QHBoxLayout()
        footer.setSpacing(6)

        if marketplace:
            stats_parts: list[str] = []
            if downloads:
                stats_parts.append(f"\u2b07 {format_count(downloads)}")
            if version:
                stats_parts.append(f"v{version}")
            if stats_parts:
                stats = QLabel("  ".join(stats_parts))
                stats.setStyleSheet(
                    f"font-size: 10px; color: {c['TEXT_SECONDARY']}; background: transparent;"
                )
                footer.addWidget(stats)
            footer.addStretch()

            self.action_btn = QPushButton("Installed \u2713" if installed else "Install")
            self.action_btn.setEnabled(not installed)
            self.action_btn.setCursor(Qt.PointingHandCursor)
            self.action_btn.setFixedHeight(26)
            btn_bg = c["ACCENT_GREEN"] if not installed else c["BG_TERTIARY"]
            btn_fg = "#000000" if not installed else c["TEXT_SECONDARY"]
            self.action_btn.setStyleSheet(
                f"QPushButton {{ font-size: 11px; font-weight: 600;"
                f" background: {btn_bg}; color: {btn_fg};"
                f" border: none; border-radius: 6px; padding: 0 12px; }}"
                f"QPushButton:hover {{ opacity: 0.9; }}"
                f"QPushButton:disabled {{ background: {c['BG_TERTIARY']};"
                f" color: {c['TEXT_SECONDARY']}; }}"
            )
            footer.addWidget(self.action_btn)
        else:
            # Source tag badge — color-coded by origin
            if source_label:
                if source_label == "ClawHub":
                    tag_bg = c["ACCENT_BLUE"]
                    tag_fg = "#FFFFFF"
                elif source_label.startswith("git"):
                    tag_bg = c["ACCENT_GREEN"]
                    tag_fg = "#000000"
                else:
                    tag_bg = c["BG_TERTIARY"]
                    tag_fg = c["TEXT_SECONDARY"]
                tag = QLabel(source_label)
                tag.setStyleSheet(
                    f"font-size: 10px; color: {tag_fg};"
                    f" background: {tag_bg};"
                    f" border-radius: 4px; padding: 2px 6px;"
                )
                footer.addWidget(tag)
            footer.addStretch()

            # Uninstall button for ClawHub skills
            if source_label == "ClawHub":
                self.action_btn = QPushButton("Uninstall")
                self.action_btn.setCursor(Qt.PointingHandCursor)
                self.action_btn.setFixedHeight(24)
                self.action_btn.setStyleSheet(
                    f"QPushButton {{ font-size: 10px; font-weight: 600;"
                    f" background: transparent; color: {c['ACCENT_RED']};"
                    f" border: 1px solid {c['ACCENT_RED']}; border-radius: 6px;"
                    f" padding: 0 8px; }}"
                    f"QPushButton:hover {{ background: rgba(255, 69, 58, 0.15); }}"
                )
                footer.addWidget(self.action_btn)
            else:
                self.action_btn = None

        layout.addLayout(footer)

    def sizeHint(self):  # noqa: N802
        h = self.layout().sizeHint().height()
        return QSize(CARD_WIDTH, max(h, 90))


def format_count(n: int) -> str:
    """Format a number for display (e.g. 1500 -> '1.5k')."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


# ---------------------------------------------------------------------------
# Tab toggle (segmented control)
# ---------------------------------------------------------------------------


def make_tab_toggle(
    labels: list[str], on_switch, parent=None
) -> tuple[QWidget, list[QPushButton]]:
    """Create a segmented-control style tab toggle."""
    c = colors()
    container = QWidget(parent)
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)

    buttons: list[QPushButton] = []
    for i, label in enumerate(labels):
        btn = QPushButton(label)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setCheckable(True)
        btn.setChecked(i == 0)
        btn.setFixedHeight(32)
        btn.clicked.connect(lambda _checked, idx=i: on_switch(idx))
        buttons.append(btn)
        layout.addWidget(btn)
    layout.addStretch()

    def _apply_styles(active_idx: int) -> None:
        for j, b in enumerate(buttons):
            b.setChecked(j == active_idx)
            if j == active_idx:
                b.setStyleSheet(
                    f"QPushButton {{ font-size: 13px; font-weight: 600;"
                    f" background: {c['ACCENT_BLUE']}; color: #FFFFFF;"
                    f" border: none; border-radius: 8px; padding: 0 18px; }}"
                )
            else:
                b.setStyleSheet(
                    f"QPushButton {{ font-size: 13px; font-weight: 500;"
                    f" background: {c['BG_SECONDARY']}; color: {c['TEXT_SECONDARY']};"
                    f" border: 1px solid {c['SEPARATOR']}; border-radius: 8px;"
                    f" padding: 0 18px; }}"
                    f"QPushButton:hover {{ background: {c['BG_TERTIARY']}; }}"
                )

    container._apply_styles = _apply_styles  # type: ignore[attr-defined]
    _apply_styles(0)
    return container, buttons
