# Changelog

All notable changes to RoomKit UI are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
While the major version is 0, a minor bump carries features and behaviour changes
and a patch carries fixes.

Each released section is the source for that version's GitHub release notes.

## [Unreleased]

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
