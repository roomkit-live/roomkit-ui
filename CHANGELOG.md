# Changelog

All notable changes to RoomKit UI are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
While the major version is 0, a minor bump carries features and behaviour changes
and a patch carries fixes.

Each released section is the source for that version's GitHub release notes.

## [Unreleased]

### Added
- **Optional backends that report themselves** — `roomkit-ui --doctor` lists what an
  install carries and the command that completes it, on any console (a Windows cp1252 one
  included) and without touching a running app's log. Settings marks a provider whose
  backend is missing, and a session started with one names the install command in the
  chat.
- **PyPI and Homebrew** — a version tag publishes the wheel to PyPI (Trusted Publishing)
  and, for a notarized macOS build only, a cask:
  `brew install --cask roomkit-live/tap/roomkit-ui`.
- **Wake word** — say an enrolled phrase to open a session. Detection runs locally and
  compares sound to sound (whisper-tiny's encoder, DTW), so the phrase works in any
  language, and nothing leaves the machine until it fires. A guided wizard records the
  phrase normally, quietly and from a distance, then decoys that must not wake it;
  sensitivity is Cautious, Balanced or Responsive; the encoder (~12 MB) downloads from
  Settings → Wake Word. What is said right after the phrase reaches the provider. The
  listener stands down during sessions, dictation and while Settings is open, and the
  microphone is released when the wake word is off. New `wakeword` extra (in `all`).
- **The assistant decides when to speak** (Voice Channel, Settings → AI → Agent) — on
  each turn a classifier judges whether you finished, put it off, asked for quiet or
  spoke to it, and the assistant answers, offers one short sentence or stays quiet; the
  chat says why it stayed quiet. "Just listen" keeps it listening until spoken to by its
  name. The judgments come from OpenAI Decisions, TypeSafe Jev (new `typesafe` extra,
  in `all`) or the conversation model; one that cannot run leaves the assistant
  answering every turn and says so. Off by default: each reply waits for the decision.
- **The assistant thinks while it listens** (Voice Channel, with a speaking decision) — on
  the turns it stays quiet, the conversation model keeps a thought of what is said and
  what the assistant could add; with something worth saying it offers it. Its thoughts
  go to the log.
- **Background work** (Voice Channel, Settings → AI → Agent) — the assistant can hand a
  long request to a task that runs with the same model and tools while the conversation
  goes on, then speaks its result. The chat shows when a task starts and ends, and an
  idle session is not hung up while one runs.
- **Hang up when the conversation goes quiet** — optional, after a set delay (15 s by
  default), never during a tool call or while the assistant speaks; the chat says why
  the session closed.
- **Conversation memory** — sessions share a persistent history (roomkit's SQLite
  store, readable by its owner only). The Voice Channel's AI reads it as context,
  realtime providers get a recap of recent exchanges (fenced as a record, unheard answers
  left out), and a `recall_conversations` tool searches all of it. Settings → General →
  "Remember conversations across sessions", on by default.
- **Realtime: Deepgram Voice Agent, ElevenLabs Conversational AI and xAI Grok.**
  Deepgram exposes its STT model, a language picker, the think model, the TTS vendor it
  hosts (Aura, ElevenLabs, OpenAI) with voice and speed, and an opt-in half-duplex mode;
  xAI its server-VAD tuning.
- **Realtime: OpenAI GPT-Live** — a full-duplex voice that listens while it speaks and
  hands reasoning and tool calls to a backend model OpenAI hosts (gpt-5.6-terra by
  default). It uses the OpenAI key.
- **Gemini 3.8 Live options** — a thinking level for
  `gemini-3.8-live-extended-thinking`, transcription options for the family (language
  may change, language hints, custom vocabulary); options a 3.8 model refuses are
  disabled with the reason.
- **OpenAI Realtime reasoning effort and voice speed** in Advanced settings.
- **Agent Skills in realtime sessions**, as in the Voice Channel.
- **Usage in the session bar** — token counts in both modes, with a cost estimate in
  Voice Channel mode from roomkit's model pricing.
- **llama.cpp** as a Voice Channel LLM — a Hugging Face `repo:quant` or a `.gguf` file;
  roomkit downloads a pinned `llama-server` (SHA-256 checked) and the model at first use,
  and the server outlives sessions. New `llamacpp` extra (in `all`).
- **Pocket TTS** — Kyutai's local, CPU-friendly voice in seven languages, with voice
  cloning from a clip. New `pocket-tts` extra (outside `all`: it pulls torch).
- **Azure MAI-Transcribe and MAI-Voice** in the Voice Channel — Microsoft Foundry
  speech, one resource and one key for both. New `azure-speech` extra (in `cloud`).
- **Barge-in modes** (Voice Channel) — Off, Any speech, or Words only, where "ok",
  "mm-hmm" or "merci" let the assistant go on and other words stop it. The old checkbox
  migrates.
- **Clean speech** (Voice Channel) — the voice and the chat skip emoji, tool JSON the
  model wrote out, its notes to itself and stage directions; on an ElevenLabs model that
  performs audio tags, "[laughs]" still reaches it.
- **ElevenLabs streamed input** — each sentence is synthesized as soon as it is written
  (on by default; v4, v4 Turbo, v2 and v2.5). v4 and v4 Turbo join the model list, and
  v4 becomes the default model (v3 has no streaming; a saved v3 default moves to v4 and
  the chat says so once).
- **"Model thinking" for local LLMs** (vLLM / Ollama), off by default, so a reasoning
  model no longer thinks for seconds before a spoken reply.
- **`smart-turn` extra** — the Smart Turn detector's dependencies, outside `all` and
  shipped in the pre-built binaries. Without it the setting reads "not installed" and a
  session runs without the detector and says so. The detector stays loaded across sessions; "Unfinished Wait (ms)" sets how long an
  unfinished turn waits for more speech.
- **Voice failures in the chat** — a TTS or STT failure, and a turn the LLM could not
  answer (bad key, quota), say why in the chat instead of only in the log.
- **Loading curtain** — a full-window overlay with the current step and a Cancel button
  while a session connects.
- **AEC dump recorder** — `ROOMKIT_AEC_DUMP=<dir>` records what the realtime echo
  canceller sees, for roomkit's offline AEC bench.

### Changed
- **Breaking: `pip install roomkit-ui` installs the core only** — the window, the
  microphone pipeline with WebRTC echo cancellation, MCP and CLI tools, and no AI
  backend. Each backend is an extra (`anthropic`, `openai`, `gemini`, `deepgram`,
  `elevenlabs`, `gradium`, `azure-speech`, `local-voice`, `llamacpp`, `dictation`,
  `wakeword`, `mcp-apps`, `telemetry`; `cloud` and `all` group them), and
  `pip install 'roomkit-ui[all]'` matches the pre-built binaries. `qwen3-tts`, `neutts`
  and `smart-turn` pin conflicting `transformers` versions and cannot share an
  environment; they and `pocket-tts` stay out of `all`. PySide6-Essentials replaces
  PySide6: QtWebEngine and QtMultimedia come with `mcp-apps`.
- **macOS: one data folder** — models, the wake word, recordings and debug audio join
  skills, speakers and conversations in `~/Library/Application Support/RoomKit UI`. What
  older versions left in `~/.local/share/roomkit-ui` moves there once at startup; a
  folder already at its new home is never overwritten.
- **roomkit `0.24.0` → `0.97.0`**, which brings the new providers, the model and voice
  catalogs, the conversation store and the shared microphone above. The app absorbs its
  behaviour changes: roomkit's own tool-call timeouts give way to the app's (MCP 60 s,
  each CLI tool its own), the built-ins stay declared when Tool Search activates, failed
  tool calls are raised so every provider reads them as failures (Gemini read a returned
  error as a success), an MCP tool whose name is taken or invalid is left out and named
  in the chat, and a Voice Channel turn the provider refuses transiently is retried twice.
- **mcp `1.x` → `2.0`.**
- **Model lists from roomkit's catalogs** — the realtime model and voice dropdowns (every
  Gemini Live voice, OpenAI's marin and cedar, Aura-2) and the Voice Channel's Claude,
  OpenAI and Gemini lists. A saved id outside the list is kept, never replaced.
- **New defaults** — Claude Sonnet 5.5 (Sonnet 4.5 and 4 retire on 2026-11-30 on the
  Claude API), Gemini 3.8 Flash for the Voice Channel (2.0 Flash left roomkit's
  catalog), and gpt-realtime-2.1 for OpenAI Realtime. A stored retired Claude or Gemini
  default moves once and the chat says so; a deprecated model the user picked is kept
  and flagged at each session.
- **Speaker attribution per utterance** (Voice Channel) — each utterance carries the
  voice heard longest over it, so in primary-speaker mode an unknown voice no longer
  inherits the primary speaker's name and gets answered. The model reads the speakers'
  names once several people talk.
- **Chat** — the assistant's text is typeset without a bubble and rolls out with its
  voice whatever the provider's transcript cadence; a barge-in completes it at once with
  an "— interrupted" mark; realtime replies stream in as partial transcriptions; new rows
  fade in.
- **The watchdog nudges unanswered speech, not silence** — a user pausing to think no
  longer gets the model apologising for connection trouble.
- **`end_conversation` fires only on an explicit goodbye** — a user saying they are off
  to eat no longer has the session ended on them.
- **The microphone's DSP runs off the Qt thread** — AEC, denoiser, VAD and diarization
  run on a roomkit worker thread in both modes, so a slow stage no longer stalls the UI.
- **Settings say what they do** — recordings are unencrypted WAV files, and speaker
  identification works in Voice Channel mode only.
- **Faster CLI tool start** — `--help` probes are cached for the app's lifetime and stop
  spawning at the byte cap (`gh` at depth 3: 215 processes on the first session start,
  now 51, and none after).
- **The focus ring shows for keyboard navigation only**, drawn without clipping.
- **Releases run CI first** — a tag ships nothing until lint, bandit, mypy, the tests and
  the Windows import check pass on that commit, and a tag that disagrees with the project
  version is refused. CI runs the locked ruff and bandit, and mypy against the project
  environment.
- Oversized modules split by responsibility (realtime provider builders, settings
  secrets, skills, MCP App widget, model downloads, the engine's start and teardown
  steps), with no behaviour change.

### Removed
- **Speaker diarization and primary-speaker mode in realtime sessions** — under roomkit
  0.96.1 they never worked there (no speaker label reached the app, and the audio reached
  the provider at the wrong rate). A realtime session with diarization enabled runs
  without it and says so; Voice Channel mode is unchanged.

### Fixed
- **Anthropic, Gradium, Qwen3-TTS, NeuTTS and Deepgram transcription work** — v0.2.1
  declared no dependency for them, so they were dead in every install, the binaries
  included. Each now has its extra.
- **A session with MCP servers no longer hangs in "stopping"** — each server is closed
  in the task that opened it.
- **Stopping a session that is still connecting stops it** — the audio device is
  released, and a failed start finishes its teardown before reporting the error.
- **The mute button silences the microphone in Voice Channel mode**, and a mute pressed
  while connecting holds once the session opens.
- **A session's end no longer cuts the app's other connections** — an MCP OAuth login,
  a skill install or a model download in progress.
- **A second session with diarization no longer fails at start.**
- **Session recording writes its WAV files again.**
- **A WebRTC echo canceller that cannot load no longer ends every session** — the
  session runs half-duplex and says so.
- **Linux release: the WebRTC AEC library is bundled** — the v0.2.1 Linux build shipped
  without it.
- **The realtime retry without MCP tools runs only when the provider refused them**, on
  freshly built audio — a transient error no longer disables MCP, and the retried session
  keeps its echo canceller.
- **The session's own TTS and cloud STT are closed at its end** — after a Piper session,
  an ElevenLabs or Gradium TTS kept its client, and so did every Gradium or Deepgram STT.
- **A new reference voice reaches Qwen3-TTS and NeuTTS** without restarting the app.
- **`set_attitude` no longer blocks on the keyring mid-conversation**, nor raises a
  Keychain prompt there.
- **The hint for a local model without tool support shows again.**
- **Esc no longer discards every change in Settings.**
- **An API key edited on any tab is the one saved**, an emptied one included; the copies
  of a shared key stay in sync as you type.
- **Settings keep the Voice Channel models** after a visit in realtime mode, keep a pick
  when its tab is revisited, and keep a saved model the dropdown does not list.
- **The Settings dialog is destroyed when it closes** — each open leaked the previous
  dialog with its pages and its audio-preview player.
- **Dropdown arrows are visible again**, and the skills marketplace buttons keep their
  style.
- **Dictation: a press while starting or stopping no longer races it** — the microphone
  no longer keeps streaming to a billed session while the tray says idle.
- **Paste on Windows** — dictation and the paste tool write the clipboard and type
  Ctrl+V through the Win32 API; they failed asking for xclip.
- **Paste on X11 tells terminals apart** — every window was taken for a terminal and got
  Ctrl+Shift+V. A refused paste keystroke is reported instead of "ok".
- **A modifier hotkey used in a chord no longer toggles** (Right-Cmd+C copied and toggled
  dictation); an unparseable hotkey is reported instead of crashing at launch.
- **Speaker enrolment records on the configured microphone**, not the system default.
- **MCP stdio servers find `npx`, `uvx` and `node` on a macOS Dock launch.**
- **An MCP server that pages its tool listing keeps all its tools** — only the first page
  was read.
- **CLI tools survive non-UTF-8 output, and a timed-out call no longer hangs on a held
  pipe**; on Windows the process tree is killed.
- **An MCP App whose session ended while it loaded is dropped** instead of raising on a
  later result; tearing a widget down no longer warns about a released profile.
- **The latest skills.sh search wins**, and an install survives the grid re-rendering.
- **Skills with a list-valued `name` or `license`** load with text values.
- **A failed skill re-clone keeps the installed skills.**
- **Model downloads give up on a stalled connection** (30 s), espeak-ng data is no longer
  taken as complete after a partial download, and a model downloads once even when
  Settings is reopened mid-download.
- **macOS and Windows render on the GPU again** — the OpenGL probe disabled it outside
  Linux. Linux no longer forces software GL when OpenGL works.
- **The released macOS app carries the project version and a stable bundle identifier**
  instead of PyInstaller's defaults.
- **The VAD speech pad placeholder shows roomkit's 1000 ms default.**

### Security
- **MCP Apps can no longer read local and LAN services** — `--disable-web-security` is
  gone, so the same-origin policy applies again, and a request or an opened link is
  judged on the host as a browser reads it: numeric IPv4 forms, CGNAT and private
  addresses embedded in IPv6 count as private, and a name must resolve only to public
  addresses.
- **CLI tool env secrets go to the keyring**, as MCP servers' do. More secret names are
  recognised (APIKEY, PAT, BEARER, PWD, PASSPHRASE, DSN, DATABASE_URL…), and a URL that
  carries credentials is a secret whatever its variable is called. Plain-text values an
  older version saved migrate on load.
- **A secret saved while the keyring was locked stays saved** — it no longer reverts to
  the previous value once the keyring unlocks.
- **MCP OAuth tokens are bound to the server URL they were issued for** — changing a
  server's URL no longer hands its tokens to the new host.
- **Temporary API-key fields are never persisted** — saving Settings could leave a copy of
  a key in plaintext QSettings.
- **Skill git runs safely** — through the app's child-process runner, with `--` before
  the URL, bounded in time, never prompting, never acting on an enclosing or inherited
  repository (`GIT_DIR` and friends are dropped).
- **Well-known skills are fetched over https only**, redirects included, with the
  per-file and per-skill caps enforced while streaming.
- **Downloads are checked** — Smart Turn and the wake-word encoder are pinned to a commit
  and a SHA-256, and every download is held to its announced size.
- **The CLI Tools page says what declaring a CLI grants** — any arguments the assistant
  chooses, run with the user's permissions, without asking.
- **The Homebrew cask is published only for a notarized app** (`xcrun stapler validate`).

## [0.2.1] - 2026-07-15

### Fixed
- **Windows: crash on startup** with `ModuleNotFoundError: No module named
  'resource'`. `cleanup.py` imported the Unix-only `resource` module at module
  scope, and `engine` imports `cleanup` on the way up, so a CPU-logging
  diagnostic took the whole app down before a window opened. The import now
  lives in the one function that uses it. Thanks @GeneraI44 for the report and
  the diagnosis ([#2](https://github.com/roomkit-live/roomkit-ui/issues/2)).
- **Windows: `AttributeError` when a CLI tool is killed.** `os.killpg` and
  `os.getpgid` are POSIX-only, so the lookup raised `AttributeError`, which the
  `OSError` catch around the call never covered. A CLI tool timing out, or a
  session tearing down with a child still running, hit it. Windows has no
  process group to signal — `start_new_session` is ignored there — so the
  child is killed on its own.

### Changed
- CI runs an import smoke test on `windows-latest`. Every other job runs on
  Linux, where both APIs above resolve, and the Windows artifact shipped
  unexecuted.

## [0.2.0] - 2026-07-15

### Added
- **CLI tools** — declare a local binary once in Settings → CLI Tools and the voice
  agent can run it. One tool per binary rather than one per subcommand: the binary's
  `--help` is probed and seeded into the tool description, so the model composes the
  argv itself. Click/Typer, Rich boxes and Cobra help layouts are parsed; a CLI with
  bespoke help still works and the model explores it through `--help`.
- **Environment variables for CLI tools** — a dedicated `Env` field (`KEY=VALUE`, one
  per line) for a CLI that needs one set. The command field is not a shell, so the
  `FOO=1 mycli` spelling never worked there. Variables reach the `--help` probe as
  well as dispatch, and the field reports the names it will set and calls out any
  line it ignored.
- **skills.sh marketplace search** and well-known source installation.

### Changed
- **Skills marketplace is skills.sh**, replacing ClawHub.
- **roomkit `0.10.0` → `0.24.0`**, consumed from PyPI, with all private-API reaches
  dropped.
- Tool grouping derives from each tool's source instead of being inferred from tool
  counts.

### Fixed
- `ON_TRANSCRIPTION` crash and a silent twin regression left by the partial 0.10.0
  migration: transcription hooks receive an event object, not a string.
- Wrong realtime-session retry, caused by a `has_mcp` boolean that a third tool
  source made lie.
- Flaky `hdiutil` DMG creation ("Resource busy") on GitHub macOS runners.

### Security
- **Secrets in the platform keyring** — API keys and OAuth tokens move to macOS
  Keychain, Windows Credential Manager, or Linux Secret Service, with an encoded
  QSettings fallback when no backend is usable.
- MCP server secrets and routing protected.
- MCP stdio config parsing hardened.
- MCP app web sandbox hardened, and MCP app tool calls restricted.
- Reduced sensitive default logging.

## [0.1.6] - 2026-06-11

### Added
- pytest suite and a CI test job.
- Project docs, and `uv.lock` tracked.

### Changed
- **roomkit `0.7.0a16` → `0.10.0`**.
- Oversized modules split along responsibility seams.
- Control-bar buttons made keyboard-accessible.
- Silent `except: pass` replaced with debug logs; `EngineState` enum introduced.

### Fixed
- Realtime barge-in: pipeline-only AEC, and no denoiser on the realtime mic path.
- Chat auto-scroll lag; MCP servers connect in parallel with a 10s timeout.
- Re-entrancy races, event-loop blocking, memory leaks, and resource cleanup.
- Invalid `QSG_RHI_BACKEND=sw` removed.

### Security
- Skill, model and MCP input paths hardened.

## [0.1.5] - 2026-02-24

### Added
- **Voice Channel STT/LLM/TTS tabs** — dedicated settings pages for each pipeline
  stage, with OpenTelemetry log suppression.
- **VAD advanced settings** — smart-turn detector UI and telemetry page.
- **Audio Debug page** — pipeline taps, recording controls, and file browser.
- **Speaker diarization** — enrollment UI, primary speaker mode, pipeline refactor.
- **Deepgram STT** for voice channel and dictation modes.
- **ElevenLabs TTS** for voice channel mode.
- **Gradium STT/TTS** with streaming chat bubbles and voice error surfacing.
- **ClawHub skills** integration, and **Agent Skills** for voice channel.
- **OAuth2 authentication** for MCP HTTP servers.
- **Attitudes** — shown in the session header, preserved across reconnects, with a
  `list_attitudes` built-in tool.
- **Gemini advanced settings** panel with `provider_config` passthrough.
- **OpenAI advanced settings** with a transport-based sub-module refactor.
- **`paste_text` tool** for agent-initiated text insertion.
- **`end_conversation` tool**; `set_attitude` restricted to known names.
- **Dictation sounds**, red dot badge, and L/R hotkey distinction.
- **macOS code signing and notarization**; sherpa-onnx bundled in the DMG, with
  generic modifier hotkeys via NSEvent.

### Changed
- **roomkit `>=0.6.0`** from PyPI.
- Package `room_ui` renamed to `roomkit_ui`.
- `settings_panel.py` split into a `widgets/settings/` package; `ai_page.py`
  refactored into transport-based sub-modules.

### Fixed
- Chat bubble `RuntimeWarning` on deleted Qt objects.
- Security, bug and resource-leak issues from code review.
- Migration from the deleted `LocalAudioTransport` to `LocalAudioBackend`
  (roomkit 0.5.0+).
- Paste from the bundled app, using AppleScript instead of CGEventPost.
- Crash on settings close caused by a pynput CGEventTap restart on macOS.
- macOS Accessibility permission request and error messaging; Accessibility and
  Input Monitoring are prompted for only on first launch.
- Skills card layout, model caching across sessions, and event-loop freeze.

## [0.1.4] - 2026-02-12

### Added
- **MCP Apps** — embedded MCP App UIs via `QWebEngineView` with a pill-shaped control
  button, and a JSON-RPC bridge for app-initiated tool calls back through MCP.
- **Global hotkey** to toggle the assistant session (NSEvent on macOS, pynput
  fallback), plus a tray status dot and notification sounds.
- Loading status messages during voice channel startup (STT, TTS, MCP, connect).
- Unified VU meter via audio level hooks, for both voice modes.

### Changed
- `engine.py` split into focused modules (`cleanup.py`, `hooks.py`,
  `builtin_tools.py`).
- Friendly error messages instead of raw WebSocket error codes, and an actionable
  message for audio interruptions.
- CODE_OF_CONDUCT, CONTRIBUTING guide and LICENSE added.

### Fixed
- JS errors from MCP Apps shown inline in the widget.
- CORS blocking MCP App ES-module imports from esm.sh.
- mypy errors across `mcp_app_widget.py`, `main_window.py`, `hotkey.py`,
  `model_manager.py`.

## [0.1.3] - 2026-02-11

### Added
- **Voice Channel mode (STT → LLM → TTS)** — local sherpa-onnx STT and TTS with text
  LLM providers (Anthropic Claude, OpenAI GPT-4o, Google Gemini), full tool calling
  for built-in and MCP tools, and a barge-in toggle.
- **Local AI models** — model manager with downloadable STT, TTS and VAD models,
  GTCRN denoiser support, and GPU/CPU inference device selection.
- Session info bar showing the active provider, model and tools.
- MCP server enable/disable and list navigation.
- Separate AI Models catalog page; settings auto-save on close.

### Fixed
- 100% CPU spin after MCP server hangup, and MCP subprocess leak on hangup/Ctrl+C.
- AEC + denoiser pipeline configuration, passed to both backend and pipeline.
- Hook registration (SYNC execution + `HookResult.allow()`).
- STT language/translate parameter passthrough, and batch STT flush.
- Tray click behaviour, and CI quality checks.

## [0.1.2] - 2026-02-10

### Added
- **MCP tool support** — built-in date/time tools and an extensible tool framework.
- **System-wide STT dictation** from any app.
- **Markdown rendering** in chat bubbles, and **dark/light theme** support.
- **Redesigned control bar** with single-key hotkeys.
- **macOS support** — AEC, clipboard paste, hotkey, file logging, codesigning.

### Changed
- Redesigned settings panel layout on macOS, and wider chat bubbles.
- pynput replaced with CGEventTap / NSEvent monitor for more reliable macOS global
  hotkeys.
- Assets moved into the package for reliable path resolution.
- SIGINT handled for clean Ctrl+C shutdown.

### Fixed
- Paste going to the wrong app — own process is no longer saved as frontmost.
- STT toggle getting stuck, and STT session cleanup leaving ghost VAD events.
- Cleanup race condition with the NSEvent monitor.
- Missing `type` field for OpenAI Realtime API tool definitions.
- Build script now uses `uv run` for pyinstaller; certifi added for macOS packaging.
- Engine errors surfaced in the UI.

## [0.1.1] - 2026-02-10

### Added
- App icon, ad-hoc codesigning, and macOS Gatekeeper documentation.

## [0.1.0] - 2026-02-10

### Added
- Initial release: RoomKit UI desktop voice assistant, with a cross-platform build
  script and a GitHub Actions workflow.

[Unreleased]: https://github.com/roomkit-live/roomkit-ui/compare/v0.2.1...HEAD
[0.2.1]: https://github.com/roomkit-live/roomkit-ui/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/roomkit-live/roomkit-ui/compare/v0.1.6...v0.2.0
[0.1.6]: https://github.com/roomkit-live/roomkit-ui/compare/v0.1.5...v0.1.6
[0.1.5]: https://github.com/roomkit-live/roomkit-ui/compare/v0.1.4...v0.1.5
[0.1.4]: https://github.com/roomkit-live/roomkit-ui/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/roomkit-live/roomkit-ui/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/roomkit-live/roomkit-ui/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/roomkit-live/roomkit-ui/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/roomkit-live/roomkit-ui/releases/tag/v0.1.0
