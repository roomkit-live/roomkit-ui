# RoomKit UI

<p align="center">
  <img src="assets/logo.svg" width="80" height="80" alt="RoomKit UI">
</p>

A desktop voice assistant built with [PySide6](https://doc.qt.io/qtforpython-6/) and [RoomKit](https://github.com/roomkit-live/roomkit). Supports real-time voice conversations with **Google Gemini** and **OpenAI** realtime APIs.

![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)
![License MIT](https://img.shields.io/badge/license-MIT-green)

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
- **Chat transcript** — iMessage-style bubbles with streaming partial transcriptions
- **Echo cancellation** — WebRTC or Speex AEC for hands-free use
- **Audio device selection** — pick your microphone and speaker from settings
- **Dark theme** — Apple-inspired dark mode UI

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- A Google API key (for Gemini) and/or an OpenAI API key
- PortAudio (`libportaudio2` on Linux, included on macOS)

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
├── icons.py            # Heroicons SVG rendering
├── settings.py         # QSettings persistence
├── theme.py            # Dark theme stylesheet
└── widgets/
    ├── main_window.py  # Main window layout
    ├── settings_panel.py # Tabbed settings dialog
    ├── chat_view.py    # Scrollable chat area
    ├── chat_bubble.py  # iMessage-style bubble widget
    ├── vu_meter.py     # Animated ambient glow VU meter
    └── control_bar.py  # Call button + mic mute + settings
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
