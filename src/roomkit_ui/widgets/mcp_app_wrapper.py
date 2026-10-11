"""The page hosting an MCP App: QWebChannel bridge plus the app's iframe.

``WRAPPER_HTML.format(app_url=..., bg_color=...)``: literal braces are
doubled.
"""

WRAPPER_HTML = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * {{ margin: 0; padding: 0; }}
  html, body {{ width: 100%; height: 100%; overflow: hidden;
                background: {bg_color}; }}
  iframe {{ width: 100%; height: 100%; border: none; box-sizing: border-box; }}
</style>
<script src="qrc:///qtwebchannel/qwebchannel.js"></script>
</head>
<body>
<iframe id="app" src="{app_url}"></iframe>
<script>
(function() {{
    "use strict";
    var iframe = document.getElementById("app");

    new QWebChannel(qt.webChannelTransport, function(channel) {{
        var bridge = channel.objects.bridge;
        console.log("[mcp-bridge] QWebChannel connected");

        // iframe -> Python: forward postMessage to bridge
        window.addEventListener("message", function(event) {{
            if (event.source === iframe.contentWindow) {{
                var json = (typeof event.data === "string")
                    ? event.data : JSON.stringify(event.data);
                bridge.receiveMessage(json);
            }}
        }});

        // Python -> iframe: forward bridge messages to iframe
        bridge.messageToApp.connect(function(jsonStr) {{
            try {{
                var data = JSON.parse(jsonStr);
                iframe.contentWindow.postMessage(data, "*");
            }} catch(e) {{
                console.error("[mcp-bridge] bad JSON from host", e);
            }}
        }});

        // Measure actual rendered content height in the iframe and
        // report it so the host widget can fit tightly around the content.
        var lastH = 0, stable = 0;
        function measureHeight() {{
            try {{
                var doc = iframe.contentDocument;
                if (!doc || !doc.body) return;
                var h = doc.body.scrollHeight;
                if (h > 50 && Math.abs(h - lastH) > 10) {{
                    lastH = h;
                    stable = 0;
                    bridge.receiveMessage(JSON.stringify({{
                        method: "ui/notifications/size-changed",
                        params: {{width: iframe.clientWidth, height: h}}
                    }}));
                }} else {{
                    stable++;
                    if (stable > 20) clearInterval(htid);
                }}
            }} catch(e) {{}}
        }}
        var htid = setInterval(measureHeight, 500);
        iframe.addEventListener("load", function() {{
            setTimeout(measureHeight, 300);
        }});
    }});
}})();
</script>
</body>
</html>
"""
