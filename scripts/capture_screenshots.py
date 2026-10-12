"""Capture real widgets with demo content, isolated settings, no devices or network.

Run with the project's Python: python scripts/capture_screenshots.py
The images document the current checkout, not necessarily the latest stable release.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("assets/screenshots"))
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("QT_SCALE_FACTOR", "2")

    import shiboken6
    from PySide6.QtCore import QSettings
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from roomkit_ui.conversations import Conversation
    from roomkit_ui.engine_state import EngineState
    from roomkit_ui.images import ImageAttachment
    from roomkit_ui.paths import data_dir
    from roomkit_ui.secret_store import SecretStore, set_secret_store_for_tests
    from roomkit_ui.settings import load_settings, save_settings
    from roomkit_ui.theme_live import apply_theme
    from roomkit_ui.tool_events import ToolCall, ToolResult
    from roomkit_ui.widgets.main_window import MainWindow
    from roomkit_ui.widgets.settings.panel import SettingsPanel

    app = QApplication([])
    app.setOrganizationName("RoomKit-Screenshot-Demo")
    app.setApplicationName("RoomKit-Screenshot-Demo")
    set_secret_store_for_tests(SecretStore(keyring_backend=None))

    def capture(widget, name):
        app.processEvents()
        QTest.qWait(350)
        if focused := app.focusWidget():
            focused.clearFocus()
        app.processEvents()
        assert widget.grab().save(str(output / f"{name}.png"))
        print(f"Captured {name}", flush=True)

    # Original vector sketch: a sample image attachment, not a generated app UI.
    svg = b"""<svg xmlns="http://www.w3.org/2000/svg"
      width="640" height="340" viewBox="0 0 640 340">
    <rect width="640" height="340" rx="24" fill="#e8efe8"/>
    <path d="M0 280 Q130 200 250 280 T640 230 V340 H0" fill="#c0d4c6"/>
    <path d="M65 230 L175 60 L290 230" fill="#8eafa3"/>
    <path d="M200 230 L350 30 L510 230" fill="#688f82"/>
    <path d="M305 90 L350 30 L398 92 L367 78 L342 92 L327 80" fill="#fafaf3"/>
    <path d="M65 290 Q140 235 230 280 T410 267 Q490 245 520 160" stroke="#b37951"
      stroke-width="7" fill="none" stroke-linecap="round" stroke-dasharray="1 17"/>
    <circle cx="65" cy="290" r="9" fill="#6650a4"/><circle cx="520" cy="160" r="9" fill="#6650a4"/>
    <text x="400" y="58" font-family="sans-serif" font-size="22" fill="#254237">WEEKEND WALK</text>
    <text x="43" y="325" font-family="sans-serif" font-size="18" fill="#254237">Start</text>
    <text x="495" y="141" font-family="sans-serif" font-size="18" fill="#254237">Lookout</text>
    </svg>"""
    sketch = QImage(640, 340, QImage.Format_RGB32)
    painter = QPainter(sketch)
    QSvgRenderer(svg).render(painter)
    painter.end()
    attachment = ImageAttachment.from_image(sketch, "weekend-sketch.png")

    with TemporaryDirectory(prefix="roomkit-screenshots-") as temporary:
        QSettings.setDefaultFormat(QSettings.IniFormat)
        QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, temporary)
        save_settings(
            {
                "conversation_mode": "voice_channel",
                "vc_llm_provider": "anthropic",
                "anthropic_api_key": "screenshot-demo-not-a-key",
                "stt_provider": "local",
                "stt_model": "kroko-streaming-fr",
                "conversation_memory": False,
                "mcp_servers": json.dumps(
                    [
                        {
                            "id": "demo-workspace",
                            "name": "Workspace",
                            "transport": "streamable_http",
                            "url": "https://mcp.example.com",
                            "auth": "bearer",
                            "headers": "Authorization: Bearer screenshot-demo-not-a-token",
                        }
                    ]
                ),
            }
        )
        # Conversation constructors and model/file panels must never read the
        # user's conversation database or display their personal recordings.
        with ExitStack() as isolated:
            # Cover both the canonical helper and aliases imported by panels.
            for name, module in list(sys.modules.items()):
                if name.startswith("roomkit_ui") and getattr(module, "data_dir", None) is data_dir:
                    isolated.enter_context(
                        patch.object(module, "data_dir", return_value=Path(temporary))
                    )
            for theme in ("dark", "light"):
                apply_theme(theme)
                window = MainWindow()
                window.resize(420, 740)
                window.show()
                capture(window, f"home-{theme}")

                window._chat.add_image_message(
                    "A quiet afternoon, based on this sketch?", (attachment,)
                )
                window._chat.add_text_reply(
                    "Make the lookout your only destination.\n\n"
                    "**Start slow.** Follow the lower trail and stop for a picnic.\n\n"
                    "**Take in the view.** Leave enough time to return before sunset.",
                    True,
                )
                window._chat.finish_text_turn()
                window._header.set_conversation("A little time outside")
                capture(window, f"conversation-{theme}")

                drawer = window._history.drawer
                drawer.set_conversations(
                    [
                        Conversation(id="demo-walk", title="A little time outside"),
                        Conversation(id="demo-dinner", title="Something good for dinner"),
                        Conversation(id="demo-story", title="An idea for a short story"),
                        Conversation(id="demo-project", title="The next step for my project"),
                    ],
                    "demo-walk",
                )
                drawer.present()
                capture(window, f"history-{theme}")
                drawer.dismiss(immediate=True)

                window._chat.clear()
                window._on_state_changed(EngineState.ACTIVE)
                window._idle_hangup.stop()
                window._chat.add_transcription(
                    "Can we make a plan for this afternoon?", "user", True
                )
                window._chat.add_transcription(
                    "Of course. A walk, a good coffee, and no rush?", "assistant", True
                )
                window._chat.add_transcription("Perfect. What's the weather like?", "user", True)
                call = ToolCall("demo-weather", "check_weather", '{"city":"Montréal"}')
                window._chat.add_tool_call(call)
                window._chat.finish_tool_call(ToolResult(call.id, "completed", "Sunny, 18 °C"))
                window._chat.add_transcription(
                    "Sunny and 18 °C. A good day for the long way home.", "assistant", True
                )
                for bubble in window._chat._bubbles():
                    while bubble._stream_timer.isActive():
                        bubble._stream_tick()
                window._vu.set_speaker_level(0.45)
                capture(window, f"live-{theme}")
                window._vu.stop()
                shiboken6.delete(window)

                panel = SettingsPanel()
                panel.resize(1120, 820)
                panel.show()
                panel._sidebar.select_page("conversation")
                capture(panel, f"settings-{theme}")
                panel._sidebar.select_page("integrations")
                mcp = panel._page_widgets["integrations"].mcp
                mcp._show_edit(0)
                app.processEvents()
                panel._scrolls["integrations"].ensureWidgetVisible(mcp._auth_hint, 0, 100)
                capture(panel, f"authentication-{theme}")
                shiboken6.delete(panel)
        assert load_settings()["anthropic_api_key"] == "screenshot-demo-not-a-key"
    print(f"Demo screenshots saved to {output}. No microphone, camera or provider was opened.")


if __name__ == "__main__":
    main()
