"""Plain checkboxes and number fields in Settings, drawn like the rest of it."""

import shiboken6
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QSpinBox,
    QStyle,
    QStyleOptionSpinBox,
    QVBoxLayout,
)

import roomkit_ui.theme as theme_mod
from roomkit_ui.widgets.settings.style import settings_colors, settings_stylesheet


def _dialog(monkeypatch, tmp_path, *widgets):
    monkeypatch.setattr(theme_mod, "data_dir", lambda: tmp_path)
    dialog = QDialog()
    dialog.setObjectName("settingsPanel")
    dialog.setStyleSheet(settings_stylesheet("dark"))
    layout = QVBoxLayout(dialog)
    for widget in widgets:
        layout.addWidget(widget)
    dialog.resize(420, 160)
    dialog.show()
    return dialog


def _close(color: QColor, hex_color: str) -> bool:
    pairs = zip(color.getRgb()[:3], QColor(hex_color).getRgb()[:3], strict=True)
    return all(abs(a - b) <= 12 for a, b in pairs)


def test_a_plain_checkbox_is_the_settings_switch_drawn_once(qapp, monkeypatch, tmp_path):
    box = QCheckBox("Stream text")
    box.setChecked(True)
    dialog = _dialog(monkeypatch, tmp_path, box)
    qapp.processEvents()
    try:
        c = settings_colors("dark")
        image = box.grab().toImage()
        middle = box.height() // 2
        # The track, in the accent, where the indicator sits...
        assert _close(image.pixelColor(8, middle), c["accent"])
        # ...and nothing past the label: a stylesheet image on the widget
        # itself would paint a second switch in the middle of the row.
        assert _close(image.pixelColor(box.width() - 60, middle), c["surface"])
        assert _close(image.pixelColor(box.width() // 2 + 20, middle), c["surface"])
    finally:
        shiboken6.delete(dialog)


def test_number_field_steppers_sit_inside_its_frame(qapp, monkeypatch, tmp_path):
    spin = QSpinBox()
    spin.setSuffix(" s")
    spin.setValue(15)
    dialog = _dialog(monkeypatch, tmp_path, spin)
    qapp.processEvents()
    try:
        option = QStyleOptionSpinBox()
        spin.initStyleOption(option)
        style = spin.style()
        up = style.subControlRect(QStyle.CC_SpinBox, option, QStyle.SC_SpinBoxUp, spin)
        down = style.subControlRect(QStyle.CC_SpinBox, option, QStyle.SC_SpinBoxDown, spin)
        text = style.subControlRect(QStyle.CC_SpinBox, option, QStyle.SC_SpinBoxEditField, spin)
        # Each stepper (its margin included) within the field, clear of the text.
        for button in (up, down):
            assert button.width() > 0 and button.height() > 0
            assert spin.rect().contains(button)
            assert button.left() > text.right()
        assert up.bottom() <= down.top()
    finally:
        shiboken6.delete(dialog)
