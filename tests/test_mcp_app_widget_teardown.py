"""An MCP App widget releases its web page before its profile.

Runs in a child interpreter: QtWebEngine starts Chromium, which must not
share the test process, and a machine that cannot start it skips rather
than fails.
"""

import subprocess
import sys

import pytest

pytest.importorskip("PySide6.QtWebEngineWidgets")

_SCRIPT = """
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QTWEBENGINE_DISABLE_SANDBOX"] = "1"
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--disable-gpu"
from PySide6.QtCore import QTimer, qInstallMessageHandler
from PySide6.QtWidgets import QApplication, QWidget

seen = []
qInstallMessageHandler(lambda mode, ctx, msg: seen.append(msg))
app = QApplication([])
from roomkit_ui.widgets.mcp_app_widget import MCPAppWidget

holder = QWidget()
widget = MCPAppWidget("tool", "server", holder)
print("children:", ",".join(type(c).__name__ for c in widget.children()), flush=True)
# Deleted with its parent, the way a cleared chat drops it: no override runs.
holder.deleteLater()
QTimer.singleShot(500, app.quit)
app.exec()
print("released:", any("Release of profile requested" in m for m in seen), flush=True)
"""


def test_the_profile_outlives_its_page_on_teardown():
    proc = subprocess.run(
        [sys.executable, "-c", _SCRIPT], capture_output=True, text=True, timeout=60
    )
    lines = dict(
        line.split(": ", 1)
        for line in proc.stdout.splitlines()
        if line.startswith(("children", "released"))
    )
    if "children" not in lines:
        pytest.skip(f"QtWebEngine cannot start here: {proc.stderr[-300:]}")

    children = lines["children"].split(",")
    # Children are deleted in the order they were added.
    assert children.index("QWebEngineProfile") > children.index("AppPage")
    assert children.index("QWebEngineProfile") > children.index("QWebEngineView")
    assert lines.get("released") == "False"
