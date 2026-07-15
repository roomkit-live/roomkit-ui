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
├── app.py               # QApplication + qasync event loop bootstrap
├── engine.py            # Engine shell: lifecycle, state machine, cleanup, model cache
├── engine_vc.py         # Voice Channel mode startup (STT → LLM → TTS) — mixin
├── engine_realtime.py   # Realtime mode startup (Gemini Live / OpenAI Realtime) — mixin
├── engine_audio.py      # Pipeline builders: AEC, denoiser, VAD, diarization, recording
├── engine_callbacks.py  # roomkit provider/transport callbacks → Qt signals — mixin
├── engine_tools.py      # Tool dispatch (builtin → MCP), attitudes, end_conversation — mixin
├── hooks.py             # RoomKit hook registration for UI events
├── watchdog.py          # Stalled-session detector (8s silence) + model nudge
├── cleanup.py           # qasync timer/FD cleanup after MCP disconnect
├── builtin_tools.py     # Built-in tools (always available)
├── toolset.py           # Tool grouping (builtin/cli/mcp) + session_info summaries — leaf
├── stt_engine.py        # Local STT dictation + text pasting
├── hotkey.py            # Global hotkey (NSEvent on macOS, pynput fallback)
├── paste.py             # Clipboard copy + paste simulation per platform
├── tray.py              # System tray icon for dictation
├── sounds.py            # Notification sounds for session start/stop
├── speaker_manager.py   # Speaker profile JSON persistence (~/.local/share/roomkit-ui/speakers)
├── enrollment.py        # Speaker embedding recording/extraction (sherpa-onnx)
├── model_manager.py     # Local model catalog + downloads (GitHub LFS resolution)
├── skill_manager.py     # Skill discovery (git / local / ClawHub) + SkillRegistry build
├── clawhub_client.py    # ClawHub skill marketplace API client
├── mcp_manager.py       # MCP client manager (stdio, SSE, HTTP transports)
├── mcp_auth.py          # OAuth2 authentication for MCP HTTP servers
├── mcp_app_bridge.py    # MCP Apps JSON-RPC bridge (QWebChannel ↔ iframe)
├── settings.py          # QSettings persistence (~90 keys)
├── icons.py             # Heroicons SVG rendering
├── theme.py             # Dark/Light theme stylesheets
├── providers/           # LLM provider factories (anthropic, gemini, openai, local) — lazy registry
├── tts/                 # TTS factories (piper, qwen3, neutts, gradium, elevenlabs) — lazy registry
└── widgets/
    ├── main_window.py     # Main window layout + Engine↔UI signal wiring
    ├── control_bar.py     # Call button + mic mute + settings
    ├── chat_view.py       # Scrollable chat transcript
    ├── chat_bubble.py     # Markdown chat bubble
    ├── mcp_app_widget.py  # QWebEngineView for MCP App HTML UIs
    ├── vu_meter.py        # Animated ambient glow VU meter
    ├── session_info.py    # Collapsible session info bar
    ├── hotkey_button.py   # Interactive hotkey capture widget
    ├── dictation_log.py   # Dictation event log window
    └── settings/          # 11-tab settings dialog (general, ai, attitudes, speakers,
                           #  dictation, models, skills/, mcp, audio_debug, telemetry, about)
```

Engine composition: `Engine(CallbackMixin, ToolMixin, RealtimeMixin, VoiceChannelMixin, QObject)` —
mixins hold no state; all attributes live on `Engine`. Docs: `docs/architecture.md`,
`docs/technical.md`, `docs/features.md`, `docs/onboarding.md`.

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
- MCP session retry: if provider rejects MCP tools, retry with `ToolSet.without_mcp`. Trigger on `ToolSet.has_mcp` — never infer "MCP tools exist" from a tool-count comparison, that breaks the moment another source contributes tools
- qasync timer cleanup: after MCP session closes, anyio leaves orphaned 0ms timers → 100% CPU. See `cleanup.py`
- AEC wiring (realtime): pass `aec` to `AudioPipelineConfig` ONLY — `LocalAudioBackend(aec=...)` flags NATIVE_AEC, the pipeline skips its AEC stage and loses the continuous playback reference (roomkit 0.9.0 barge-in fix). Same wiring as roomkit's `examples/realtime_voice_local_gemini.py`. VC mode still passes both.
- No denoiser on the realtime mic path — speech enhancers keep the dominant voice and eat the user's barge-in during doubletalk. Denoisers are VC-mode only.
- With a pipeline VAD (diarization), roomkit hands barge-in authority to the LOCAL VAD and ignores the provider's server-VAD events (`_realtime_speech.py` early-returns) — interruption quality then depends entirely on the local VAD.
- `InterruptionConfig`: pass `InterruptionStrategy.DISABLED` explicitly, not `None`
