# RoomKit UI

PySide6 + qasync desktop voice assistant wrapping the `roomkit` framework.

## Commands

```bash
uv sync                          # Install dependencies
uv sync --extra dev              # Install with dev tools
uv run python -m roomkit_ui         # Run the app
uv run ruff check .              # Lint
uv run ruff format --check .     # Format check
uv run ruff format .             # Auto-format
uv run mypy src/                 # Type check
uv run bandit -r src/ -c pyproject.toml  # Security scan
```

## Architecture

Entry point: `src/roomkit_ui/app.py` → `roomkit_ui.app:main`

```
src/roomkit_ui/
├── app.py           # QApplication + qasync event loop bootstrap
├── engine.py        # Async voice session engine (roomkit ↔ Qt signals)
├── mcp_manager.py   # MCP client manager (stdio, SSE, HTTP transports)
├── mcp_app_bridge.py # MCP Apps JSON-RPC bridge (QWebChannel ↔ iframe)
├── settings.py      # QSettings persistence
├── cleanup.py       # qasync timer/FD cleanup after MCP disconnect
├── hotkey.py        # Global hotkey (NSEvent on macOS, pynput fallback)
├── stt_engine.py    # Local STT dictation + text pasting
├── model_manager.py # Local model download & management
├── theme.py         # Dark/Light theme stylesheets
└── widgets/
    ├── main_window.py     # Main window layout
    ├── settings_panel.py  # Tabbed settings dialog
    ├── chat_view.py       # Scrollable chat transcript
    ├── chat_bubble.py     # Markdown chat bubble
    ├── mcp_app_widget.py  # QWebEngineView for MCP App HTML UIs
    ├── vu_meter.py        # Animated ambient glow VU meter
    ├── control_bar.py     # Call button + mic mute + settings
    └── hotkey_button.py   # Interactive hotkey capture widget
```

## Code Style

- Python 3.12+, target in pyproject.toml
- Ruff: `select = ["E", "F", "I", "N", "UP", "B", "SIM"]`, line-length 99
- `SIM105` ignored — try/except/pass used intentionally for Qt signal safety
- `N802` ignored in widget files — Qt method overrides (paintEvent, enterEvent)
- Mypy: `disable_error_code = ["attr-defined"]` for PySide6 dynamic enums

## Gotchas

- `QT_QUICK_BACKEND=software` must be set BEFORE importing PySide6 (see app.py line 16)
- Qt signals in async callbacks: always wrap emit() in try/except — the C++ object may be deleted
- MCP tool schemas: strip `$schema` and `additionalProperties` keys for Gemini compatibility (`_clean_schema()` in mcp_manager.py)
- MCP session retry: if provider rejects MCP tools, retry with built-in tools only
- qasync timer cleanup: after MCP session closes, anyio leaves orphaned 0ms timers → 100% CPU. See `cleanup.py`
- `AudioPipelineConfig`: pass `aec` + `denoiser` here AND `aec` to LocalAudioBackend (both needed)
- `InterruptionConfig`: pass `InterruptionStrategy.DISABLED` explicitly, not `None`
