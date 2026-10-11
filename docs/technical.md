# Technical Reference

> _Generated: 2026-06-11 — updated 2026-10-10 for roomkit 0.96.1 — re-run /project-review to update_

System context lives in [architecture.md](architecture.md); feature-to-code mapping in
[features.md](features.md); setup steps in [onboarding.md](onboarding.md).

## Technology stack

| Layer | Technology | Version (locked) |
|---|---|---|
| Language | Python | 3.12+ |
| GUI | PySide6-Essentials (Qt 6); PySide6-Addons via the `mcp-apps` extra | 6.11.1 |
| Async/Qt bridge | qasync | 0.28.0 |
| Voice/AI framework | roomkit (core: `local-audio`, `webrtc-aec`; every backend through an app extra) | 0.96.1 |
| Tool protocol | mcp | 2.0.0 |
| HTTP | httpx | 0.28.1 |
| Secrets | keyring | 25.7.0 |
| Markdown rendering | markdown-it-py | 4.2.0 |
| Global hotkeys | pynput (fallback; NSEvent native on macOS) | 1.8.2 |
| Local inference | sherpa-onnx (via roomkit extra), onnxruntime (wake word) | 1.13.4, 1.28.0 |
| Packaging | hatchling (build), PyInstaller 6 (bundles), uv (env) | — |
| Quality | ruff 0.16, mypy 2.3, bandit 1.9, pytest 9.1 | — |

## Project structure

```
src/roomkit_ui/
├── app.py, features.py         # Startup (graphics env, --doctor, qasync); optional-backend registry
├── engine.py, engine_state.py  # Engine shell: start task / stop, state machine, model cache, teardown
├── engine_vc.py, engine_vc_helpers.py          # Voice Channel mode (mixin + stateless builders)
├── engine_realtime.py, realtime_providers.py   # Realtime mode (mixin + provider builders, audio wiring)
├── engine_audio.py             # Pipeline builders: AEC, denoise, VAD, diarization, recording, DSP pool
├── engine_callbacks.py, engine_tools.py, toolset.py, builtin_tools.py   # Callbacks, tool dispatch
├── hooks.py, watchdog.py, idle_hangup.py, cleanup.py, memory.py, aec_dump.py
├── mcp_manager.py, mcp_config.py, mcp_auth.py, mcp_app_bridge.py, url_policy.py
├── cli_tools.py, cli_exec.py, cli_help.py, cli_tools_config.py, env_config.py
├── skill_manager.py, skill_git.py, skill_well_known.py, skills_sh_client.py
├── stt_engine.py, stt_sessions.py, hotkey.py, paste.py, paste_windows.py, tray.py, sounds.py
├── speaker_manager.py, enrollment.py
├── model_catalog.py, model_download.py, model_manager.py, download_flight.py
├── settings.py, settings_secrets.py, secret_store.py, constants.py, icons.py, theme.py
├── providers/                  # LLM factories: anthropic, openai, gemini, local, llamacpp (lazy registry)
├── tts/                        # TTS factories: piper, pocket, qwen3, neutts, gradium, elevenlabs, azure
├── wakeword/                   # Wake word: controller, listener, capture, detection, enrolment
└── widgets/                    # Main window, chat, MCP App views, loading overlay, wake-word wizard,
                                #  settings/ (13-tab dialog)
```

The Architecture section of [CLAUDE.md](../CLAUDE.md) describes every module.

## Data models & persistence

There is no server database. State lives in these places:

1. **QSettings** (`settings.py`) — ~150 flat keys: model choices, VAD/AEC/denoise
   tuning, hotkeys, theme, sanitized MCP server and CLI tool configs (JSON strings), skill
   sources, attitudes, wake word options. Renamed keys and retired defaults migrate on
   load. Secrets go through `settings_secrets.py` → `SecretStore` (OS keyring first,
   QSettings fallback).
2. **Conversation history** — `conversations.db`, roomkit's `SQLiteStore`, in the
   platform data dir (`~/Library/Application Support/RoomKit UI/` on macOS,
   `~/.local/share/roomkit-ui/` elsewhere), mode 0600.
3. **Speaker profiles** — one JSON file per speaker in the platform data dir
   (`speakers/<name>.json`): name, embeddings (list of float vectors), `is_primary`.
   Skills sources are cloned under the same data dir (`skills/`).
4. **Model store** — `~/.local/share/roomkit-ui/models/<model-id>/v1/` on every platform;
   the `v1` segment leaves room for format migrations. The wake-word fingerprint
   (`wakeword/fingerprint.npz` + `.json`), recordings and debug taps live under
   `~/.local/share/roomkit-ui/` too.

## Key patterns

### Engine mixin composition

`Engine(CallbackMixin, ToolMixin, RealtimeMixin, VoiceChannelMixin, QObject)` — mixins
contribute behavior only; every attribute lives on `Engine`. This keeps Qt signal
definitions in one QObject while splitting the two session modes into separate files.
Stateless builders sit beside them (`engine_vc_helpers.py`, `realtime_providers.py`,
`engine_audio.py`).

### Session lifecycle

`start()` claims CONNECTING before its first await and runs the session start as its own
task; `stop()` publishes STOPPING, cancels that task where it waits, and runs the teardown
once it has unwound. A failed start holds STOPPING through its teardown and reports ERROR
after (`_fail_start`). The teardown (`_cleanup`) is a sequence of named steps whose order
encodes past fixes; see [onboarding.md — Common pitfalls](onboarding.md#common-pitfalls).

### Lazy provider factories and optional backends

```python
# providers/__init__.py — registry dispatch, no if-chains
_REGISTRY = {"anthropic": "roomkit_ui.providers.anthropic", ...}

def create_ai_provider(name: str, settings: dict) -> Any:
    feature = AI_PROVIDER_FEATURES.get(name)
    if feature is not None:
        require(feature)            # FeatureUnavailableError names the install command
    module = importlib.import_module(_REGISTRY[name])
    return module.create(settings)
```

Heavy SDKs (anthropic, google-genai, openai) are only imported when the user actually
selects that provider. `features.py` maps each provider to an extra and the modules it
imports; a missing one reaches the chat, the Settings combo and `--doctor` as the command
that installs it. Extras that pin conflicting `transformers` versions (`qwen3-tts`,
`neutts`, `smart-turn`) are listed in `EXCLUSIVE_EXTRAS`, mirroring `[tool.uv].conflicts`.

### Tool calls

Tools are grouped by source (`ToolSet`: built-in, CLI, MCP). Every channel built with tools
takes `toolset.channel_options()`, which turns off roomkit's own per-call timeout (the app
bounds MCP calls at 60 s and each CLI tool at its own timeout) and pins the built-ins
against Tool Search. A failed call raises `roomkit.ToolFailedError` or `ToolRefusedError`,
which every provider reads as a failure — Gemini reads any returned body as a success.

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
some real failures are swallowed silently — see Technical debt. Work that outlives the
Settings dialog (destroyed on close) checks its widget still exists before touching it.

## Security implementation

- **Secrets** — API keys, MCP OAuth client secrets and secret-looking env values of MCP
  servers and CLI tools are stored in the keyring (`cli_tool:<id>:env:<KEY>` for CLI
  tools); QSettings keeps `KEY=`. A URL carrying credentials counts as a secret whatever
  the variable is called. A value written to the QSettings fallback while the keyring was
  locked is read first and moved back into the keyring once it works.
- **MCP OAuth** — stored tokens record the server URL they were issued for; when the
  server's URL changes, the tokens and the client registration are dropped instead of
  being sent to the new host.
- **MCP Apps** — QtWebEngine runs with the same-origin policy on (no
  `--disable-web-security`). `url_policy.py` decides what a request or an "Open link" may
  reach: numeric IPv4 forms parsed per the WHATWG URL standard, a host public only when
  `is_global` (judged on the embedded IPv4 where there is one), and a name must resolve
  within 2 s, only to global addresses. Each widget has its own web profile.
- **CLI tools** — argv lists only, through `cli_exec` (PATH and library paths repaired
  for a Dock launch and a frozen build). `--help` probes run in batches of 16 under a byte
  cap and are cached for the app's lifetime, keyed by argv, env, depth, cap and the
  binary's mtime.
- **Skills** — git runs through `cli_exec` with `--` before the URL, timeouts (clone
  180 s, pull 120 s), `GIT_TERMINAL_PROMPT=0`, without inherited `GIT_DIR` & co., and
  clones into a staging folder. Well-known installs are https only, redirects included,
  streamed under a 5 MB per-file and 50 MB per-skill cap.
- **Model downloads** — every request gives up after 30 s without a byte; Git LFS files
  are checked against their OID (SHA-256), Smart Turn and the wake-word encoder against
  a pinned SHA-256, espeak-ng data against git blob ids; one download per model at a time
  (`download_flight.py`), joined by a second request.

## Configuration management

- All user configuration is edited in the Settings dialog and persisted via QSettings —
  no config files, no required env vars. The dialog saves when it closes, however it is
  closed.
- Env vars honored at startup: `DEBUG=1` (verbose logging for mcp/roomkit),
  `ROOMKIT_AEC_DUMP=<dir>` (record what the realtime AEC sees, for roomkit's offline
  bench).
- Rendering overrides set *by* the app, before PySide6 is imported
  (`app._graphics_env()`): `QTWEBENGINE_CHROMIUM_FLAGS` always; `QT_QUICK_BACKEND=software`
  and `LIBGL_ALWAYS_SOFTWARE=1` only when the Linux-only OpenGL probe fails. Values
  already in the environment win.

## Build & deployment

```bash
./scripts/build_app.sh            # PyInstaller bundle (--extra all)
```

CI (`.github/workflows/`):

- `ci.yml` — on every push to main and PR, and called first by both release workflows
  (`workflow_call`): one job for ruff check + format check, bandit and mypy against the
  synced dev environment; pytest (offscreen Qt); a Windows job that imports the app on a
  core-only install and runs `--doctor`.
- `build.yml` — on a `v*` tag: CI, a tag/version check, then PyInstaller builds for macOS
  (signed + notarized when the Apple secrets are set, else ad hoc; DMG), Linux (tar.gz),
  Windows (ZIP), uploaded to GitHub Releases; then the Homebrew cask, only for an app
  that passes `xcrun stapler validate`.
- `release.yml` — on the same tag: CI, then the wheel to PyPI through Trusted Publishing,
  after installing it with `[all]` and running `--doctor`.

The PyInstaller flags live in `scripts/build_app.sh` and the Unix and Windows steps of
`build.yml`; `tests/test_build_flags.py` fails when the three lists differ. `RoomKit UI.spec`
is PyInstaller's output, regenerated by each build and gitignored.

## Testing strategy

The pytest suite (`tests/`, ~90 modules) covers pure-Python logic, the security-sensitive
helpers, the engine's lifecycle and teardown, tool dispatch, settings round-trips, the
wake word, and pieces of the UI under `pytest-qt` (offscreen). Several tests run real
roomkit channels on roomkit's mocks (`tests/vc_harness.py`). Guards that keep packaging
honest: `test_features.py` (extras ↔ `features.py`, exclusive extras ↔ uv conflicts) and
`test_build_flags.py` (the three PyInstaller flag lists). The main remaining gap is
end-to-end coverage with real devices and providers. What should stay covered first, in
order of value:

1. `Engine._cleanup` ordering — the teardown sequence encodes hard-won fixes
   (ElevenLabs double-close hang, qasync timer leaks); a regression is a 100 % CPU bug.
2. `settings.py` round-trip — ~150 keys with type coercion, migrations and secrets.
3. `skill_manager` discovery / `model_download` LFS pointer parsing — pure logic, easy to
   unit-test with fixtures.
4. Tool dispatch (`engine_tools.py`) — precedence (engine built-ins, built-ins, CLI, MCP),
   raised failures and the pending-call counter.

## Code quality tools

```bash
uv run ruff check .              # E,F,I,N,UP,B,SIM — line length 99
uv run ruff format --check .
uv run mypy src/                 # attr-defined disabled for PySide6 dynamic enums
uv run bandit -r src/ -c pyproject.toml
QT_QPA_PLATFORM=offscreen uv run pytest -q
```

## Known technical debt

| # | Item | Where | Recommendation |
|---|---|---|---|
| 1 | No end-to-end coverage with real devices and providers | engine workflows, audio | Scripted smoke sessions against the providers' sandboxes |
| 2 | GitHub release-asset models publish no digest — size-checked only | `model_download.py` (GTCRN, speaker models) | Pin SHA-256 per asset in the catalog |
| 3 | SecretStore can fall back to QSettings when no OS keyring backend is available | `secret_store.py`, `settings_secrets.py`, `mcp_auth.py` | Surface backend status in Settings and docs |
| 4 | Largest modules: `realtime_section.py` (~750 l), `engine.py` (~660 l), `engine_vc.py` (~570 l), `mcp_page.py` (~540 l), `models_page.py` (~530 l), `audio_debug_page.py` (~510 l) | - | Split by responsibility when they next grow |
| 5 | Silent `except Exception: pass` beyond Qt-emit guards | `stt_engine.py` (dictation teardown), `engine.py` (diarization close) | Log at DEBUG instead of `pass` |
| 6 | Repeated stylesheet f-strings (~200 `setStyleSheet` calls) | `widgets/` | Shared style helpers per pattern |
| 7 | `cleanup.py` depends on qasync name-mangled internals | `cleanup.py` | Re-verify on every qasync upgrade; upstream a fix |
| 8 | MCP stdio and CLI tool execution trust is user-configured | `mcp_manager.py`, `cli_tools.py` | Consider per-call confirmation for sensitive tools |
| 9 | Unused mypy override sections (Quartz, sherpa_onnx, sounddevice, qasync now ship types) | `pyproject.toml` | Prune on next config pass |
| 10 | Realtime sessions cannot run diarization (roomkit 0.96.1 forwards no speaker change from `RealtimeVoiceChannel`) | `engine_realtime.py` | Bring it back once roomkit reports pipeline speaker changes and forwards pipeline audio at the provider's rate |
| 11 | Frozen builds: roomkit spawns `llama-server` with the app's environment, PyInstaller's library path included | `providers/llamacpp.py` | Fix upstream in roomkit's server spawn |
