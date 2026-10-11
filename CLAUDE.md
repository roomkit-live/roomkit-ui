# RoomKit UI

PySide6 + qasync desktop voice assistant wrapping the `roomkit` framework.

## Commands

```bash
uv sync                          # Core only — no AI backend at all
uv sync --extra all              # Core + every backend (what a build ships)
uv sync --extra dev              # ...plus dev tools (dev implies all)
uv sync --extra dev --extra smart-turn   # ...plus ONE exclusive extra (see below)
uv run python -m roomkit_ui         # Run the app
uv run roomkit-ui --doctor       # Which backends this install carries
QT_QPA_PLATFORM=offscreen uv run pytest -q  # Tests (CI runs them offscreen)
uv run ruff check .              # Lint
uv run ruff format --check .     # Format check
uv run ruff format .             # Auto-format
uv run mypy src/                 # Type check
uv run bandit -r src/ -c pyproject.toml  # Security scan
```

`all` leaves four extras out. `qwen3-tts`, `neutts` and `smart-turn` pin conflicting
`transformers` versions: they are declared in `[tool.uv].conflicts`, mirrored by
`features.EXCLUSIVE_EXTRAS` (a test keeps the two equal), and at most one goes in an
environment. `pocket-tts` stays out because it pulls torch.

## Architecture

Entry point: `src/roomkit_ui/app.py` → `roomkit_ui.app:main`

```
src/roomkit_ui/
├── __main__.py          # `python -m roomkit_ui` → app.main
├── app.py               # Startup: graphics env (before PySide6), --doctor, QApplication + qasync, tray, hotkeys, wake word
├── constants.py         # UI-independent constants (attitude presets, …)
├── features.py          # Optional-backend registry: extras ↔ import probes ↔ install commands, EXCLUSIVE_EXTRAS, --doctor
├── engine.py            # Engine shell: start task / stop, state machine, model cache, kit build, ordered teardown
├── engine_state.py      # EngineState StrEnum — leaf
├── engine_vc.py         # Voice Channel start (STT → LLM → TTS) — mixin
├── engine_vc_helpers.py # Stateless VC builders: cloud STT, barge-in, TTS filter, Smart Turn, turn VAD, local LLM
├── engine_realtime.py   # Realtime start: media per attempt, no-MCP retry, channel — mixin
├── realtime_providers.py # Realtime builders + config (Gemini, OpenAI, GPT-Live, Deepgram, ElevenLabs, xAI), transport_audio_profile
├── engine_audio.py      # Pipeline builders: AEC, denoiser, VAD, diarization, recorder, DSP_THREADS, shared-mic rate
├── engine_callbacks.py  # Realtime provider callbacks → Qt signals — mixin
├── engine_tools.py      # Tool dispatch (engine built-ins → built-ins → CLI → MCP), attitudes, paste — mixin
├── toolset.py           # Tool grouping (builtin/cli/mcp), channel_options(), reachable_mcp_tools — leaf
├── builtin_tools.py     # Built-in tools (always available)
├── hooks.py             # RoomKit hook registration for UI events (VC + realtime)
├── watchdog.py          # Unanswered-speech detector (8 s) + model nudge
├── idle_hangup.py       # Hangs up a session gone quiet (set on the Wake Word page, any session)
├── cleanup.py           # qasync timer/FD cleanup after MCP disconnect, registered_fds()
├── memory.py            # Persistent conversations: SQLite store, realtime recap, recall_conversations tool
├── aec_dump.py          # AEC dump for roomkit's offline bench (ROOMKIT_AEC_DUMP=<dir>, realtime only)
├── cli_tools.py         # CLI tool manager: schema build + dispatch (mirrors MCPManager)
├── cli_exec.py          # Child-process primitives: PATH/env, Popen registry, timeout
├── cli_help.py          # Recursive `--help` probing (Click/Typer/Rich + Cobra), cached per binary mtime
├── cli_tools_config.py  # CLI tool config parsing + validation (mirrors mcp_config.py)
├── env_config.py        # `KEY=VALUE` env block parsing (MCP servers + CLI tools) — leaf
├── mcp_manager.py       # MCP client manager (stdio, SSE, HTTP transports)
├── mcp_config.py        # MCP server config parsing helpers
├── mcp_auth.py          # OAuth2 for MCP HTTP servers; tokens bound to the server URL
├── mcp_app_bridge.py    # MCP Apps JSON-RPC bridge (QWebChannel ↔ iframe)
├── url_policy.py        # Public-host policy for MCP App requests and links
├── stt_engine.py        # Dictation lifecycle (DictationState) + paste
├── stt_sessions.py      # Dictation session bring-up per provider — mixin
├── hotkey.py            # Global hotkey (NSEvent on macOS, pynput fallback)
├── paste.py             # Clipboard + paste keystroke per platform (paste_into_focused)
├── paste_windows.py     # Windows clipboard + Ctrl+V through Win32 SendInput (ctypes)
├── tray.py              # System tray icon for dictation
├── sounds.py            # Notification sounds for session start/stop
├── speaker_manager.py   # Speaker profile JSON persistence (~/.local/share/roomkit-ui/speakers)
├── enrollment.py        # Speaker embedding recording/extraction (sherpa-onnx)
├── model_catalog.py     # Downloadable local models + on-disk locations
├── model_download.py    # Download plumbing: raw GitHub, Git LFS (oid-checked), release assets; 30 s timeouts
├── model_manager.py     # Download/delete entry points per model kind (edge-ai-models)
├── download_flight.py   # One download per model across Settings dialogs — leaf
├── skill_manager.py     # Skill source dirs, discovery, SkillRegistry build
├── skill_git.py         # git clone/pull/remove for skill sources (isolated git runner)
├── skill_well_known.py  # skills.sh well-known installer (https only, byte caps)
├── skills_sh_client.py  # skills.sh public search client
├── settings.py          # QSettings persistence (~150 keys), defaults, migrations
├── settings_secrets.py  # Keyring hand-off: API keys, MCP OAuth secrets, MCP/CLI env secrets
├── secret_store.py      # SecretStore: OS keyring, QSettings fallback
├── icons.py             # Heroicons SVG rendering
├── theme.py             # Dark/Light theme stylesheets
├── providers/           # LLM factories, lazy registry: anthropic, openai, gemini, local (vLLM/Ollama), llamacpp
├── tts/                 # TTS factories, lazy registry: piper, qwen3, neutts, pocket, gradium, elevenlabs, azure, _util
├── wakeword/            # controller (shared mic + listener lifetime), listener, capture (mic → VAD → segments),
│                        #  resample, jobs (SerialWorker), detector, features (whisper encoder), dtw, fingerprint,
│                        #  enroller, encoder_download, page_sensitivity
└── widgets/
    ├── main_window.py     # Main window layout + Engine↔UI signal wiring
    ├── control_bar.py     # Call button + mic mute + settings
    ├── chat_view.py       # Scrollable chat transcript
    ├── chat_bubble.py     # One chat entry: user bubble, typeset assistant text
    ├── loading_overlay.py # Full-window curtain (with Cancel) while a session connects
    ├── mcp_app_widget.py  # MCP App widget (QWebEngineView, text fallback)
    ├── mcp_app_web.py     # QtWebEngine request filter + page
    ├── mcp_app_server.py  # 127.0.0.1 server + CSP for MCP App content
    ├── mcp_app_wrapper.py # Wrapper page: QWebChannel bridge + app iframe
    ├── vu_meter.py        # Animated ambient glow VU meter
    ├── session_info.py    # Collapsible session info bar
    ├── hotkey_button.py   # Interactive hotkey capture widget
    ├── dictation_log.py   # Dictation event log window
    ├── wakeword_wizard.py # Guided wake-word enrolment
    └── settings/          # 13-tab dialog (panel.py), one <tab>_page.py per tab: general, ai, attitudes,
                           #  speakers, dictation, wakeword, models, mcp, cli_tools, audio_debug, telemetry,
                           #  about, plus skills/ (page, my_skills, marketplace, widgets). AI tab parts:
                           #  realtime_section, realtime_catalogs, realtime_gemini_live, realtime_gpt_live,
                           #  vc_local_fields, vc_cloud_fields, vc_azure_fields; also models_widgets,
                           #  speakers_dialogs, feature_hints
```

Engine composition: `Engine(CallbackMixin, ToolMixin, RealtimeMixin, VoiceChannelMixin, QObject)` —
mixins hold no state; all attributes live on `Engine`. Docs: `docs/architecture.md`,
`docs/technical.md`, `docs/features.md`, `docs/onboarding.md`.

Packaging: the base install is core-only (window, mic pipeline, AEC, MCP/CLI tools).
Every AI backend lives behind an extra declared in `pyproject.toml` AND mirrored in
`features.py`; `tests/test_features.py` fails if the two drift.

## Code Style

- Python 3.12+, target in pyproject.toml
- Ruff: `select = ["E", "F", "I", "N", "UP", "B", "SIM"]`, line-length 99
- `SIM105` ignored — try/except/pass used intentionally for Qt signal safety
- `N802` ignored in widget files — Qt method overrides (paintEvent, enterEvent)
- Mypy: `disable_error_code = ["attr-defined"]` for PySide6 dynamic enums

## Gotchas

### Startup and Qt
- The graphics environment is decided by `app._graphics_env()` and applied BEFORE PySide6 is imported. The OpenGL probe runs on Linux only (macOS/Windows render through Metal/Direct3D and ship no libEGL); only without OpenGL does it set `QT_QUICK_BACKEND=software`, `LIBGL_ALWAYS_SOFTWARE=1` and Chromium's GPU-off flags
- Never pass `--disable-web-security` to Chromium: it is process-wide, and MCP Apps rely on the same-origin policy (with `url_policy`) to keep local and LAN services out of reach
- Qt signals in async callbacks: always wrap emit() in try/except — the C++ object may be deleted
- The Settings dialog has no Save button: it saves in `done()`, on every way out (Esc included), and is destroyed after. Work that outlives it (downloads, OAuth, skill installs) must check its widget still exists. Shared API-key fields are mirrored live across tabs (`_link_api_key_fields`)
- Secrets go through `settings_secrets.py` (keyring via `SecretStore`): API keys, MCP OAuth client secrets, and secret-looking env values of MCP servers AND CLI tools. Never write one to QSettings directly

### Session lifecycle
- `start()` claims CONNECTING before its first await and runs the start as its own task (`_start_task`); `stop()` publishes STOPPING, cancels that task and tears down once it has unwound. A failed start goes STOPPING → cleanup → ERROR (`_fail_start`). A stop before the kit exists closes the transport/backend itself (`_close_unowned_backends`)
- Teardown order in `Engine._cleanup` is load-bearing (TTS before `kit.close()`, MCP after it, two loop yields before the FD pass); each step is a named method saying why
- qasync timer cleanup: after an MCP session closes, anyio leaves orphaned 0ms timers → 100% CPU. See `cleanup.py`. The end-of-session pass `cleanup_stale_fds(keep=...)` removes only FD notifiers registered since the session started (`registered_fds()` snapshot) — the app's own sockets (OAuth callback, downloads) survive
- MCP server stacks are closed in the task that opened them (anyio cancel scopes). Closing one from another task made anyio cancel the owner and hung `close_all()`

### Tools
- MCP tool schemas: strip `$schema` and `additionalProperties` keys for Gemini compatibility (`_clean_schema()` in mcp_manager.py)
- MCP session retry (realtime): retry with `ToolSet.without_mcp` (builtin + CLI) only when the provider refused the session config (`_refuses_session_config`: a ValueError, Gemini Live's 1007, Deepgram's "rejected Settings") — never on a bad key, the network or a quota. Each attempt runs on freshly built media (`_build_realtime_media`): a failed attempt's `kit.close()` closed the provider, the transport and its AEC. Only MCP is shed (server-supplied schemas). Trigger on `ToolSet.has_mcp`, never on a tool-count comparison
- Every roomkit channel built with tools takes `**toolset.channel_options()`: since 0.95 roomkit bounds each tool call itself (10 s realtime, 30 s AIChannel) and Tool Search hides tools behind `find_tools` once the catalogue is large. The app keeps its own bounds (MCP 60 s, per-CLI-tool timeout) and pins the built-ins. roomkit also refuses a tool name declared twice when it builds a realtime channel, so `_setup_tools` drops MCP tools named like a built-in/CLI tool or outside `[A-Za-z0-9_-]{1,64}` and says so in the chat
- A tool that fails raises `roomkit.ToolFailedError` (it ran and failed) or `ToolRefusedError` (nothing ran) — since roomkit 0.95 Gemini reads any returned body as a success. Two envelopes stay: `{"error": "Unknown tool"}` (roomkit reads it as "not served here") and the `{"error": ...}` an MCP App widget receives before the engine re-raises
- CLI tool schemas are hand-authored and never pass through `_clean_schema()` — so do NOT add `additionalProperties` to them, nothing would strip it and Gemini rejects it
- Tool names reaching a provider must be `[A-Za-z0-9_-]{1,64}` — no spaces, no dots. Don't push that rule onto the user: `cli_tools_config.slugify_tool_name()` derives it ("GitHub CLI" → `github_cli`) and the settings page shows the result. A declaration the model never receives must surface in the chat, not only in a log
- `cli_help.parse_subcommands()` covers Click/Typer, Rich boxes and Cobra (`gh` uses colon-suffixed names across several `* COMMANDS` sections). It is best-effort by design — a CLI with bespoke help (`git`, `brew`) seeds depth 1 and the model explores via `--help` through the tool. Test any parser change against `gh`, `kubectl`, `docker` AND a Rich/Typer CLI: the two ecosystems break each other
- Nothing in a CLI tool's shared description text may name a real subcommand — it is injected into *every* declared tool, so an example from one CLI is nonsense in another's (`_ARGS_HINT` in `cli_tools.py`)

### Child processes
- CLI tools: never `shell=True`, always an argv list. A macOS `.app` launched from the Dock inherits only `/usr/bin:/bin:/usr/sbin:/sbin`, and PyInstaller repoints `DYLD_LIBRARY_PATH` at `_MEIPASS` — both are handled in `cli_exec.child_env()`/`search_path()`, so spawn through there, not bare `subprocess`. MCP stdio servers resolve their command the same way
- No shell means the Command field is not one: `FOO=1 mycli` makes `resolve_command()` look for a binary literally named `FOO=1` and the whole tool gets dropped. Env vars go in the tool's Env field (`KEY=VALUE` per line, parsed by `env_config.parse_env_block`), same as an MCP server. They reach the `--help` probe too, so seeded help describes the CLI as configured
- git for skills runs through `skill_git` and drops `GIT_DIR` & co. (`_GIT_REDIRECTS`): an app started from a git hook or `rebase --exec` would otherwise act on that repository. Tests that run git must clear them too
- llama.cpp: roomkit spawns `llama-server` with a copy of the app's environment, so in a frozen build it inherits PyInstaller's library path — `cli_exec` cannot help, the fix belongs upstream. The server runs on its own thread and loop (`providers/llamacpp.py`) so it survives sessions and the end-of-session FD cleanup

### Packaging
- Adding a backend means three edits, not one: the extra in `pyproject.toml`, the `Feature` in `features.py`, and the provider→feature entry in the matching `*_FEATURES` map. An extra that conflicts with another also goes in `[tool.uv].conflicts` AND `EXCLUSIVE_EXTRAS`. Probe what the code path *imports*, not what the extra installs — the realtime providers ride a raw websocket and never touch the vendor SDK, so requiring it would block a session that works
- `RoomKit UI.spec` is gitignored and *regenerated* by every build — it is PyInstaller's output, not its input. The real flag lists live in `scripts/build_app.sh` and `.github/workflows/build.yml` (Unix + Windows steps); `tests/test_build_flags.py` fails when the three differ, so a flag goes in all three (`tiktoken_ext.openai_public` for GPT-Live, `--collect-binaries=aec_audio_processing`, which a Linux release once lost). All use `--collect-submodules=roomkit,roomkit_ui` because the backends load through string-keyed registries static analysis cannot follow
- `uv sync` with no extra installs the core, which has no AI backend at all. Anything that builds or ships the app must use `--extra all` — so frozen builds carry neither Smart Turn, Pocket TTS, Qwen3-TTS nor NeuTTS

### Audio
- AEC wiring (realtime) is PER PROVIDER — mirror roomkit's example for that provider (`transport_audio_profile` in realtime_providers.py). Gemini/OpenAI Realtime/xAI/ElevenLabs: `aec` to `AudioPipelineConfig` ONLY (`LocalAudioBackend(aec=...)` flags NATIVE_AEC, the pipeline skips its AEC stage and loses the continuous playback reference — the 0.9.0 barge-in fix; `examples/realtime_voice_local_gemini.py`). Deepgram: `aec` to the TRANSPORT (inline on the PortAudio thread, sample-synchronous) + webrtc NS in the pipeline (`examples/realtime_voice_local_deepgram.py` — an open, poorly-aligned mic makes Deepgram transcribe its own voice and barge-in forever); `rt_prebuffer_ms=240` for Aura's bursts, with or without an AEC. GPT-Live: `aec` to the transport too + webrtc NS whether or not there is an AEC + the default 120 ms prebuffer (`examples/realtime_voice_local_openai_live.py`). No AEC at all mutes the mic during playback. VC mode still passes `aec` to both
- No user denoiser on the realtime mic path — speech enhancers keep the dominant voice and eat the user's barge-in during doubletalk. Denoisers are VC-mode only. The two exceptions mirror roomkit's examples: the mild WebRTC noise suppressor for Deepgram (with an AEC) and GPT-Live
- Realtime pipelines carry no VAD and no diarization (`_build_realtime_pipeline`). roomkit 0.96.1's RealtimeVoiceChannel forwards no speaker change and sends 16 kHz pipeline audio to the provider as 24 kHz, and a pipeline VAD would take barge-in authority from the provider's server VAD (`_realtime_speech.py` early-returns). Diarization is Voice Channel only (`REALTIME_DIARIZATION_NOTICE`)
- The inbound DSP pool is ON (`DSP_THREADS = 1` in engine_audio.py, both modes): since roomkit 0.95 (RMK-392) the pipeline sends every stage callback back to its loop, in order. Before that, the pool dropped them (no mic audio, dead VU meter)
- `InterruptionConfig`: pass `InterruptionStrategy.DISABLED` explicitly, not `None`. "Words only" barge-in is SEMANTIC + `PhraseBackchannelDetector`; with a non-streaming (Whisper-type) STT it keeps `cut_without_words` on, or nothing could interrupt
- A turnless STT (Azure MAI-Transcribe) only finalises when the client commits: without a pipeline VAD no transcript ever comes. `stt_needs_turn_vad` gives it one — the chosen VAD model, else an energy VAD
- Cached local TTS (`tts._CACHED`): a factory built from more than (provider, model, device) declares `cache_fields(settings)` in its `tts/` module (`tts_cache_fields`; Pocket does), or a changed voice keeps the old instance. Qwen3/NeuTTS add their reference clip in `engine_vc._tts_cache_key`
- Recording sets `storage_encrypted_at_rest=True`: roomkit's only switch for plain WAVs, recorded as a storage choice — not a claim about the disk. The UI says the files are unencrypted

### Wake word
- The shared mic source runs only while the wake word is enabled; otherwise the engine's capture source is cleared and sessions open the device themselves. `wakeword/controller.py` owns that lifetime
- Heavy work (whisper encoder, DTW) goes through `wakeword/jobs.py`'s `SerialWorker`, never the Qt thread. A capture recreates its queues on each start, and never closes the device from inside the drain (`stream.stop()` there deadlocks the UI)
