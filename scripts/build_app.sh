#!/usr/bin/env bash
# Build a distributable app with PyInstaller.
# Usage: bash scripts/build_app.sh
#
# Produces:
#   macOS  → dist/RoomKit UI.app  (signed + notarized if env vars set)
#   Linux  → dist/RoomKit UI/  (one-dir bundle)
#
# Environment variables (macOS code signing & notarization):
#   CODESIGN_IDENTITY  — e.g. "Developer ID Application: Your Name (TEAMID)"
#   APPLE_ID           — Apple ID email for notarization
#   APPLE_PASSWORD     — App-specific password for notarization
#   APPLE_TEAM_ID      — 10-char Apple Developer Team ID
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> Installing dependencies..."
if command -v uv &>/dev/null; then
    uv sync
    uv pip install pyinstaller
    # uv sync removes sherpa-onnx-core (platform-specific binary wheel not
    # in the lock file).  Reinstall it so PyInstaller can bundle libonnxruntime.
    uv pip install sherpa-onnx-core
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
    --collect-binaries=sherpa_onnx \
    --hidden-import=sherpa_onnx \
    --hidden-import=pynput \
    --hidden-import=pynput.keyboard \
    --hidden-import=pynput.keyboard._darwin \
    --add-data "src/roomkit_ui${SEP}roomkit_ui" \
    src/roomkit_ui/__main__.py

# macOS: patch Info.plist, sign, and optionally notarize
APP="dist/RoomKit UI.app"
APP_PLIST="$APP/Contents/Info.plist"
if [ -f "$APP_PLIST" ]; then
    /usr/libexec/PlistBuddy -c \
        "Set :CFBundleIdentifier com.roomkit.ui" \
        "$APP_PLIST" 2>/dev/null || true
    /usr/libexec/PlistBuddy -c \
        "Add :NSMicrophoneUsageDescription string 'RoomKit UI needs microphone access for voice conversations.'" \
        "$APP_PLIST" 2>/dev/null || true
    echo "==> Patched Info.plist (bundle ID + mic permission)"

    if [ -n "${CODESIGN_IDENTITY:-}" ]; then
        echo "==> Signing with: $CODESIGN_IDENTITY"

        # Sign all bundled shared libraries first
        find "$APP/Contents/Frameworks" -type f \( -name '*.so' -o -name '*.dylib' \) | while read -r lib; do
            codesign --force --options runtime --entitlements entitlements.plist \
                --sign "$CODESIGN_IDENTITY" "$lib"
        done
        echo "==> Signed shared libraries"

        # Sign the main executable
        codesign --force --options runtime --entitlements entitlements.plist \
            --sign "$CODESIGN_IDENTITY" "$APP/Contents/MacOS/RoomKit UI"
        echo "==> Signed main executable"

        # Sign the app bundle
        codesign --force --options runtime --entitlements entitlements.plist \
            --sign "$CODESIGN_IDENTITY" "$APP"
        echo "==> Signed app bundle"

        # Verify signature
        codesign --verify --deep --strict "$APP"
        echo "==> Signature verified"

        # Notarize if Apple credentials are provided
        if [ -n "${APPLE_ID:-}" ] && [ -n "${APPLE_PASSWORD:-}" ] && [ -n "${APPLE_TEAM_ID:-}" ]; then
            echo "==> Notarizing..."
            ZIP_PATH="dist/RoomKit UI-notarize.zip"
            ditto -c -k --keepParent "$APP" "$ZIP_PATH"
            xcrun notarytool submit "$ZIP_PATH" \
                --apple-id "$APPLE_ID" \
                --password "$APPLE_PASSWORD" \
                --team-id "$APPLE_TEAM_ID" \
                --wait
            rm -f "$ZIP_PATH"
            xcrun stapler staple "$APP"
            echo "==> Notarization complete"
        else
            echo "==> Skipping notarization (APPLE_ID/APPLE_PASSWORD/APPLE_TEAM_ID not set)"
        fi
    else
        echo "==> Ad-hoc signing (no CODESIGN_IDENTITY set)"
        codesign --force --deep --sign - "$APP"
    fi

    echo "==> Re-signed app bundle"
fi

# Create DMG (drag-to-Applications disk image)
if [[ "$OSTYPE" == "darwin"* ]] && [ -d "$APP" ]; then
    DMG_PATH="dist/RoomKit-UI.dmg"
    echo "==> Creating DMG..."
    hdiutil create -volname "RoomKit UI" -srcfolder "$APP" \
        -ov -format UDZO "$DMG_PATH"

    # Staple notarization ticket to DMG if available
    if [ -n "${CODESIGN_IDENTITY:-}" ] && [ -n "${APPLE_ID:-}" ]; then
        xcrun stapler staple "$DMG_PATH" || true
    fi

    echo "==> DMG ready: $DMG_PATH"
fi

echo "==> Build complete: dist/RoomKit UI"
