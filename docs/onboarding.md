# Developer Onboarding

> _Generated: 2026-06-11 — updated 2026-10-11 for roomkit 0.97.0 — re-run /project-review to update_

Goal: productive in under 30 minutes. Deeper context:
[architecture.md](architecture.md) · [technical.md](technical.md) · [features.md](features.md)

## Prerequisites

- **Python 3.12+**
- **[uv](https://docs.astral.sh/uv/)** — the only supported workflow
- **PortAudio** — included on macOS; `sudo apt install libportaudio2` on Linux
- An API key for at least one cloud provider (Gemini, OpenAI, Anthropic, …) — entered in
  the app's Settings UI, not in env vars. An all-local Voice Channel (local STT, Ollama or
  llama.cpp, Piper) needs none
- Linux dictation extras: `xclip` + `xdotool` (X11) or `wl-copy` + `wtype` (Wayland)

## Setup

```bash
git clone https://github.com/roomkit-live/roomkit-ui.git
cd roomkit-ui
uv sync --extra dev          # core + every backend in `all` + ruff/mypy/bandit/pytest/pyinstaller
uv run python -m roomkit_ui  # launch the app
uv run roomkit-ui --doctor   # which optional backends this environment carries
```

The core already includes WebRTC echo cancellation (`roomkit[webrtc-aec]`). `all` leaves
out `qwen3-tts`, `neutts`, `smart-turn` and `pocket-tts`; add at most one of the first
three (they pin conflicting `transformers` versions), e.g.
`uv sync --extra dev --extra smart-turn`.

First run: gear icon → **AI Provider** → pick a provider, paste your API key → close
Settings (it saves on close, Esc included; there is no Save button) → green call button →
talk.

## Environment variables

None are required. Useful ones:

| Var | Effect |
|---|---|
| `DEBUG=1` | DEBUG-level logs for `mcp`, `roomkit`, realtime voice |
| `ROOMKIT_AEC_DUMP=<dir>` | Record what the realtime AEC sees, for roomkit's offline AEC bench |

All real configuration (keys, models, devices, hotkeys) lives in the Settings dialog
and persists via QSettings. Logs go to `roomkit-ui.log`, rewritten at each launch, in
`~/.local/share/roomkit-ui/logs/` on Linux (`$XDG_DATA_HOME` if set) and
`~/Library/Logs/RoomKit UI/` on macOS.

## Quality checks (run before every PR)

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src/
uv run bandit -r src/ -c pyproject.toml
QT_QPA_PLATFORM=offscreen uv run pytest -q
```

CI runs these checks in `.github/workflows/ci.yml`, and again before any tag ships. If you
add logic that is testable without Qt, add a pytest target with it (see
[technical.md — Testing](technical.md#testing-strategy)).

## Common pitfalls

1. **The graphics environment is set before PySide6 is imported** — `app._graphics_env()`
   decides it at the top of `app.py`; never import PySide6 from a module that loads
   earlier. Never add `--disable-web-security` to the Chromium flags: MCP Apps rely on
   the same-origin policy.
2. **Qt signals in async callbacks**: always wrap `emit()` in `try/except` — the C++
   object may already be deleted (`SIM105` is disabled in ruff for this).
3. **Never touch roomkit private attributes directly** — use a public roomkit
   API. If one is missing, add it upstream in roomkit rather than reaching in.
4. **Teardown order in `Engine._cleanup` is load-bearing**: the engine closes the
   session's own STT/TTS (skipping cached models) *before* `kit.close()`, and the channel
   is built with `close_providers=False` so `VoiceChannel.close()` skips STT/TTS
   (ElevenLabs double-close hang) while still closing the backend. Reordering
   re-introduces the hang and cross-session leaks. A stop during CONNECTING cancels the
   start task first; the teardown never runs alongside it.
5. **qasync timer leak**: after an MCP session closes, anyio leaves orphaned 0 ms
   timers → 100 % CPU. `cleanup.py` purges them; call it after any new disconnect path.
   The end-of-session pass removes only the FDs the session registered.
6. **Gemini tool schemas**: strip `$schema` / `additionalProperties` (done in
   `mcp_manager._clean_schema()`); Gemini silently refuses tools otherwise. A tool that
   fails must raise `roomkit.ToolFailedError` / `ToolRefusedError`: Gemini reads any
   returned body as a success.
7. **AEC placement**: Voice Channel mode passes `aec` to both `AudioPipelineConfig` and
   `LocalAudioBackend`. Realtime mode decides per provider
   (`realtime_providers.transport_audio_profile`), mirroring roomkit's example for each.
8. **`InterruptionConfig`**: pass `InterruptionStrategy.DISABLED` explicitly, not `None`.
9. **Adding a backend**: the extra in `pyproject.toml`, the `Feature` in `features.py`
   and the provider's entry in the matching `*_FEATURES` map; `tests/test_features.py`
   catches a drift. A new PyInstaller flag goes in `scripts/build_app.sh` and both steps
   of `build.yml` (`tests/test_build_flags.py`).
10. **macOS permissions**: grant Microphone + Accessibility (for dictation paste) to your
    terminal when running from source.
11. **CUDA wheels**: `uv sync` reinstalls the CPU sherpa-onnx wheel; use
    `uv run --no-sync` to keep a manually installed CUDA wheel.

## Where to find what

| You want to… | Look at |
|---|---|
| Understand the system | [architecture.md](architecture.md) |
| Change a session mode / provider | `engine_vc.py`, `engine_vc_helpers.py`, `engine_realtime.py`, `realtime_providers.py`, `providers/`, `tts/` |
| Add an optional backend | `pyproject.toml` extras, `features.py` |
| Add a tool | `builtin_tools.py` (builtin), or declare a CLI tool / MCP server in Settings |
| Touch teardown/cleanup | `engine.py:_cleanup`, `cleanup.py` |
| Work on the wake word | `wakeword/` (start with `controller.py`), `widgets/wakeword_wizard.py` |
| Add a settings field | `widgets/settings/<page>.py` + key in `settings.py` (secrets: `settings_secrets.py`) |
| Debug "model didn't call my tool" | `DEBUG=1`, and `ROOMKIT_GEMINI_DEBUG=1` (roomkit-side) |
| Build a release bundle | `./scripts/build_app.sh`, `.github/workflows/build.yml` |
| API/feature reference | [technical.md](technical.md), [features.md](features.md) |
