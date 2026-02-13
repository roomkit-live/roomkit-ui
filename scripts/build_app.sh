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
    [[ -f assets/icon.icns ]] && EXTRA_ARGS+=(--icon=assets/icon.icns)
elif [[ "$OSTYPE" == "linux"* ]]; then
    [[ -f assets/icon.png ]] && EXTRA_ARGS+=(--icon=assets/icon.png)
fi

echo "==> Running PyInstaller..."
uv run pyinstaller \
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
    --hidden-import=aec_audio_processing \
    --collect-binaries=aec_audio_processing \
    --hidden-import=pynput \
    --hidden-import=pynput.keyboard \
    --hidden-import=pynput.keyboard._darwin \
    --add-data "src/roomkit_ui${SEP}roomkit_ui" \
    src/roomkit_ui/__main__.py

# macOS: patch Info.plist and re-sign
APP_PLIST="dist/RoomKit UI.app/Contents/Info.plist"
if [ -f "$APP_PLIST" ]; then
    /usr/libexec/PlistBuddy -c \
        "Set :CFBundleIdentifier com.roomkit.ui" \
        "$APP_PLIST" 2>/dev/null || true
    /usr/libexec/PlistBuddy -c \
        "Add :NSMicrophoneUsageDescription string 'RoomKit UI needs microphone access for voice conversations.'" \
        "$APP_PLIST" 2>/dev/null || true
    echo "==> Patched Info.plist (bundle ID + mic permission)"
    codesign --force --deep --sign - "dist/RoomKit UI.app"
    echo "==> Re-signed app bundle"
fi

echo "==> Build complete: dist/RoomKit UI"
