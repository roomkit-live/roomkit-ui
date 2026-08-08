# Source of truth for the Homebrew cask. The Build workflow copies this file
# into roomkit-live/homebrew-tap on each `v*` tag, with `version` and `sha256`
# rewritten to match the released DMG. Edit it here, never in the tap.

cask "roomkit-ui" do
  version "0.2.1"
  sha256 "0000000000000000000000000000000000000000000000000000000000000000"

  url "https://github.com/roomkit-live/roomkit-ui/releases/download/v#{version}/RoomKit-UI-macOS.dmg",
      verified: "github.com/roomkit-live/roomkit-ui/"
  name "RoomKit UI"
  desc "Desktop voice assistant built on the roomkit framework"
  homepage "https://github.com/roomkit-live/roomkit-ui"

  livecheck do
    url :url
    strategy :github_latest
  end

  # arm64: the release matrix builds macOS on `macos-latest` only, so the DMG
  # carries a single slice.
  #
  # Ventura, not Big Sur: the launcher binary reports `minos 11.0` because it
  # inherits it from the Python framework, but the Qt frameworks inside the
  # bundle are built against the macOS 13 SDK. Trusting the launcher would let
  # an older Mac install cleanly and then crash on the first Qt symbol.
  depends_on arch: :arm64
  depends_on macos: :ventura

  app "RoomKit UI.app"

  # Global hotkeys keep a listener alive, so an upgrade over a running copy
  # leaves a stale process holding the shortcut.
  uninstall quit: "com.roomkit.ui"

  # Two roots on purpose: models, skills and conversation history follow the
  # macOS convention, while the audio-debug captures land in the XDG path the
  # pipeline uses on every platform.
  zap trash: [
    "~/.local/share/roomkit-ui",
    "~/Library/Application Support/RoomKit UI",
    "~/Library/Logs/RoomKit UI",
    "~/Library/Preferences/com.roomkit.RoomKit UI.plist",
    "~/Library/Saved Application State/com.roomkit.ui.savedState",
  ]
end
