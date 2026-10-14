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

To try a roomkit change before its release, `--with-editable` overlays the checkout
next door (`../roomkit`) for one command. Use `--no-sync` to preserve optional backends
and custom wheels in the existing environment; this does not update the project's
dependency declaration. Omit `--with-editable` to use the installed RoomKit version.

```bash
uv run --no-sync --with-editable ../roomkit python -m roomkit_ui
QT_QPA_PLATFORM=offscreen uv run --no-sync --with-editable ../roomkit pytest -q
```

`all` leaves five extras out. `qwen3-tts`, `neutts` and `smart-turn` pin conflicting
`transformers` versions: they are declared in `[tool.uv].conflicts`, mirrored by
`features.EXCLUSIVE_EXTRAS` (a test keeps the two equal), and at most one goes in an
environment. `pocket-tts` and `vui` stay out because they pull torch; `vui` installs on
Python 3.12 only (`Feature.python_below`).

## Architecture

Entry point: `src/roomkit_ui/app.py` → `roomkit_ui.app:main`

```
src/roomkit_ui/
├── __main__.py          # `python -m roomkit_ui` → app.main
├── app.py               # Startup: graphics env (before PySide6), --doctor, QApplication + qasync, tray, hotkeys, wake word
├── macos_app.py         # Cached camera-only macOS bundle and usage declaration; original Python untouched
├── camera_capture.py    # Isolated photo window entrypoint; pipe to parent, no settings or secret access
├── constants.py         # UI-independent constants (attitude presets, …)
├── features.py          # Optional-backend registry: extras ↔ import probes ↔ install commands, EXCLUSIVE_EXTRAS, --doctor
├── components.py        # One extra = one component; install_plan(): app runs uv/pip, checkout gets `uv sync`, frozen nothing — leaf
├── component_installer.py # The app's one installer (QProcess, no shell), restart_app()
├── engine.py            # Engine shell: start task / stop, state machine, model cache, kit build, ordered teardown
├── engine_state.py      # EngineState StrEnum — leaf
├── engine_text.py       # Typed turns: AIChannel + in-process delivery, streaming, no audio — mixin
├── text_chat.py         # Local composer readiness check for the configured conversation LLM
├── images.py            # Bounded image import/normalization and self-contained attachments
├── image_messages.py    # RoomKit CompositeContent and recent image context when resuming
├── image_generation.py  # Images the assistant draws: providers, generate_image tool, drawing → chat image
├── engine_vc.py         # Voice Channel start (STT → LLM → TTS) — mixin
├── engine_vc_helpers.py # Stateless VC builders: barge-in, TTS filter, Smart Turn, local LLM
├── vc_stt.py            # VC cloud STT builders (dispatch table) + the turn VAD a turnless STT needs
├── audio_tags.py        # Tags a VC TTS performs ([whispers]) and the prompt section handing them over — leaf
├── vc_agent.py          # VC agent from the Agent tab: speak policy (classifier), thinker, background work + its model
├── session_models.py    # Display-only model inventory from resolved VC/Realtime backends; explicit safe fields
├── agent_hooks.py       # VC decision logs, background-task chat notices and running-task count
├── speaker_roster.py    # Voices Muse tells apart + their names, the user's voice, primary gate, prompt note — leaf
├── speaker_naming.py    # Muse speaker hook, name_voice (chat click), name_speaker tool, per-turn speaker note
├── engine_realtime.py   # Realtime start: media per attempt, no-MCP retry, channel — mixin
├── realtime_providers.py # Realtime builders + config (Gemini, OpenAI, GPT-Live, Deepgram, ElevenLabs, xAI), transport_audio_profile
├── engine_audio.py      # Pipeline builders: AEC, denoiser, VAD, diarization, recorder, DSP_THREADS, shared-mic rate
├── call_mode.py         # Join a call: the app recording from RoomKit Microphone, CallAudioBackend, CallRelay
├── engine_callbacks.py  # Realtime provider callbacks → Qt signals — mixin
├── engine_tools.py      # Tool dispatch (engine built-ins → built-ins → CLI → MCP), attitudes, paste — mixin
├── tool_events.py       # ToolCall / ToolResult, matched by invocation ID — leaf
├── toolset.py           # Tool grouping (builtin/cli/mcp), channel_options(), reachable_mcp_tools — leaf
├── builtin_tools.py     # Built-in tools (always available)
├── hooks.py             # RoomKit hook registration for UI events (VC + realtime)
├── watchdog.py          # Unanswered-speech detector (8 s) + model nudge
├── idle_hangup.py       # Hangs up a session gone quiet (set on the Wake Word page, any session)
├── cleanup.py           # qasync timer/FD cleanup after MCP disconnect, registered_fds()
├── memory.py            # Room-scoped SQLite store, fenced resume context, recall_conversations tool
├── conversations.py     # Local catalogue + display snapshots; one RoomKit room per thread
├── conversation_titles.py # Bounded title summary through the configured text provider
├── aec_dump.py          # AEC dump for roomkit's offline bench (ROOMKIT_AEC_DUMP=<dir>, realtime only)
├── cli_tools.py         # CLI tool manager: schema build + dispatch (mirrors MCPManager)
├── cli_exec.py          # Child-process primitives: PATH/env, Popen registry, timeout
├── cli_help.py          # Recursive `--help` probing (Click/Typer/Rich + Cobra), cached per binary mtime
├── cli_tools_config.py  # CLI tool config parsing + validation (mirrors mcp_config.py)
├── env_config.py        # `KEY=VALUE` env block parsing (MCP servers + CLI tools) — leaf
├── mcp_manager.py       # MCP client manager (stdio, SSE, HTTP transports), the instructions each server publishes
├── mcp_config.py        # MCP server config parsing helpers
├── mcp_http_auth.py     # Explicit None/Bearer/raw/Basic/OAuth form mapped to protected headers
├── mcp_auth.py          # OAuth2 for MCP HTTP servers; tokens bound to the server URL
├── mcp_skills.py        # Skills MCP servers publish (SEP-2640): a session as roomkit reads a server, labels, notices
├── mcp_app_bridge.py    # MCP Apps JSON-RPC bridge (QWebChannel ↔ iframe)
├── url_policy.py        # Public-host policy for MCP App requests and links
├── paths.py             # The one data dir per platform + the one-time macOS move off ~/.local/share
├── stt_engine.py        # Dictation lifecycle (DictationState) + paste
├── stt_sessions.py      # Dictation session bring-up per provider — mixin
├── dictation_stream.py  # Finite STT stream over public RoomKit capture/provider APIs
├── hotkey.py            # Global hotkey (NSEvent on macOS, pynput fallback)
├── paste.py             # Clipboard + paste keystroke per platform (paste_into_focused)
├── paste_windows.py     # Windows clipboard + Ctrl+V through Win32 SendInput (ctypes)
├── tray.py              # System tray icon for dictation
├── sounds.py            # Session start/stop and dictation sounds, through sounddevice (never QSoundEffect)
├── speaker_manager.py   # Speaker profile JSON persistence (<data dir>/speakers)
├── enrollment.py        # Speaker embedding recording/extraction (sherpa-onnx)
├── model_catalog.py     # Downloadable local models + on-disk locations
├── model_download.py    # Download plumbing: raw GitHub, Git LFS (oid-checked), release assets; 30 s timeouts
├── gguf_models.py       # llama.cpp models from Hugging Face: search, repo files, HF-cache downloads, resolve, fit — leaf
├── model_manager.py     # Download/delete entry points per model kind (edge-ai-models)
├── download_flight.py   # One download per model across Settings dialogs — leaf
├── skill_manager.py     # Skill source dirs, discovery, SkillRegistry build
├── skill_approval.py    # The user's yes before a CLI tool runs for a skill an MCP server serves — leaf
├── skill_git.py         # git clone/pull/remove for skill sources (isolated git runner)
├── skill_well_known.py  # skills.sh well-known installer (https only, byte caps)
├── skills_sh_client.py  # skills.sh public search client
├── settings.py          # QSettings persistence (~150 keys), defaults, migrations
├── settings_secrets.py  # Keyring hand-off: API keys, MCP OAuth secrets, MCP/CLI env secrets
├── secret_store.py      # SecretStore: OS keyring, QSettings fallback
├── icons.py             # Heroicons SVG rendering
├── theme.py             # Dark/Light theme stylesheets
├── providers/           # LLM factories, lazy registry: anthropic, openai, gemini, local (vLLM/Ollama), llamacpp;
│                        #  llm_settings(): a role's own model (background tasks, text chat) over Think · LLM's
├── tts/                 # TTS factories, lazy registry: piper, qwen3, neutts, pocket, vui, gradium, elevenlabs, azure, gemini, _util
├── wakeword/            # controller (shared mic + listener lifetime), listener, capture (mic → VAD → segments),
│                        #  resample, jobs (SerialWorker), detector, features (whisper encoder), dtw, fingerprint,
│                        #  enroller, encoder_download, page_sensitivity
└── widgets/
    ├── main_window.py     # Main window layout + Engine↔UI signal wiring
    ├── conversation_home.py # Compact welcome, violet background + history header
    ├── conversation_history.py # Thread selection, autosave, titles and legacy import
    ├── conversation_drawer.py # Full-width sliding thread list, search and New conversation
    ├── navigation_brand.py # Shared RoomKit wordmark for Settings and conversation navigation
    ├── sliding_panel.py   # Shared panel shell, animation, focus and theme; one overlay at a time
    ├── conversation_composer.py # Text send/stop + Live / cancel / end / mute
    ├── composer_dictation.py # Shared STTEngine → draft at cursor, no clipboard or automatic send
    ├── message_input.py    # Draft grows to eight visual lines, then scrolls; Shift+Enter newline
    ├── menus.py            # Shared rounded popup style, themed action icons and composer anchoring
    ├── image_attachments.py # File/clipboard/drop previews, remove/open, camera entry point
    ├── camera_dialog.py    # Permission, still-photo review and camera lifetime; optional Qt media
    ├── camera_process.py   # Source macOS camera process, bounded image reply, cancel/exit cleanup
    ├── chat_view.py       # Scrollable chat transcript
    ├── chat_bubble.py     # One chat entry: user bubble, typeset assistant text
    ├── tool_activity.py   # Compact tool state, optional plain-text details and inline MCP output
    ├── session_loading.py # In-layout startup progress; Cancel stays in the composer
    ├── mcp_app_widget.py  # MCP App widget (QWebEngineView, text fallback)
    ├── mcp_app_web.py     # QtWebEngine request filter + page
    ├── mcp_app_server.py  # 127.0.0.1 server + CSP for MCP App content
    ├── mcp_app_wrapper.py # Wrapper page: QWebChannel bridge + app iframe
    ├── vu_meter.py        # Compact violet waveform; mic mute preserves playback activity
    ├── session_info.py    # Minimal Live header with history and session-panel actions
    ├── session_drawer.py  # Active models by role, usage and searchable tools/skills; live updates
    ├── hotkey_button.py   # Interactive hotkey capture widget
    ├── dictation_log.py   # Dictation event log window
    ├── wakeword_wizard.py # Guided wake-word enrolment
    ├── voice_name_dialog.py # "Who is this?" when a voice's name is clicked in the chat
    ├── skill_approval_dialog.py # "Allow this skill to run programs?", non-blocking, Refuse by default
    ├── install_offer.py   # "<X> is not installed. [Install]" under a provider combo and in the chat
    └── settings/          # Resizable settings workspace (panel.py); page_registry.py owns IDs,
                           #  groups, factories and refresh hooks; navigation.py renders the sidebar.
                           #  controls.py (sections, forms, feedback), appearance.py and style.py
                           #  are shared UI building blocks;
                           #  choice_cards.py provides accessible mode cards;
                           #  pipeline_summary.py reflects the selected STT/LLM/TTS providers.
                           #  conversation_page.py owns voice_setup.py, text_chat_setup.py and the
                           #  personality editor; llm_fields.py is THE LLM picker (LLMFields, LLM
                           #  catalogs, reasoning) for Think · LLM, the Agent tab's tasks and Text
                           #  chat; model_combos.py shares the model/choice dropdowns;
                           #  images_setup.py is the Images tab;
                           #  llm_library_page.py is Models & components → LLMs (GGUF downloads);
                           #  audio_page.py owns audio_processing.py and speakers_page.py.
                           #  providers_page.py owns every shared provider credential; privacy_page.py
                           #  owns memory and session recording. diagnostics_page.py groups
                           #  recordings_page.py (file browser and owned media player),
                           #  audio_capture_page.py (debug taps) and telemetry_page.py (OTLP).
                           #  library_page.py groups models_page.py and components_page.py;
                           #  model_library.py describes each model kind's file operations;
                           #  model_jobs.py owns download progress for the application.
                           #  integrations_page.py groups skills/, mcp_page.py and cli_tools_page.py,
                           #  with tool_search_section.py below their tabs;
                           #  integration_controls.py shares searchable lists and detail views.
                           #  Other pages: dictation, wakeword, about. Voice parts:
                           #  realtime_section, realtime_catalogs, realtime_gemini_live, realtime_gpt_live,
                           #  vc_local_fields, vc_cloud_fields, vc_azure_fields, vc_meta_fields, vc_google_fields,
                           #  vc_agent_fields;
                           #  also models_widgets, speakers_dialogs, speakers_muse, feature_hints
```

Engine composition: `Engine(CallbackMixin, ToolMixin, RealtimeMixin, VoiceChannelMixin, TextMixin, QObject)` —
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
- Style menus through `QProxyStyle.polish`, including Qt-created editor menus. Never use an application-wide Python event filter for this: PySide can wrap a partially constructed WebEngine QObject (`QWebEngineUrlRequestJob`) and crash before the filter body runs. WebEngine integration tests must install the production menu style as well as the application QSS.
- The graphics environment is decided by `app._graphics_env()` and applied BEFORE PySide6 is imported. The OpenGL probe runs on Linux only (macOS/Windows render through Metal/Direct3D and ship no libEGL); only without OpenGL does it set `QT_QUICK_BACKEND=software`, `LIBGL_ALWAYS_SOFTWARE=1` and Chromium's GPU-off flags
- Never pass `--disable-web-security` to Chromium: it is process-wide, and MCP Apps rely on the same-origin policy (with `url_policy`) to keep local and LAN services out of reach
- Qt signals in async callbacks: always wrap emit() in try/except — the C++ object may be deleted
- The theme alone saves and applies immediately through `theme_live.apply_theme`; other Settings edits save in `done()` on every way out (Esc included). The dialog is destroyed after closing. Work that outlives it (downloads, OAuth, skill installs) must check its widget still exists. Provider credentials are edited only in `ProvidersPage`; each persisted setting has one page owner. Do not add duplicate key fields or temporary secret aliases
- Live palette styles use `theme_live.themed_style(widget, lambda c: ...)`; callbacks are parented to their widget and replaced on state changes. Do not rebuild pages to switch themes or cache a palette for later rendering. Search metadata lives in `PageSpec.search`; it contains labels, aliases and control paths, never entered values.
- Models & components keeps the `models` page ID; its two tabs own model files and optional dependencies separately. `model_jobs.ModelDownloads` owns async download tasks for the application; pages subscribe through Qt slots so destroying one disconnects its updates. Keep the late-progress guard and backend `download_flight` deduplication. Refresh/filter/theme changes must not start work or rebuild rows. `ComponentInstaller.last_result` keeps the outcome and restart action when Settings reopens.
- Integrations owns the four saved slices for Skills, MCP and CLI; its child views stay alive across tab switches. List filtering hides rows without changing configuration indices. OAuth snapshots credentials before scheduling work and binds feedback to server ID + URL. Git source feedback belongs to its URL, so completion never reports success on another source being edited. An enabled integration or stored token does not establish a working connection.
- Dictation retains unavailable model IDs as labelled choices. Wake Word shares `model_jobs` and model rows with the library; no page-owned download task. Opening its page supplies pending audio/provider values to the recording wizard. Refresh may disable activation when prerequisites are absent, but must preserve its checked value and allow switching an unavailable feature off. Recording/forgetting a phrase changes its file immediately; other preferences save on close.
- Secrets go through `settings_secrets.py` (keyring via `SecretStore`): API keys, MCP OAuth client secrets, every header value of an MCP HTTP server, and secret-looking env values of MCP servers AND CLI tools. Never write one to QSettings directly, and never log a header line (`invalid_header_lines` counts them)
- MCP HTTP auth fields compile to the existing secret `Authorization` header via `mcp_http_auth.HTTPAuthentication`; do not add duplicate plaintext credential fields. Legacy headers populate explicit auth methods. None removes manual Authorization and its secret; OAuth owns Authorization and keeps only additional headers.

### Session lifecycle
- `MainWindow._stt` is shared by the composer and global dictation. `start_input()` fixes the destination before scheduling capture; only `draft_ready` goes to the composer, never the `text_ready` paste/log path. Keep `busy` true through final transcription AND device cleanup; it gates sending/navigation/Live and wake word. Cancel suppresses pending text, including during startup; app shutdown awaits cleanup. Draft OpenAI sessions commit manually (VAD off, language in provider_config). Local streaming models and Deepgram use `DictationStream` over public RoomKit capture/provider APIs: Stop drains captured frames then sends EOF, without waiting for silence. Offline models use `VoiceChannel.flush_stt()`. Warm local models before capture; reuse the streaming model across completed dictations with unchanged settings, but create a fresh decoder stream each time. Invalidate the cache after cancellation because native decoding may still be running; await native warmup before finishing a cancelled start. Never read/restore frontmost application focus for a draft.
- One microphone session per voice channel, the app's own: roomkit's `LocalAudioBackend` declares `auto_connect`, so `attach_channel` would join a session and start the mic before the app opens its own (`_listen`: replay mark, mute before the first frame). Build every local backend a `VoiceChannel` uses with `engine_audio.local_audio_backend()` (it opts out) — two sessions mean every sentence heard, answered and spoken twice
- qasync installs no async generator hooks: `app.install_asyncgen_hooks()` does, right after the loop is created. Without them a generator left with `break` (roomkit's continuous STT, to drop an echo) is closed by the GC, its `finally` cannot await, and a streaming STT's websocket stays open
- `start()` claims CONNECTING before its first await and runs the start as its own task (`_start_task`); `stop()` publishes STOPPING, cancels that task and tears down once it has unwound. A failed start goes STOPPING → cleanup → ERROR (`_fail_start`). A stop before the kit exists closes the transport/backend itself (`_close_unowned_backends`)
- Typed turns and background tasks may run on a model of their own (Text chat tab, Agent tab → Tasks run on): read a role's model through `providers.llm_settings(settings, role)`, never `vc_llm_provider` directly — it names the provider, puts the role's fields (`text_*`, `vc_background_*`) over Think · LLM's, and gives it its own reasoning (empty: the model's default, never Think · LLM's, set for spoken replies). Readiness (`text_chat_unavailable`), the start and the factory's llama.cpp `role=` all go through it Every place an LLM is chosen builds `llm_fields.LLMFields` (provider, model, reasoning, local/llama.cpp fields): a field added to one place goes in the component, never beside it
- Images shared while Live (the composer's image button, file or camera) never become a draft: `images_shared` → `Engine.share_images`. Voice Channel: the user's turn, `process_inbound` on the "voice" channel as "local-user" (VoiceChannel.handle_inbound keeps the content), read by a model that sees. Realtime: `RealtimeVoiceChannel.inject_image`, silent but for the last. `_live_images_reason` (set at start: `supports_vision`, or the provider overrides `inject_image`) greys the button with the reason
- Text reply completion returns READY with the kit, provider and MCP Apps connected. The same thread/config reuses them and RoomKit's current-session memory; `cancel_response()` cancels only generation. `stop()` owns full teardown on navigation, Settings, Live or window close. A late MCP App resource belongs to the session, not the turn; it may arrive in READY, but never in a replacement session.
- Teardown order in `Engine._cleanup` is load-bearing (TTS before `kit.close()`, MCP after it, two loop yields before the FD pass); each step is a named method saying why
- qasync timer cleanup: after an MCP session closes, anyio leaves orphaned 0ms timers → 100% CPU. See `cleanup.py`. The end-of-session pass `cleanup_stale_fds(keep=...)` removes only FD notifiers registered since the session started (`registered_fds()` snapshot) — the app's own sockets (OAuth callback, downloads) survive
- A bound `CancelScope` callback is not proof of an orphan. Keep active `_timeout` deadlines and cancellation retries; remove a retry only for an inactive scope with no living owner or child tasks.
- MCP server stacks are closed in the task that opened them (anyio cancel scopes). Closing one from another task made anyio cancel the owner and hung `close_all()`

### Tools
- MCP App HTML (`app_html`) and app-initiated tool responses (`app_results`, `mcp_app_state.AppToolResults`) belong to the `ToolActivity` snapshot, alongside the original call and result. Some pages read their display data through `tools/call` (e.g. `get_screen_data`), so saving HTML and the model's text result alone is insufficient. Autosave changed responses per exact tool/input pair, scoped to the same widget, row and MCP manager after awaiting; repeated identical polls do not save again. History answers those requests from saved data with new request IDs; never reconnect MCP or repeat tools just to display history. End of session freezes app actions; navigation releases the view and HTTP content. Preserve saved data without WebEngine; old snapshots remain readable.
- MCP tool schemas: strip `$schema` and `additionalProperties` keys for Gemini compatibility (`_clean_schema()` in mcp_manager.py)
- MCP sessions open through `mcp_manager.negotiate_era` (`server/discover`, then the initialize handshake: mcp's own `Client(mode="auto")` policy), never `session.initialize()` alone: a server on the 2026 protocol (FastMCP 4, mcp 2.x) declares its extensions only there, so its skills never showed
- Skills an MCP server publishes go through roomkit's `SkillRegistry.add_mcp_server`, once the servers are connected (`_load_all_skills`, both modes), named `<label>:<path>` with the label from the server's name. Never fetch or inline a served skill's files in the app: roomkit verifies them against the listing and hands them to the model as the server's data. The CLI tools are the `execution_tools`: while a served skill is active, each asks the user (`SkillApprovals`, 60 s, then refused; roomkit keeps a yes per conversation and skill version). mcp 2.0's `send_request` takes only its `types.Request` and its `Result` drops unknown fields — `mcp_skills` sends and reads raw
- What an MCP server publishes on using its tools (`session.instructions`, from the handshake `negotiate_era` settled) reaches the model through roomkit's `server_instructions=` (0.99, RMK-692), never through the app's prompt: `MCPManager.instructions()` gives it by the server's label, `ToolSet.instructions` carries it, and `ToolSet.channel_options()` hands it to every channel built with MCP tools (Voice Channel, its background worker, typed turns, realtime). roomkit adds it to each prompt it composes, fenced and cut at 8192 characters with a warning — so `set_system_prompt`/`reconfigure_session` (an attitude, the memory recap) keep it once; writing it into `_base_system_prompt` would double it. Rebuild a `ToolSet` with `dataclasses.replace`, never field by field (the instructions would be lost). The no-MCP realtime retry (`ToolSet.without_mcp`) sheds it with the tools. Off per server through the entry's `instructions` key (`uses_instructions`, on by default)
- MCP session retry (realtime): retry with `ToolSet.without_mcp` (builtin + CLI) only when the provider refused the session config (`_refuses_session_config`: a ValueError, Gemini Live's 1007, Deepgram's "rejected Settings") — never on a bad key, the network or a quota. Each attempt runs on freshly built media (`_build_realtime_media`): a failed attempt's `kit.close()` closed the provider, the transport and its AEC. Only MCP is shed (server-supplied schemas), with its servers' instructions. Trigger on `ToolSet.has_mcp`, never on a tool-count comparison
- Every roomkit channel built with tools takes `**toolset.channel_options()`: since 0.95 roomkit bounds each tool call itself (10 s realtime, 30 s AIChannel) and Tool Search hides tools behind `find_tools` once the catalogue is large. The app keeps its own bounds (MCP 60 s, per-CLI-tool timeout) and pins the built-ins. When Tool Search turns on is the user's (Settings → Integrations → Tool search): `toolset.tool_search_options(settings, realtime=...)` goes beside `channel_options()` — a realtime channel takes only the mode and the tool count, an AIChannel the token budget and window share too. Automatic is off for a local Voice Channel LLM (`local_model=`, `LOCAL_LLMS`): every tool stays in its prompt. roomkit also refuses a tool name declared twice when it builds a realtime channel, so `_setup_tools` drops MCP tools named like a built-in/CLI tool or outside `[A-Za-z0-9_-]{1,64}` and says so in the chat
- A tool that fails raises `roomkit.ToolFailedError` (it ran and failed) or `ToolRefusedError` (nothing ran) — since roomkit 0.95 Gemini reads any returned body as a success. Two envelopes stay: `{"error": "Unknown tool"}` (roomkit reads it as "not served here") and the `{"error": ...}` an MCP App widget receives before the engine re-raises
- The Voice Channel's tools reach the AIChannel through `ToolSet.turn_config()` (its `config_provider`), never the binding's `metadata={"tools": ...}`: a background task runs the agent in a room attached without that metadata. Not the constructor's `tools=` either: it raises when a host tool is named like a skill or Tool Search tool (`list_tools`, `activate_skill`), where a turn config's tools are left out with a warning
- The speaking decision reads the Agent tab's Role (`vc_agent_role` → `ClassifierSpeakPolicy(agent_role=)`) with every turn. "What it is asked…" shows `vc_agent.speak_policy_brief`, written out from roomkit's own policy (`state()` on an example turn, its question objects, `compose`'s rules): never copy the questions into the app, they change with roomkit
- VC agent add-ons (`vc_agent.py`) never fail a start. An unavailable speaking policy is reported in session details and logs, not the transcript; other add-ons explain their absence in the chat. roomkit refuses a thinker without a speak policy, and closes neither the classifier nor the thinker — `Engine._close_vc_agent()` does, after `kit.close()`. Background tasks on a model of their own (any LLM provider) run on a second AIChannel (`BACKGROUND_WORKER`), `kit.setup_background(ai, worker=...)`: registered on the kit, never attached to the session room (it would answer every turn), its usage priced as its own model (`_accumulate_usage(task=True)`). `providers/llamacpp.py` keeps one server per role (`role=`), shared when two run the same GGUF and context: never stop a server another role still uses. A task's room (roomkit's `task_id` metadata) gets no `toolset.SESSION_TOOLS` (hang up, attitudes, voices' names, paste) from `ToolSet.turn_config()`, whichever model runs it
- Image generation (`image_generation.py`) is roomkit's ImageProvider surface (RFC §25), one engine tool for every mode: `_setup_tools` declares `generate_image` only when the Images tab's provider can run (installed, keyed), else the chat says why. A drawing reaches the chat through `Engine.image_generated` as an assistant entry (history keeps it). The model gets `drawing_result`: text (its id, size, dominant-colour palette, revised prompt) then a copy at most 768 px long; roomkit gives a model that does not see the text alone, and keeps the latest tool images in view on the next turns (RMK-708) — never put a drawing in an assistant message, which providers refuse an image in. `_handle_tool_call` returns a content-part list as is and shows its text in the tool row. Results go through `ImageAttachment.from_image` (PNG/JPEG, metadata stripped; Meta is asked for JPEG, as Qt may not read WebP). A paid generation is never retried: refused before billing → `ToolRefusedError`, failed → `ToolFailedError`, images billed before a failure are still shown. `edit` takes the drawing `image_id` names, else `ImageStudio.last`, the latest image drawn or shared. The Images tab's per-model settings come from `image_generation.image_controls` (roomkit's catalog `ImageCapabilities`; xAI's config, as its catalog declares none): `ImageOptions` through `generate_with_options`, xAI's through its config; a size the assistant names drops the shape and resolution (roomkit refuses both); a value the model does not take is never sent Its cost joins the session's only when roomkit prices the model (`_add_image_cost`)
- CLI tool schemas are hand-authored and never pass through `_clean_schema()` — so do NOT add `additionalProperties` to them, nothing would strip it and Gemini rejects it
- Tool names reaching a provider must be `[A-Za-z0-9_-]{1,64}` — no spaces, no dots. Don't push that rule onto the user: `cli_tools_config.slugify_tool_name()` derives it ("GitHub CLI" → `github_cli`) and the settings page shows the result. A declaration the model never receives must surface in the chat, not only in a log
- `cli_help.parse_subcommands()` covers Click/Typer, Rich boxes and Cobra (`gh` uses colon-suffixed names across several `* COMMANDS` sections). It is best-effort by design — a CLI with bespoke help (`git`, `brew`) seeds depth 1 and the model explores via `--help` through the tool. Test any parser change against `gh`, `kubectl`, `docker` AND a Rich/Typer CLI: the two ecosystems break each other
- Nothing in a CLI tool's shared description text may name a real subcommand — it is injected into *every* declared tool, so an example from one CLI is nonsense in another's (`_ARGS_HINT` in `cli_tools.py`)

### Child processes
- CLI tools: never `shell=True`, always an argv list. A macOS `.app` launched from the Dock inherits only `/usr/bin:/bin:/usr/sbin:/sbin`, and PyInstaller repoints `DYLD_LIBRARY_PATH` at `_MEIPASS` — both are handled in `cli_exec.child_env()`/`search_path()`, so spawn through there, not bare `subprocess`. MCP stdio servers resolve their command the same way
- No shell means the Command field is not one: `FOO=1 mycli` makes `resolve_command()` look for a binary literally named `FOO=1` and the whole tool gets dropped. Env vars go in the tool's Env field (`KEY=VALUE` per line, parsed by `env_config.parse_env_block`), same as an MCP server. They reach the `--help` probe too, so seeded help describes the CLI as configured
- git for skills runs through `skill_git` and drops `GIT_DIR` & co. (`_GIT_REDIRECTS`): an app started from a git hook or `rebase --exec` would otherwise act on that repository. Tests that run git must clear them too
- llama.cpp: roomkit spawns `llama-server` with a copy of the app's environment, PyInstaller's library path included; since 0.97.0 roomkit sets the host's own loader path back for it (`cli_exec` does the same for CLI tools). The server runs on its own thread and loop (`providers/llamacpp.py`) so it survives sessions and the end-of-session FD cleanup
- llama.cpp models (`gguf_models.py`): the app downloads into the Hugging Face hub cache, in its own layout (`blobs/<sha256>`, `snapshots/<commit>/<file>` linking it, `refs/main`) — the cache llama-server's `-hf` uses, so either one's downloads are listed. A session hands llama-server a downloaded `repo:quant` as its file (`providers.llamacpp.local_model` → `gguf_models.resolve`): no network at start, and llama-server never sees the Hugging Face token. The token is only for the app's own requests (Authorization to huggingface.co; httpx drops it on the redirect to the CDN). Each part is held to the listing's size and SHA-256 and confined to its snapshot folder (a file name from a listing is data). Whether a model fits is an estimate (`fit`: file + KV cache + margin against `machine().budget`) that warns, never refuses. Tests point `HF_HUB_CACHE` at a temp folder (conftest)

### Packaging
- Source macOS camera capture needs a bundle `NSCameraUsageDescription`. Only `camera_capture` re-execs through `macos_app`'s cached interpreter copy, preserving the venv via `__PYVENV_LAUNCHER__`. Never relaunch the main app this way: changing its executable identity triggers Keychain prompts for saved API keys. The helper must not import `settings`, `secret_store`, providers or the main app; use the supplied theme, and return the reviewed image through the bounded stdout pipe. Cancellation and stdin EOF close capture. Frozen apps use their own bundle and an in-process dialog. Never patch shared Python, change Keychain ACLs or reset TCC grants.
- A backend this install lacks is a state, not a fault: code that needs one calls `features.require(key)` (or checks `unavailable_reason`) BEFORE importing it, so it raises `FeatureUnavailableError` (which carries the feature key), never a raw ImportError. A session start catches it apart: one warning line, no traceback, `component_missing` → the chat's Install offer. An optional pipeline stage (denoiser, diarization, a VAD model) is left out with a chat notice instead of failing the start
- Installing a component (`components.py`, `component_installer.py`): only the app's own extras, pinned to the running version, argv without a shell; the app runs it only in a plain environment (pip, pipx, uv tool). A source checkout gets the `uv sync --inexact --extra` command (pip there would be undone by the next `uv sync`), a frozen build nothing. After an install `features.refresh()` drops the probe caches
- Adding a backend means three edits, not one: the extra in `pyproject.toml`, the `Feature` in `features.py`, and the provider→feature entry in the matching `*_FEATURES` map. An extra that conflicts with another also goes in `[tool.uv].conflicts` AND `EXCLUSIVE_EXTRAS`. Probe what the code path *imports*, not what the extra installs — the realtime providers ride a raw websocket and never touch the vendor SDK, so requiring it would block a session that works
- `RoomKit UI.spec` is gitignored and *regenerated* by every build — it is PyInstaller's output, not its input. The real flag lists live in `scripts/build_app.sh` and `.github/workflows/build.yml` (Unix + Windows steps); `tests/test_build_flags.py` fails when the three differ, so a flag goes in all three (`tiktoken_ext.openai_public` for GPT-Live, `--collect-binaries=aec_audio_processing`, which a Linux release once lost). All use `--collect-submodules=roomkit,roomkit_ui` because the backends load through string-keyed registries static analysis cannot follow
- `uv sync` with no extra installs the core, which has no AI backend at all. Anything that builds or ships the app must use `--extra all --extra smart-turn` (the builds add Smart Turn, whose transformers modules are hidden imports) — so frozen builds carry neither Pocket TTS, Qwen3-TTS nor NeuTTS

### Audio
- Meta Muse with speaker identification on (`vc_stt.labels_speakers`) labels the voices itself (`DIARIZATION`): the local identification does not run, and the labels hold only in roomkit's continuous mode — never give that session a pipeline VAD. The labels are per stream ("Speaker A", "Speaker A#1" after a restart) and name nobody: `SpeakerRoster` holds the names (`engine._speakers`, None otherwise)
- Speaker names are an authorization surface: with "Listen only to primary speaker", only the voice carrying the user's name reaches the assistant (and its tools), and it fails closed while none does. The assistant's `name_speaker` names from what it hears, so it never renames a voice the user named, never gives the user's name or a name another voice carries, and takes plain names only (they go into every turn's prompt). Keep those refusals when touching `speaker_naming.py`
- AEC wiring (realtime) is PER PROVIDER — mirror roomkit's example for that provider (`transport_audio_profile` in realtime_providers.py). Gemini/OpenAI Realtime/xAI/ElevenLabs: `aec` to `AudioPipelineConfig` ONLY (`LocalAudioBackend(aec=...)` flags NATIVE_AEC, the pipeline skips its AEC stage and loses the continuous playback reference — the 0.9.0 barge-in fix; `examples/realtime_voice_local_gemini.py`). Deepgram: `aec` to the TRANSPORT (inline on the PortAudio thread, sample-synchronous) + webrtc NS in the pipeline (`examples/realtime_voice_local_deepgram.py` — an open, poorly-aligned mic makes Deepgram transcribe its own voice and barge-in forever); `rt_prebuffer_ms=240` for Aura's bursts, with or without an AEC. GPT-Live: `aec` to the transport too + webrtc NS whether or not there is an AEC + the default 120 ms prebuffer (`examples/realtime_voice_local_openai_live.py`). No AEC at all mutes the mic during playback. VC mode still passes `aec` to both.
  A pipeline-stage AEC is passed as built: since roomkit 0.98 (RMK-678) the pipeline keeps it running between replies (`LocalAudioBackend` marks the silence it plays `reference_continues`). Paused at a reply's end, WebRTC AEC3 resumed misaligned for seconds and the provider heard itself and cut its own reply — never pause it from the app
- No user denoiser on the realtime mic path — speech enhancers keep the dominant voice and eat the user's barge-in during doubletalk. Denoisers are VC-mode only. The two exceptions mirror roomkit's examples: the mild WebRTC noise suppressor for Deepgram (with an AEC) and GPT-Live
- Realtime pipelines carry no VAD and no diarization (`_build_realtime_pipeline`). roomkit 0.97.0's RealtimeVoiceChannel forwards pipeline speaker changes at the provider's rate (0.96.1 did neither), but primary-speaker gating (`set_input_gated`) drops frames before the pipeline, and a pipeline VAD would take barge-in authority from the provider's server VAD (`_realtime_speech.py` early-returns). Diarization is Voice Channel only (`REALTIME_DIARIZATION_NOTICE`)
- The inbound DSP pool is ON (`DSP_THREADS = 1` in engine_audio.py, both modes): since roomkit 0.95 (RMK-392) the pipeline sends every stage callback back to its loop, in order. Before that, the pool dropped them (no mic audio, dead VU meter)
- `InterruptionConfig`: pass `InterruptionStrategy.DISABLED` explicitly, not `None`. "Words only" barge-in is SEMANTIC + `PhraseBackchannelDetector`; with a non-streaming (Whisper-type) STT it keeps `cut_without_words` on, or nothing could interrupt
- A turnless STT (Azure MAI-Transcribe) only finalises when the client commits: without a pipeline VAD no transcript ever comes. `stt_needs_turn_vad` gives it one — the chosen VAD model, else an energy VAD
- Cached local TTS (`tts._CACHED`): a factory built from more than (provider, model, device) declares `cache_fields(settings)` in its `tts/` module (`tts_cache_fields`; Pocket does), or a changed voice keeps the old instance. Qwen3/NeuTTS add their reference clip in `engine_vc._tts_cache_key`
- Notification sounds (`sounds.py`) play through sounddevice, never QtMultimedia's `QSoundEffect`: its `play()` holds the GIL down into CoreAudio, which waits for the output device's lock while a session's PortAudio callback holds that lock and waits for the GIL. The session-start sound plays once the session's streams run, and froze the whole app (sounddevice releases the GIL in PortAudio calls). The same goes for any other call into the audio system from the Qt thread
- Recording sets `storage_encrypted_at_rest=True`: roomkit's only switch for plain WAVs, recorded as a storage choice — not a claim about the disk. The UI says the files are unencrypted
- Join a call (`call_mode.py`, setting `join_call`): the switch turns the feature on, then nothing is to pick or switch. The call is the app recording from RoomKit Microphone (roomkit-devices' `list_virtual_microphone_apps`, a helper folded into its app), looked up at each Live start (`Engine._find_call`): found, the session joins it; none, Live is a conversation here as usual — never an error, the user must not switch the setting by hand. A call macOS will not let the app hear (audio capture denied) fails the start. A joined session builds roomkit-devices' `CallAudioBackend` instead of `LocalAudioBackend`: the assistant hears the call app and the mic, mixed, and speaks into RoomKit Microphone and the session's output (`monitor`: the user hears it too, cut with the call's). The user's voice reaches the call through `CallRelay` (MainWindow's, polled every second): open while the switch is on and a call records from RoomKit Microphone, session or not, closed otherwise so the mic is not held. RoomKit Microphone carries the sum of everything played into it, so a joined session relays nothing (`passthrough=False`) unless the relay could not open; `_find_call` polls the relay first. The mic button mutes the user for the assistant only (it still hears the call); the call button (`call_mute_toggled`, shown only in a joined session) mutes the user in the call only, and is reset when the session ends. RoomKit Microphone is no microphone for the app (it would hear itself): device lists leave out `virtual_microphone_name()`, the name read from the device, never a copy. A joined session runs with `aec_mode` "none" and the backend reports `NATIVE_AEC` (no half-duplex, no post-reply drain window): right in headphones; on speakers the mic hears the assistant (the notice asks for headphones). roomkit-devices is no dependency: runs overlay it (`uv run --no-sync --with-editable ../roomkit-devices python -m roomkit_ui`) and imports stay lazy

### Wake word
- The shared mic source runs only while the wake word is enabled; otherwise the engine's capture source is cleared and sessions open the device themselves. `wakeword/controller.py` owns that lifetime
- Heavy work (whisper encoder, DTW) goes through `wakeword/jobs.py`'s `SerialWorker`, never the Qt thread. A capture recreates its queues on each start, and never closes the device from inside the drain (`stream.stop()` there deadlocks the UI)
