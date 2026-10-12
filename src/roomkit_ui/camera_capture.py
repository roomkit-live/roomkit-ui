"""Camera-only helper: no settings loader, providers, engine or Keychain access.

Only source macOS launches need this process. Its parent sends cancel/raise over
stdin; one reviewed image returns on stdout. No photo or credentials go to disk.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from roomkit_ui.macos_app import relaunch_camera_if_needed


def main() -> int:
    args = argparse.ArgumentParser()
    args.add_argument("--theme", choices=("dark", "light"), default="dark")
    theme = args.parse_args().theme
    try:
        relaunch_camera_if_needed()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    # The bundle must be in place before Qt initializes its permission backend.
    from PySide6.QtCore import QSocketNotifier
    from PySide6.QtWidgets import QApplication

    from roomkit_ui.theme import get_stylesheet
    from roomkit_ui.widgets.camera_dialog import CameraDialog

    app = QApplication(["RoomKit Camera"])
    app.setApplicationName("RoomKit Camera")
    app.setStyleSheet(get_stylesheet(theme))
    dialog = CameraDialog()
    dialog.photo_selected.connect(
        lambda photo: print(json.dumps({"event": "photo", "image": photo.snapshot()}), flush=True)
    )
    dialog.finished.connect(app.quit)

    # EOF also closes capture if the main application exits unexpectedly.
    control = QSocketNotifier(sys.stdin.fileno(), QSocketNotifier.Read, dialog)
    pending = bytearray()

    def commands() -> None:
        data = os.read(sys.stdin.fileno(), 1024)
        pending.extend(data)
        if not data or len(pending) > 4096:
            control.setEnabled(False)
            dialog.reject()
            return
        while b"\n" in pending:
            command, _, rest = pending.partition(b"\n")
            pending[:] = rest
            if command == b"cancel":
                dialog.reject()
                return
            if command == b"raise":
                dialog.show()
                dialog.raise_()
                dialog.activateWindow()

    control.activated.connect(commands)
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
