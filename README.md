# RoomKit UI

<p align="center">
  <img src="assets/logo.svg" width="80" height="80" alt="RoomKit UI">
</p>

A desktop voice assistant built with [PySide6](https://doc.qt.io/qtforpython-6/) and [RoomKit](https://github.com/roomkit-live/roomkit). Supports real-time voice conversations with **Google Gemini** and **OpenAI** realtime APIs.

![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)
![License MIT](https://img.shields.io/badge/license-MIT-green)

<p align="center">
  <img src="assets/screenshot.png" width="300" alt="RoomKit UI screenshot">
</p>

## Download

Pre-built binaries are available for macOS, Linux, and Windows on the [Releases](https://github.com/roomkit-live/roomkit-ui/releases) page.

### macOS

After downloading and extracting, macOS may block the app because it's not notarized. To fix this, open a terminal and run:

```bash
xattr -cr "RoomKit UI.app"
```

Then double-click the app to open it. You'll also need to grant microphone permission when prompted.

## Features

- **Dual provider support** — switch between Google Gemini and OpenAI from settings
- **Real-time voice** — full-duplex voice conversation with interruption support
- **Animated VU meter** — ambient glow visualization for mic and speaker audio levels
- **Chat transcript** — iMessage-style bubbles with markdown rendering and streaming transcriptions
- **System-wide dictation** — global hotkey triggers OpenAI STT and pastes text into the focused app
- **MCP tool support** — connect external tools via Model Context Protocol (stdio, SSE, HTTP)
- **Echo cancellation** — WebRTC or Speex AEC for hands-free use
- **RNNoise denoiser** — optional audio denoising for noisy environments
- **Audio device selection** — pick your microphone and speaker from settings
- **Dark & Light themes** — Apple-inspired UI with theme switcher
- **System tray** — tray icon with dictation status, quick toggle, and notifications
- **Multi-language STT** — 14+ languages for dictation (auto-detect, English, French, Spanish, etc.)

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- A Google API key (for Gemini) and/or an OpenAI API key
- PortAudio (`libportaudio2` on Linux, included on macOS)
- **Linux dictation deps** — `xclip` + `xdotool` (X11) or `wl-copy` + `wtype` (Wayland) for the system-wide STT dictation feature

## Run from source

```bash
git clone https://github.com/roomkit-live/roomkit-ui.git
cd roomkit-ui
uv sync
uv run python -m room_ui
```

For WebRTC echo cancellation (recommended):

```bash
uv pip install aec-audio-processing
```

## Usage

1. Click the gear icon to open **Settings**
2. Go to **AI Provider**, select your provider and enter your API key
3. Click **Save**, then press the green call button to start a voice session
4. Speak naturally — the AI will respond in real-time
5. Press the red button to end the session

## Project Structure

```
src/room_ui/
├── app.py              # QApplication + qasync event loop
├── engine.py           # Async engine bridging roomkit <> Qt signals
├── hotkey.py           # Global hotkey (NSEvent on macOS, pynput fallback)
├── icons.py            # Heroicons SVG rendering
├── mcp_manager.py      # MCP client manager (stdio, SSE, HTTP)
├── settings.py         # QSettings persistence
├── stt_engine.py       # STT dictation engine + text pasting
├── theme.py            # Dark & Light theme stylesheets
├── tray.py             # System tray icon for dictation
└── widgets/
    ├── main_window.py    # Main window layout
    ├── settings_panel.py # Tabbed settings dialog
    ├── chat_view.py      # Scrollable chat area
    ├── chat_bubble.py    # Chat bubble with markdown rendering
    ├── vu_meter.py       # Animated ambient glow VU meter
    ├── control_bar.py    # Call button + mic mute + settings
    ├── hotkey_button.py  # Interactive hotkey capture widget
    └── dictation_log.py  # Dictation event log window
```

## Building

```bash
./scripts/build_app.sh
```

Or generate icons and build manually:

```bash
pip install pyinstaller Pillow cairosvg
python scripts/generate_icons.py
pyinstaller --name "RoomKit UI" --windowed --icon=assets/icon.icns src/room_ui/__main__.py
```

## License

MIT License — Copyright (c) 2025 Sylvain Boily
