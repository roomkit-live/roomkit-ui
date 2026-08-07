# Technical Reference

> _Generated: 2026-06-11 — re-run /project-review to update_

System context lives in [architecture.md](architecture.md); feature-to-code mapping in
[features.md](features.md); setup steps in [onboarding.md](onboarding.md).

## Technology stack

| Layer | Technology | Version (locked) |
|---|---|---|
| Language | Python | 3.12+ |
| GUI | PySide6 (Qt 6) | 6.11.1 |
| Async/Qt bridge | qasync | 0.28.0 |
| Voice/AI framework | roomkit (extras: realtime-gemini, realtime-openai, realtime-deepgram, realtime-elevenlabs, local-audio, webrtc-aec, sherpa-onnx) | 0.43.0 |
| Tool protocol | mcp | 1.26.0 |
| HTTP | httpx | 0.28.1 |
| Markdown rendering | markdown-it-py | 4.0.0 |
| Global hotkeys | pynput (fallback; NSEvent native on macOS) | 1.8.1 |
| Local inference | sherpa-onnx (via roomkit extra) | 1.13.2 |
| Packaging | hatchling (build), PyInstaller 6 (bundles), uv (env) | — |
| Quality | ruff 0.15, mypy 1.19, bandit 1.9 | — |

## Project structure

```
src/roomkit_ui/
├── app.py               # QApplication + qasync bootstrap, rendering probes, logging
├── engine.py            # Engine shell: lifecycle, state, cleanup, model cache
├── engine_vc.py         # VoiceChannel mode: STT/LLM/TTS builders (mixin)
├── engine_realtime.py   # Realtime mode: Gemini Live, OpenAI, Deepgram Agent, ElevenLabs, Grok (mixin)
├── engine_audio.py      # Pipeline builders: AEC, denoise, VAD, diarization, recording
├── engine_callbacks.py  # Provider/transport callbacks → Qt signals (mixin)
├── engine_tools.py      # Tool dispatch: builtin → MCP, attitudes, end_conversation (mixin)
├── hooks.py             # RoomKit hook registration (transcription, levels, speakers)
├── watchdog.py          # Stalled-session detector + nudge
├── cleanup.py           # qasync/anyio orphaned timer & FD purge
├── settings.py          # QSettings persistence (~90 keys)
├── builtin_tools.py     # Always-available tools (date/time, attitudes, clipboard)
├── stt_engine.py        # Dictation: record → transcribe → paste
├── hotkey.py            # Global hotkey (NSEvent / pynput)
├── paste.py             # Clipboard + paste simulation per platform
├── tray.py              # System tray icon (dictation status)
├── sounds.py            # Synthesized notification sounds
├── speaker_manager.py   # Speaker profile JSON persistence
├── enrollment.py        # Speaker embedding recording/extraction
├── model_manager.py     # Local model catalog + GitHub LFS downloads
├── skill_manager.py     # Skill discovery (git/local) + registry
├── skills_sh_client.py  # skills.sh public search client
├── mcp_manager.py       # MCP connections, tool routing
├── mcp_auth.py          # OAuth2 provider + localhost callback server
├── mcp_app_bridge.py    # QWebChannel JSON-RPC bridge for MCP Apps
├── icons.py / theme.py  # Heroicons SVG renderer / dark-light QSS palettes
├── providers/           # LLM factories: anthropic, openai, gemini, local (lazy registry)
├── tts/                 # TTS factories: piper, qwen3, neutts, gradium, elevenlabs
└── widgets/
    ├── main_window.py   # Window layout + Engine↔UI signal wiring
    ├── control_bar.py   # Sparkle call button, mute/reset, settings
    ├── chat_view.py / chat_bubble.py
    ├── mcp_app_widget.py # QWebEngineView host for MCP Apps
    ├── vu_meter.py / session_info.py / hotkey_button.py / dictation_log.py
    └── settings/        # 11-tab settings dialog (general, ai, attitudes, speakers,
                         #  dictation, models, skills/, mcp, audio_debug, telemetry, about)
```

## Data models & persistence

There is no database. State lives in three places:

1. **QSettings** (`settings.py`) — ~90 flat keys: model choices, VAD/AEC/denoise
   tuning, hotkeys, theme, sanitized MCP server configs (JSON string), skill
   sources, attitudes. Secrets go through `SecretStore` (OS keyring first,
   QSettings fallback).
2. **Speaker profiles** — one JSON file per speaker in the platform data dir
   (`speakers/<name>.json`): name, embeddings (list of float vectors), `is_primary`.
3. **Model store** — `models/<model-id>/v1/` under the platform data dir; the `v1`
   segment leaves room for format migrations.

## Key patterns

### Engine mixin composition

`Engine(CallbackMixin, ToolMixin, RealtimeMixin, VoiceChannelMixin, QObject)` — mixins
contribute behavior only; every attribute lives on `Engine`. This keeps Qt signal
definitions in one QObject while splitting the two session modes into separate files.

### Lazy provider factories

```python
# providers/__init__.py — registry dispatch, no if-chains
_FACTORIES = {"anthropic": "roomkit_ui.providers.anthropic", ...}

def create_ai_provider(name: str, settings: dict) -> Any:
    module = importlib.import_module(_FACTORIES[name])
    return module.create(settings)
```

Heavy SDKs (anthropic, google-genai, openai) are only imported when the user actually
selects that provider.

### No private-API reaches

The app uses only public roomkit APIs. Operations that once poked roomkit
internals now have public entry points (roomkit 0.24.0+):

- **Provider lifecycle** — `VoiceChannel(close_providers=False)` (the engine owns
  STT/TTS closing for model caching), instead of nulling `channel._stt`/`_tts`.
- **Live system-prompt swap** — `AIChannel.set_system_prompt(...)`, instead of
  writing `AIChannel._system_prompt`.
- **Diarization enrollment reset** — `DiarizationProvider.clear_speakers()`,
  instead of clearing `_manager` / `_enrolled_embeddings`.

### Qt-signal safety in async callbacks

Callbacks invoked by roomkit may fire after the C++ side of a QObject is deleted, so
emits are wrapped in `try/except` (`SIM105` is disabled for this reason). The cost:
some real failures are swallowed silently — see Technical debt.

## Configuration management

- All user configuration is edited in the Settings dialog and persisted via QSettings —
  no config files, no required env vars.
- Env vars honored at startup: `DEBUG=1` (verbose logging for mcp/roomkit), plus
  rendering overrides set *by* the app (`QT_QUICK_BACKEND`, `QSG_RHI_BACKEND`,
  `QTWEBENGINE_CHROMIUM_FLAGS`, `LIBGL_ALWAYS_SOFTWARE`).
- `QT_QUICK_BACKEND=software` must be set **before** PySide6 import (`app.py`).

## Build & deployment

```bash
./scripts/build_app.sh            # icons + PyInstaller bundle
```

CI (`.github/workflows/`):

- `ci.yml` — ruff check + format check, bandit, mypy on every push/PR.
- `build.yml` — PyInstaller builds for macOS (codesign + notarize + DMG), Linux
  (tar.gz), Windows (ZIP); uploads to GitHub Releases. Hidden imports for
  dynamically-loaded SDKs are listed in the workflow and `RoomKit UI.spec`.

## Testing strategy

Automated tests cover core pure-Python logic and several security-sensitive helpers.
CI also covers linting, formatting, typing, and static security analysis. The main
remaining test gap is broader integration/UI coverage. What should stay covered first,
in order of value:

1. `Engine._cleanup` ordering — the teardown sequence encodes hard-won fixes
   (ElevenLabs double-close hang, qasync timer leaks); a regression is a 100 % CPU bug.
2. `settings.py` round-trip — ~90 keys with type coercion.
3. `skill_manager.discover_all_skills` / `model_manager` LFS pointer parsing — pure
   logic, easy to unit-test with fixtures.
4. Tool dispatch (`engine_tools.py`) — builtin-vs-MCP routing and the pending-call counter.

Widget code is hard to test without `pytest-qt`; the five modules above need none of it.

## Code quality tools

```bash
uv run ruff check .              # E,F,I,N,UP,B,SIM — line length 99
uv run ruff format --check .
uv run mypy src/                 # attr-defined disabled for PySide6 dynamic enums
uv run bandit -r src/ -c pyproject.toml
```

## Known technical debt

| # | Item | Where | Recommendation |
|---|---|---|---|
| 1 | Limited integration/UI coverage | engine workflows, widgets | Add higher-level tests around session setup, settings pages, and MCP App rendering |
| 2 | No checksum verification on model downloads | `model_manager.py` | Pin SHA-256 per model in the catalog (LFS pointers already carry the OID) |
| 3 | SecretStore can fall back to QSettings when no OS keyring backend is available | `secret_store.py`, `settings.py`, `mcp_auth.py` | Surface backend status in Settings and docs |
| 4 | Oversized modules: `model_manager.py` (~965 l), `models_page.py` (~760 l), `speakers_page.py` (~675 l), `stt_engine.py` (~680 l), `engine_vc.py` (~515 l) | - | Split by responsibility (catalog data vs download logic; dialogs vs page) |
| 5 | Silent `except Exception: pass` beyond Qt-emit guards | `engine_callbacks.py`, `builtin_tools.py:126`, `main_window.py:224` | Log at DEBUG instead of `pass` |
| 6 | Engine state machine is string-based (`"idle"`, `"active"`, ...) | `engine.py` | `enum.StrEnum` for typo safety |
| 7 | Repeated stylesheet f-strings (~200 `setStyleSheet` calls) | `widgets/` | Shared style helpers per pattern |
| 8 | `cleanup.py` depends on qasync name-mangled internals | `cleanup.py` | Re-verify on every qasync upgrade; upstream a fix |
| 9 | MCP stdio execution trust is user-configured | `mcp_manager.py` | Consider per-server allow/deny prompts for sensitive tools |
| 10 | Unused mypy override sections (Quartz, sherpa_onnx, sounddevice, qasync now ship types) | `pyproject.toml` | Prune on next config pass |
| 11 | No keyboard navigation / accessible names on custom-painted buttons | `control_bar.py` | `setFocusPolicy`, `setAccessibleName` |
