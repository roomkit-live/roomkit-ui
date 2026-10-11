"""``roomkit-ui --doctor`` runs beside a live app and must leave it alone."""

import os
import subprocess
import sys
from pathlib import Path


def _log_file(home: Path) -> Path:
    if sys.platform == "darwin":
        return home / "Library" / "Logs" / "RoomKit UI" / "roomkit-ui.log"
    return home / ".local" / "share" / "roomkit-ui" / "logs" / "roomkit-ui.log"


def test_doctor_leaves_the_running_apps_log_alone(tmp_path):
    # A real process: the log was opened (and truncated) while importing the
    # entry point, before main() ever saw --doctor.
    log = _log_file(tmp_path)
    log.parent.mkdir(parents=True)
    log.write_text("session in progress\n")
    env = {k: v for k, v in os.environ.items() if k != "XDG_DATA_HOME"}
    env.update(HOME=str(tmp_path), USERPROFILE=str(tmp_path))

    done = subprocess.run(
        [sys.executable, "-m", "roomkit_ui", "--doctor"],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )

    assert "roomkit-ui" in done.stdout
    assert log.read_text() == "session in progress\n"
