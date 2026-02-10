#!/usr/bin/env bash
# Build a macOS .app bundle with PyInstaller.
# Usage: bash scripts/build_app.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> Installing build dependencies..."
pip install -e ".[dev]"

echo "==> Running PyInstaller..."
pyinstaller \
    --name "RoomKit UI" \
    --windowed \
    --noconfirm \
    --clean \
    --hidden-import=google.genai \
    --hidden-import=google.genai.live \
    --hidden-import=sounddevice \
    --hidden-import=roomkit.providers.gemini.realtime \
    --hidden-import=roomkit.voice.realtime.local_transport \
    --hidden-import=roomkit.voice.pipeline.aec.webrtc \
    --hidden-import=roomkit.voice.pipeline.aec.speex \
    --hidden-import=roomkit.voice.pipeline.denoiser.rnnoise \
    --add-data "src/room_ui:room_ui" \
    src/room_ui/__main__.py

# Add microphone usage description for macOS
APP_PLIST="dist/RoomKit UI.app/Contents/Info.plist"
if [ -f "$APP_PLIST" ]; then
    /usr/libexec/PlistBuddy -c \
        "Add :NSMicrophoneUsageDescription string 'RoomKit UI needs microphone access for voice conversations with Gemini.'" \
        "$APP_PLIST" 2>/dev/null || true
    echo "==> Added NSMicrophoneUsageDescription to Info.plist"
fi

echo "==> Build complete: dist/RoomKit UI.app"
