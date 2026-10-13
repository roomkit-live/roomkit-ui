"""SVG icon helpers — Heroicons-style outline icons rendered to QIcon."""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

# ---------------------------------------------------------------------------
# Heroicons 24×24 outline SVG paths (MIT-licensed)
# ---------------------------------------------------------------------------

_SVG_TEMPLATE = (
    '<svg xmlns="http://www.w3.org/2000/svg" fill="none" '
    'viewBox="0 0 24 24" stroke-width="1.5" stroke="{color}">'
    "{paths}</svg>"
)

_PATHS = {
    "photo": (
        '<rect x="3" y="3" width="18" height="18" rx="3"/>'
        '<circle cx="8" cy="8" r="1.5"/>'
        '<path stroke-linejoin="round" d="m3 17 5-5 4 4 4-6 5 7"/>'
    ),
    "camera": (
        '<path stroke-linejoin="round" d="M8 5 9.5 3h5L16 5h3a2 2 0 0 1 2 2v12'
        'a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2Z"/>'
        '<circle cx="12" cy="12" r="4"/>'
    ),
    "pencil": (
        '<path stroke-linecap="round" stroke-linejoin="round" '
        'd="m15 5 4 4M4 16 16 4a2.828 2.828 0 0 1 4 4L8 20l-5 1Z"/>'
    ),
    "arrow-up": '<path stroke-linecap="round" stroke-linejoin="round" d="M12 20V4m-7 7 7-7 7 7"/>',
    "sidebar": '<rect x="3" y="4" width="18" height="16" rx="3"/><path d="M9 4v16"/>',
    "x-mark": '<path stroke-linecap="round" d="m6 6 12 12M6 18 18 6"/>',
    "check": '<path stroke-linecap="round" stroke-linejoin="round" d="m5 12 4 4L19 6"/>',
    "chevron-right": '<path stroke-linecap="round" stroke-linejoin="round" d="m9 5 7 7-7 7"/>',
    "chevron-down": '<path stroke-linecap="round" stroke-linejoin="round" d="m5 9 7 7 7-7"/>',
    "plus": '<path stroke-linecap="round" d="M12 5v14M5 12h14"/>',
    "magnifying-glass": (
        '<circle cx="10.5" cy="10.5" r="7.5"/><path stroke-linecap="round" d="m16 16 5 5"/>'
    ),
    "squares-2x2": (
        '<rect x="3" y="3" width="7" height="7" rx="2"/>'
        '<rect x="14" y="3" width="7" height="7" rx="2"/>'
        '<rect x="3" y="14" width="7" height="7" rx="2"/>'
        '<rect x="14" y="14" width="7" height="7" rx="2"/>'
    ),
    "chat-bubble": '<path d="M21 11a8 8 0 0 1-8 8H6l-3 3V11a9 9 0 0 1 18 0Z"/>',
    "user-group": (
        '<circle cx="9" cy="7" r="4"/>'
        '<path d="M2 21v-3a7 7 0 0 1 14 0v3M17 4a4 4 0 0 1 0 7M21 21v-3a7 7 0 0 0-4-5"/>'
    ),
    "bolt": '<path stroke-linejoin="round" d="m13 2-9 12h7l-1 8 10-13h-8l1-7Z"/>',
    "layers": (
        '<path stroke-linejoin="round" d="m12 2 9 5-9 5-9-5 9-5ZM3 12l9 5 9-5M3 17l9 5 9-5"/>'
    ),
    "cube": '<path stroke-linejoin="round" d="m12 2 9 5v10l-9 5-9-5V7l9-5Zm0 10 9-5M3 7l9 5v10"/>',
    "plug": '<path d="M8 3v5M16 3v5M5 8h14v3a7 7 0 0 1-14 0V8ZM12 18v4"/>',
    "command-line": (
        '<rect x="2" y="4" width="20" height="16" rx="3"/><path d="m6 9 3 3-3 3M12 15h5"/>'
    ),
    "waveform": '<path stroke-linecap="round" d="M4 10v4M8 6v12M12 3v18M16 7v10M20 10v4"/>',
    "chart-bar": '<path d="M4 3v18h17M8 17v-5M13 17V8M18 17V4"/>',
    "information-circle": '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7v1"/>',
    "microphone": (
        '<path stroke-linecap="round" stroke-linejoin="round" '
        'd="M12 18.75a6 6 0 0 0 6-6v-1.5m-6 7.5a6 6 0 0 1-6-6v-1.5m6 '
        "7.5v3.75m-3.75 0h7.5M12 15.75a3 3 0 0 1-3-3V4.5a3 3 0 1 1 6 "
        '0v8.25a3 3 0 0 1-3 3Z"/>'
    ),
    "microphone-slash": (
        '<path stroke-linecap="round" stroke-linejoin="round" '
        'd="M12 18.75a6 6 0 0 0 6-6v-1.5m-6 7.5a6 6 0 0 1-6-6v-1.5m6 '
        "7.5v3.75m-3.75 0h7.5M12 15.75a3 3 0 0 1-3-3V4.5a3 3 0 1 1 6 "
        '0v8.25a3 3 0 0 1-3 3Z"/>'
        '<line x1="3" y1="3" x2="21" y2="21" stroke-linecap="round"/>'
    ),
    "cog-6-tooth": (
        '<path stroke-linecap="round" stroke-linejoin="round" '
        'd="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 '
        "1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127"
        ".325.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 0 1 1.37.49l"
        "1.296 2.247a1.125 1.125 0 0 1-.26 1.431l-1.003.827c-.293.241-"
        ".438.613-.43.992a7.723 7.723 0 0 1 0 .255c-.008.378.137.75.43"
        ".991l1.004.827c.424.35.534.955.26 1.43l-1.298 2.247a1.125 1.125"
        " 0 0 1-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47"
        " 6.47 0 0 1-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-"
        ".09.543-.56.94-1.11.94h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-"
        "1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 0 1-.22-.127c-"
        ".325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 0 1-1.369"
        "-.49l-1.297-2.247a1.125 1.125 0 0 1 .26-1.431l1.004-.827c.292-"
        ".24.437-.613.43-.991a6.932 6.932 0 0 1 0-.255c.007-.38-.138-"
        ".751-.43-.992l-1.004-.827a1.125 1.125 0 0 1-.26-1.43l1.297-"
        "2.247a1.125 1.125 0 0 1 1.37-.491l1.216.456c.356.133.751.072 "
        "1.076-.124.072-.044.146-.086.22-.128.332-.183.582-.495.644-.869l"
        '.214-1.28Z"/>'
        '<path stroke-linecap="round" stroke-linejoin="round" '
        'd="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z"/>'
    ),
    "phone": (
        '<path stroke-linecap="round" stroke-linejoin="round" '
        'd="M2.25 6.75c0 8.284 6.716 15 15 15h2.25a2.25 2.25 0 0 0 '
        "2.25-2.25v-1.372c0-.516-.351-.966-.852-1.091l-4.423-1.106c-"
        ".44-.11-.902.055-1.173.417l-.97 1.293c-.282.376-.769.542-1.21"
        ".38a12.035 12.035 0 0 1-7.143-7.143c-.162-.441.004-.928.38-"
        "1.21l1.293-.97c.363-.271.527-.734.417-1.173L6.963 3.102a1.125"
        ' 1.125 0 0 0-1.091-.852H4.5A2.25 2.25 0 0 0 2.25 4.5v2.25Z"/>'
    ),
    "phone-x-mark": (
        '<path stroke-linecap="round" stroke-linejoin="round" '
        'd="M15.75 3.75 18 6m0 0 2.25 2.25M18 6l2.25-2.25M18 6l-2.25 '
        "2.25m-7.5 9.75c-3.75-3.75-5.25-7.5-4.5-9.75L7.5 6.75l2.25 "
        "3-1.5 2.25c1.5 3 3.75 5.25 6.75 6.75l2.25-1.5 3 2.25-1.5 "
        '1.5c-2.25.75-6-1.5-9.75-5.25Z"/>'
    ),
    "stop": (
        '<path stroke-linecap="round" stroke-linejoin="round" '
        'd="M5.25 7.5A2.25 2.25 0 0 1 7.5 5.25h9a2.25 2.25 0 0 1 2.25 '
        "2.25v9a2.25 2.25 0 0 1-2.25 2.25h-9a2.25 2.25 0 0 1-2.25-2.25"
        'v-9Z"/>'
    ),
    "play": (
        '<path stroke-linecap="round" stroke-linejoin="round" '
        'd="M5.25 5.653c0-.856.917-1.398 1.667-.986l11.54 6.347a1.125 '
        "1.125 0 0 1 0 1.972l-11.54 6.347a1.125 1.125 0 0 1-1.667-.986"
        'V5.653Z"/>'
    ),
    "arrow-path": (
        '<path stroke-linecap="round" stroke-linejoin="round" '
        'd="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m'
        "-4.992 0 3.181 3.183a8.25 8.25 0 0 0 13.803-3.7M4.031 9.865"
        'a8.25 8.25 0 0 1 13.803-3.7l3.181 3.182M21.015 4.356v4.992"/>'
    ),
    "trash": (
        '<path stroke-linecap="round" stroke-linejoin="round" '
        'd="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 '
        "1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084"
        "a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 "
        "0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 "
        "0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964"
        " 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667"
        ' 48.667 0 0 0-7.5 0"/>'
    ),
    "arrow-down-tray": (
        '<path stroke-linecap="round" stroke-linejoin="round" '
        'd="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5'
        'M16.5 12 12 16.5m0 0L7.5 12m4.5 4.5V3"/>'
    ),
    "sparkles": (
        '<path stroke-linecap="round" stroke-linejoin="round" '
        'd="M9.813 15.904 9 18.75l-.813-2.846a4.5 4.5 0 0 0-3.09-3.09'
        "L2.25 12l2.846-.813a4.5 4.5 0 0 0 3.09-3.09L9 5.25l.813 "
        "2.846a4.5 4.5 0 0 0 3.09 3.09L15.75 12l-2.846.813a4.5 4.5 "
        "0 0 0-3.09 3.09ZM18.259 8.715 18 9.75l-.259-1.035a3.375 "
        "3.375 0 0 0-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 0 "
        "0 2.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 0 0 2.456 "
        "2.456L21.75 6l-1.035.259a3.375 3.375 0 0 0-2.456 2.456Z"
        "M16.894 20.567 16.5 21.75l-.394-1.183a2.25 2.25 0 0 0-1.423"
        "-1.423L13.5 18.75l1.183-.394a2.25 2.25 0 0 0 1.423-1.423"
        "L16.5 15.75l.394 1.183a2.25 2.25 0 0 0 1.423 1.423l1.183"
        '.394-1.183.394a2.25 2.25 0 0 0-1.423 1.423Z"/>'
    ),
}


def svg_icon(name: str, color: str = "#FFFFFF", size: int = 24) -> QIcon:
    """Render a named Heroicon SVG path to a QIcon at the given size."""
    paths = _PATHS.get(name, "")
    svg = _SVG_TEMPLATE.format(color=color, paths=paths)
    data = QByteArray(svg.encode("utf-8"))
    renderer = QSvgRenderer(data)

    screen = QGuiApplication.primaryScreen()
    ratio = screen.devicePixelRatio() if screen else 1.0
    pixmap = QPixmap(round(size * ratio), round(size * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(QColor(0, 0, 0, 0))  # transparent
    painter = QPainter(pixmap)
    try:
        renderer.render(painter, QRectF(0, 0, size, size))
    finally:
        painter.end()

    return QIcon(pixmap)
