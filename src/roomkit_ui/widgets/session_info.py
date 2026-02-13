"""Collapsible session info bar showing model and tool details."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from roomkit_ui.theme import colors

_COLLAPSED_HEIGHT = 36
_MAX_EXPANDED_HEIGHT = 400
_ANIM_INTERVAL = 16  # ms (~60 fps)
_ANIM_DURATION = 200  # ms
_ANIM_STEPS = _ANIM_DURATION // _ANIM_INTERVAL


class SessionInfoBar(QWidget):
    """Compact summary bar that expands to show tool details."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(0)
        self.hide()
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self._expanded = False
        self._target_height = 0
        self._anim_step = 0

        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(_ANIM_INTERVAL)
        self._anim_timer.timeout.connect(self._anim_tick)

        c = colors()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Summary row (always visible) ──
        self._header = QWidget()
        self._header.setFixedHeight(_COLLAPSED_HEIGHT)
        self._header.setCursor(Qt.PointingHandCursor)
        self._header.setStyleSheet(f"background-color: {c['BG_TERTIARY']};")

        header_layout = QHBoxLayout(self._header)
        header_layout.setContentsMargins(12, 0, 12, 0)
        header_layout.setSpacing(0)

        self._summary_label = QLabel()
        self._summary_label.setStyleSheet(
            f"color: {c['ACCENT_BLUE']}; font-size: 12px; background: transparent;"
        )
        header_layout.addWidget(self._summary_label, 1)

        self._chevron = QLabel()
        self._chevron.setFixedWidth(20)
        self._chevron.setAlignment(Qt.AlignCenter)
        self._chevron.setStyleSheet(
            f"color: {c['ACCENT_BLUE']}; font-size: 14px; background: transparent;"
        )
        header_layout.addWidget(self._chevron)

        outer.addWidget(self._header)

        # ── Separator ──
        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background-color: {c['SEPARATOR']};")
        outer.addWidget(sep)

        # ── Tool detail panel (scroll area) ──
        self._detail_area = QScrollArea()
        self._detail_area.setWidgetResizable(True)
        self._detail_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._detail_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._detail_area.setFrameShape(QFrame.NoFrame)
        self._detail_area.setStyleSheet("background: transparent;")
        self._detail_area.hide()

        self._detail_container = QWidget()
        self._detail_container.setStyleSheet(f"background-color: {c['BG_TERTIARY']};")
        self._detail_layout = QVBoxLayout(self._detail_container)
        self._detail_layout.setContentsMargins(12, 4, 12, 8)
        self._detail_layout.setSpacing(2)
        self._detail_area.setWidget(self._detail_container)

        outer.addWidget(self._detail_area, 1)

        # ── Bottom border ──
        border = QWidget()
        border.setFixedHeight(1)
        border.setStyleSheet(f"background-color: {c['SEPARATOR']};")
        outer.addWidget(border)

        self._header.mousePressEvent = lambda _e: self._toggle()  # type: ignore[method-assign]

    # -- public API ----------------------------------------------------------

    def set_session(self, info: dict) -> None:
        """Populate and show the bar with session info."""
        provider = info.get("provider", "")
        model = info.get("model", "")
        tools: list[dict] = info.get("tools", [])
        skills: list[dict] = info.get("skills", [])
        failed: list[str] = info.get("failed_servers", [])

        # Shorten model name for display
        display_model = model.split("/")[-1] if "/" in model else model
        if len(display_model) > 24:
            display_model = display_model[:22] + "\u2026"

        provider_display = provider.capitalize()
        n_tools = len(tools)
        n_skills = len(skills)
        tool_word = "tool" if n_tools == 1 else "tools"
        parts = [f"{provider_display}", display_model, f"{n_tools} {tool_word}"]
        if n_skills:
            skill_word = "skill" if n_skills == 1 else "skills"
            parts.append(f"{n_skills} {skill_word}")
        self._summary_label.setText("  \u2013  ".join(parts))
        self._chevron.setText("\u25be")

        # Build detail list
        self._clear_details()
        c = colors()

        if failed:
            failed_label = QLabel(f"\u26a0  Failed: {', '.join(failed)}")
            failed_label.setWordWrap(True)
            failed_label.setStyleSheet(
                f"color: {c['ACCENT_RED']}; font-size: 12px;"
                f" background: transparent; padding: 2px 0;"
            )
            self._detail_layout.addWidget(failed_label)

        for tool in tools:
            self._add_detail_row(
                "\u2699", tool.get("name", ""), tool.get("description", ""), c
            )

        for skill in skills:
            self._add_detail_row(
                "\u2726", skill.get("name", ""), skill.get("description", ""), c
            )

        self._detail_layout.addStretch()

        # Show bar at collapsed height
        self._expanded = False
        self._detail_area.hide()
        self.setFixedHeight(_COLLAPSED_HEIGHT)
        self.show()

    def _add_detail_row(
        self, icon: str, name: str, desc: str, c: dict
    ) -> None:
        """Add a single tool/skill row to the detail panel."""
        if len(desc) > 80:
            desc = desc[:77] + "..."
        sec_color = c["TEXT_SECONDARY"]
        row = QLabel(
            f"<span style='font-weight:600;'>{icon} {_esc(name)}</span>"
            f"  "
            f"<span style='color:{sec_color};'>{_esc(desc)}</span>"
        )
        row.setTextFormat(Qt.RichText)
        row.setWordWrap(True)
        row.setStyleSheet(
            f"color: {c['TEXT_PRIMARY']}; font-size: 12px;"
            f" background: transparent; padding: 1px 0;"
        )
        self._detail_layout.addWidget(row)

    def clear_session(self) -> None:
        """Hide the bar."""
        self._anim_timer.stop()
        self._expanded = False
        self.setFixedHeight(0)
        self.hide()
        self._detail_area.hide()
        self._clear_details()

    # -- internal ------------------------------------------------------------

    def _toggle(self) -> None:
        if self._expanded:
            self._expanded = False
            self._chevron.setText("\u25be")
            self._animate_to(_COLLAPSED_HEIGHT)
        else:
            self._expanded = True
            self._chevron.setText("\u25b4")
            self._detail_area.show()
            self._animate_to(_MAX_EXPANDED_HEIGHT)

    def _animate_to(self, target: int) -> None:
        self._target_height = target
        self._anim_step = 0
        self._anim_start_height = self.height()
        self._anim_timer.start()

    def _anim_tick(self) -> None:
        self._anim_step += 1
        progress = min(self._anim_step / _ANIM_STEPS, 1.0)
        # Ease-out quadratic
        eased = 1.0 - (1.0 - progress) ** 2
        current = int(
            self._anim_start_height + (self._target_height - self._anim_start_height) * eased
        )
        self.setFixedHeight(current)

        if progress >= 1.0:
            self._anim_timer.stop()
            if not self._expanded:
                self._detail_area.hide()

    def _clear_details(self) -> None:
        while self._detail_layout.count():
            item = self._detail_layout.takeAt(0)
            if item is None:
                continue
            w = item.widget()
            if w:
                w.deleteLater()


def _esc(text: str) -> str:
    """Minimal HTML escaping for rich-text labels."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
