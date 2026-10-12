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


_HISTORY_SCRIPT = """
import json, os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QTWEBENGINE_DISABLE_SANDBOX"] = "1"
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--disable-gpu"
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
app = QApplication([])
app.setOrganizationName("RoomKitUI-Tests")
app.setApplicationName("RoomKitUI-Tests")
print('started', flush=True)
from roomkit_ui.theme import get_stylesheet
from roomkit_ui.widgets.menus import install_menu_style
app.setStyleSheet(get_stylesheet("dark"))
install_menu_style(app)
from roomkit_ui.widgets.chat_view import ChatView
from roomkit_ui.widgets.mcp_app_server import get_http_server
html = '''<!DOCTYPE html><html><body>Waiting<script>
let notation = '';
const ready = setInterval(() => parent.postMessage(
  {jsonrpc:'2.0', id:'init', method:'ui/initialize'}, '*'), 30);
addEventListener('message', ({data:m}) => {
  if (m.id === 'init') {
    clearInterval(ready);
    parent.postMessage({method:'ui/notifications/initialized'}, '*');
  }
  if (m.method === 'ui/notifications/tool-input') notation=m.params.arguments.notation;
  if (m.method === 'ui/notifications/tool-result') {
    parent.postMessage({id:'screen-data', method:'tools/call',
        params:{name:'get_screen_data', arguments:{view:'dice'}}}, '*');
  }
  if (m.id === 'screen-data') {
    if (m.result.isError) {
      document.body.firstChild.textContent=m.result.content[0].text;
      return;
    }
    document.body.firstChild.textContent=notation+': '+JSON.parse(m.result.content[0].text).total;
    parent.postMessage({id:'auto-roll', method:'tools/call',
        params:{name:'roll_dice', arguments:{}}}, '*');
  }
});
</script></body></html>'''
entry = {'kind':'tool', 'call': {'id':'roll', 'name':'roll_dice',
    'arguments_json':'{"notation":"1d20"}', 'resource_uri':'ui://dice', 'server_name':'Dice'},
    'result':{'call_id':'roll','status':'completed','text':'{"total":15}'}, 'app_html':html}
entry['app_results'] = [{'name':'get_screen_data', 'arguments':{'view':'dice'},
    'result':json.dumps({'result':json.dumps({'total':15})})}]
chat = ChatView()
chat.resize(500,600)
chat.show()
chat.restore([entry])
widget = chat.tool_call('roll')._app
assert widget._view is not None
forwarded = []
widget.tool_call_requested.connect(lambda *args: forwarded.append(args))
passed = False
poll = QTimer()
def read_dom(text):
    global passed
    if passed or text != '1d20: 15': return
    passed = True
    poll.stop()
    assert not forwarded
    paths = list(widget._http_paths)
    assert paths
    assert chat.snapshot() == [entry]
    chat.clear()
    assert all(path not in get_http_server().content_map for path in paths)
    print('restored: 1d20: 15; no tool replay; resources released', flush=True)
    QTimer.singleShot(200, app.quit)
poll.timeout.connect(lambda: widget._page.runJavaScript(
    "document.querySelector('iframe')?.contentDocument?.body?.firstChild?.textContent", read_dom))
poll.start(100)
QTimer.singleShot(15000, app.quit)
app.exec()
assert passed, 'Saved MCP App did not render its original result'
"""


def test_saved_app_renders_original_result_in_webengine_and_releases_content():
    proc = subprocess.run(
        [sys.executable, "-c", _HISTORY_SCRIPT], capture_output=True, text=True, timeout=30
    )
    if "started" not in proc.stdout:
        pytest.skip(f"QtWebEngine cannot start here: {proc.stderr[-300:]}")
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert "restored: 1d20: 15; no tool replay; resources released" in proc.stdout
