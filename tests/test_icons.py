"""Icons drawn from Heroicons paths: the hang-up handset is placed by hand."""

from PySide6.QtCore import QByteArray, QRectF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

from roomkit_ui.icons import _PATHS, _SVG_TEMPLATE


def _drawn_box(name: str, size: int = 240) -> tuple[float, float, float, float]:
    """The drawn pixels' box, in the icon's 24-unit coordinates."""
    svg = _SVG_TEMPLATE.format(color="#FFFFFF", paths=_PATHS[name])
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(image)
    QSvgRenderer(QByteArray(svg.encode())).render(painter, QRectF(0, 0, size, size))
    painter.end()
    drawn = [
        (x, y) for x in range(size) for y in range(size) if image.pixelColor(x, y).alpha() > 40
    ]
    xs, ys = [x for x, _ in drawn], [y for _, y in drawn]
    unit = 24 / size
    return min(xs) * unit, min(ys) * unit, max(xs) * unit, max(ys) * unit


def test_the_hang_up_handset_is_filled_centred_and_whole(qapp):
    """Before: Heroicons' phone-x-mark, the handset low left and a cross high
    right, sat off centre in the round red button."""
    left, top, right, bottom = _drawn_box("phone-hang-up")

    assert abs((left + right) / 2 - 12) <= 0.5 and abs((top + bottom) / 2 - 12) <= 0.5
    assert left > 0 and top > 0 and right < 24 and bottom < 24  # nothing cut at the edge
    assert right - left > 2 * (bottom - top)  # laid flat
