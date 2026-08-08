"""Provider combos that show which backends this install actually carries.

A backend the install lacks stays selectable: the setting may have been made on
another machine, and removing the entry would leave the user hunting for a
provider that simply is not listed.  Instead the item says it is missing and
its tooltip carries the command that installs it.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QComboBox

from roomkit_ui.features import unavailable_reason
from roomkit_ui.theme import colors


def populate_provider_combo(
    combo: QComboBox,
    entries: list[tuple[str, str]],
    feature_map: dict[str, str],
) -> None:
    """Fill ``combo`` from ``(label, provider_id)`` pairs, flagging what is missing.

    ``feature_map`` maps a provider id to a key in ``roomkit_ui.features``; ids
    absent from it need nothing beyond the core install.
    """
    muted = QBrush(QColor(colors()["TEXT_SECONDARY"]))
    for label, value in entries:
        feature = feature_map.get(value)
        reason = unavailable_reason(feature) if feature else None
        if reason is None:
            combo.addItem(label)
            continue
        combo.addItem(f"{label} — not installed")
        index = combo.count() - 1
        combo.setItemData(index, reason, Qt.ToolTipRole)
        combo.setItemData(index, muted, Qt.ForegroundRole)
