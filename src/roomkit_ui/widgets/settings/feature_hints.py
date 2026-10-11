"""Provider combos that show which backends this install actually carries.

A backend the install lacks stays selectable: the setting may have been made on
another machine, and removing the entry would leave the user hunting for a
provider that simply is not listed.  Instead the item says it is missing, its
tooltip carries the command that installs it, and ``offer_install`` puts the
button that installs it under the combo while it is selected.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QComboBox

from roomkit_ui.features import unavailable_reason
from roomkit_ui.theme import colors
from roomkit_ui.theme_live import bind_theme
from roomkit_ui.widgets.install_offer import InstallOffer


def populate_provider_combo(
    combo: QComboBox,
    entries: list[tuple[str, str]],
    feature_map: dict[str, str],
) -> None:
    """Fill ``combo`` from ``(label, provider_id)`` pairs, flagging what is missing.

    ``feature_map`` maps a provider id to a key in ``roomkit_ui.features``; ids
    absent from it need nothing beyond the core install.
    """
    start = combo.count()
    for label, _value in entries:
        combo.addItem(label)
    refresh_provider_combo(combo, entries, feature_map, offset=start)
    bind_theme(combo, lambda: _refresh_colors(combo), name="provider_colors")


def _refresh_colors(combo: QComboBox) -> None:
    muted = QBrush(QColor(colors()["TEXT_SECONDARY"]))
    for index in range(combo.count()):
        if combo.itemData(index, Qt.ForegroundRole) is not None:
            combo.setItemData(index, muted, Qt.ForegroundRole)


def refresh_provider_combo(
    combo: QComboBox,
    entries: list[tuple[str, str]],
    feature_map: dict[str, str],
    *,
    offset: int = 0,
) -> None:
    """Mark again which of ``entries`` (from item *offset* on) are missing:
    a component installed meanwhile loses its "not installed"."""
    muted = QBrush(QColor(colors()["TEXT_SECONDARY"]))
    for i, (label, value) in enumerate(entries):
        index = offset + i
        feature = feature_map.get(value)
        reason = unavailable_reason(feature) if feature else None
        combo.setItemText(index, label if reason is None else f"{label} — not installed")
        combo.setItemData(index, reason, Qt.ToolTipRole)
        combo.setItemData(index, muted if reason is not None else None, Qt.ForegroundRole)


def offer_install(
    combo: QComboBox,
    entries: list[tuple[str, str]],
    feature_map: dict[str, str],
    *,
    offset: int = 0,
) -> InstallOffer:
    """The line under *combo* that offers to install its choice when it is missing.

    The caller puts it in its layout; it shows only while the selected entry
    (item *offset* on) is not installed, and relabels the combo once it is.
    """
    offer = InstallOffer()

    def follow() -> None:
        i = combo.currentIndex() - offset
        value = entries[i][1] if 0 <= i < len(entries) else ""
        offer.set_feature(feature_map.get(value))

    combo.currentIndexChanged.connect(follow)
    offer.installed.connect(
        lambda _extra: refresh_provider_combo(combo, entries, feature_map, offset=offset)
    )
    follow()
    return offer
