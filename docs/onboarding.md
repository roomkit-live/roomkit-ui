# Developer Onboarding

> _Generated: 2026-06-11 — re-run /project-review to update_

Goal: productive in under 30 minutes. Deeper context:
[architecture.md](architecture.md) · [technical.md](technical.md) · [features.md](features.md)

## Prerequisites

- **Python 3.12+**
- **[uv](https://docs.astral.sh/uv/)** — the only supported workflow
- **PortAudio** — included on macOS; `sudo apt install libportaudio2` on Linux
- An API key for at least one provider (Gemini, OpenAI, or Anthropic) — entered in the
  app's Settings UI, not in env vars
- Linux dictation extras: `xclip` + `xdotool` (X11) or `wl-copy` + `wtype` (Wayland)

## Setup

```bash
git clone https://github.com/roomkit-live/roomkit-ui.git
cd roomkit-ui
uv sync --extra dev          # runtime + ruff/mypy/bandit/pyinstaller
uv run python -m roomkit_ui  # launch the app
```

First run: gear icon → **AI Provider** → pick a provider, paste your API key → Save →
green call button → talk.

Optional but recommended for hands-free use:

```bash
uv pip install aec-audio-processing   # WebRTC echo cancellation
```

## Environment variables

None are required. Useful ones:

| Var | Effect |
|---|---|
| `DEBUG=1` | DEBUG-level logs for `mcp`, `roomkit`, realtime voice |

All real configuration (keys, models, devices, hotkeys) lives in the Settings dialog
and persists via QSettings. Logs go to the platform data dir (`~/.local/share/roomkit-ui/`
on Linux, `~/Library/Application Support/RoomKit UI/` on macOS).

## Quality checks (run before every PR)

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src/
uv run bandit -r src/ -c pyproject.toml
```

**There is no test suite yet** — CI runs exactly the four commands above
(`.github/workflows/ci.yml`). If you add logic that is testable without Qt
(see [technical.md — Testing](technical.md#testing-strategy)), add a pytest target with it.

## Common pitfalls

1. **`QT_QUICK_BACKEND=software` must be set before PySide6 is imported** — `app.py`
   does this at the top; never import PySide6 from a module that loads earlier.
2. **Qt signals in async callbacks**: always wrap `emit()` in `try/except` — the C++
   object may already be deleted (`SIM105` is disabled in ruff for this).
3. **Never touch roomkit private attributes directly** — use a public roomkit
   API. If one is missing, add it upstream in roomkit rather than reaching in.
4. **Teardown order in `Engine._cleanup` is load-bearing**: the engine closes TTS
   itself (skipping cached models) *before* `kit.close()`, and the channel is built
   with `close_providers=False` so `VoiceChannel.close()` skips STT/TTS (ElevenLabs
   double-close hang) while still closing the backend. Reordering re-introduces the
   hang and cross-session leaks.
5. **qasync timer leak**: after an MCP session closes, anyio leaves orphaned 0 ms
   timers → 100 % CPU. `cleanup.py` purges them; call it after any new disconnect path.
6. **Gemini tool schemas**: strip `$schema` / `additionalProperties` (done in
   `mcp_manager._clean_schema()`); Gemini silently refuses tools otherwise.
7. **`AudioPipelineConfig`**: pass `aec` + `denoiser` there AND `aec` to
   `LocalAudioBackend` — both are needed.
8. **`InterruptionConfig`**: pass `InterruptionStrategy.DISABLED` explicitly, not `None`.
9. **macOS permissions**: grant Microphone + Accessibility (for dictation paste) to your
   terminal when running from source.
10. **CUDA wheels**: `uv sync` reinstalls the CPU sherpa-onnx wheel; use
    `uv run --no-sync` to keep a manually installed CUDA wheel.

## Where to find what

| You want to… | Look at |
|---|---|
| Understand the system | [architecture.md](architecture.md) |
| Change a session mode / provider | `engine_vc.py`, `engine_realtime.py`, `providers/`, `tts/` |
| Add a tool | `builtin_tools.py` (builtin) or configure an MCP server |
| Touch teardown/cleanup | `engine.py:_cleanup`, `cleanup.py` |
| Add a settings field | `widgets/settings/<page>.py` + key in `settings.py` |
| Debug "model didn't call my tool" | `DEBUG=1`, and `ROOMKIT_GEMINI_DEBUG=1` (roomkit-side) |
| Build a release bundle | `./scripts/build_app.sh`, `.github/workflows/build.yml` |
| API/feature reference | [technical.md](technical.md), [features.md](features.md) |
