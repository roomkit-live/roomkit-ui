#!/usr/bin/env bash
# Build a distributable app with PyInstaller.
# Usage: bash scripts/build_app.sh
#
# Produces:
#   macOS  → dist/RoomKit UI.app
#   Linux  → dist/RoomKit UI/  (one-dir bundle)
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> Installing dependencies..."
if command -v uv &>/dev/null; then
    uv sync
    uv pip install pyinstaller
else
    pip install -e ".[dev]"
fi

# OS-specific separator for --add-data
SEP=":"
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" || "$OSTYPE" == "win32" ]]; then
    SEP=";"
fi

EXTRA_ARGS=()
if [[ "$OSTYPE" == "darwin"* ]]; then
    EXTRA_ARGS+=(--windowed)  # .app bundle on macOS
fi

echo "==> Running PyInstaller..."
pyinstaller \
    --name "RoomKit UI" \
    --noconfirm \
    --clean \
    "${EXTRA_ARGS[@]}" \
    --hidden-import=google.genai \
    --hidden-import=google.genai.live \
    --hidden-import=openai \
    --hidden-import=websockets \
    --hidden-import=sounddevice \
    --hidden-import=_sounddevice_data \
    --hidden-import=roomkit.providers.gemini.realtime \
    --hidden-import=roomkit.providers.openai.realtime \
    --hidden-import=roomkit.voice.realtime.local_transport \
    --hidden-import=roomkit.voice.pipeline.aec.webrtc \
    --hidden-import=roomkit.voice.pipeline.aec.speex \
    --hidden-import=roomkit.voice.pipeline.denoiser.rnnoise \
    --hidden-import=certifi \
    --add-data "src/room_ui${SEP}room_ui" \
    src/room_ui/__main__.py

# macOS: add microphone usage description to Info.plist
APP_PLIST="dist/RoomKit UI.app/Contents/Info.plist"
if [ -f "$APP_PLIST" ]; then
    /usr/libexec/PlistBuddy -c \
        "Add :NSMicrophoneUsageDescription string 'RoomKit UI needs microphone access for voice conversations.'" \
        "$APP_PLIST" 2>/dev/null || true
    echo "==> Added NSMicrophoneUsageDescription to Info.plist"
fi

echo "==> Build complete: dist/RoomKit UI"
