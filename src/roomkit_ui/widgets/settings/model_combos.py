"""Model and choice dropdowns shared by the Settings pages."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox


def choice_combo(options: list[tuple[str, str]], saved: str) -> QComboBox:
    combo = QComboBox()
    for label, value in options:
        combo.addItem(label, value)
    combo.setCurrentIndex(max(combo.findData(saved), 0))
    return combo


def select_model(combo: QComboBox, model_id: str, label: str | None = None) -> None:
    """Select *model_id* in a fixed model dropdown.

    A saved id the lineup does not carry (a retired model, a hand-pinned
    one) is inserted at the top, shown as *label* when given, and stays
    selected — falling back to the first item would silently change what
    the next session runs.
    """
    if not model_id:
        return
    idx = combo.findData(model_id)
    if idx < 0:
        combo.insertItem(0, label or model_id, model_id)
        idx = 0
    combo.setCurrentIndex(idx)


def populate_editable_models(
    combo: QComboBox, options: list[tuple[str, str]], current: str
) -> None:
    """Fill an editable model combo: ids as text, the catalog name as tooltip.

    The text doubles as free input (any id the API takes), so it must be the
    id itself; a saved id the lineup lacks is shown as it was saved.
    """
    for label, model_id in options:
        combo.addItem(model_id, model_id)
        combo.setItemData(combo.count() - 1, label, Qt.ToolTipRole)
    idx = combo.findText(current)
    if idx >= 0:
        combo.setCurrentIndex(idx)
    else:
        combo.setCurrentText(current)
