"""The paste keystroke through the XDG RemoteDesktop portal (GNOME, KDE on Wayland).

GNOME's compositor has no virtual keyboard protocol, so it refuses wtype; the
portal is how a Wayland app may press keys there.  The desktop asks the user
once ("remote interaction"); the restore token each start returns skips the
question next time (a token serves once, so the newest is kept).  Each paste
opens a session, presses the keys and closes it: a session left open would keep
the desktop's remote-control indicator on.

Blocking D-Bus through jeepney: callers run this off the event loop.
"""

from __future__ import annotations

import logging
import os
import secrets
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from roomkit_ui.paths import data_dir

logger = logging.getLogger(__name__)

_BUS_NAME = "org.freedesktop.portal.Desktop"
_PORTAL_PATH = "/org/freedesktop/portal/desktop"
_REMOTE_DESKTOP = "org.freedesktop.portal.RemoteDesktop"
_KEYBOARD = 1  # AvailableDeviceTypes / SelectDevices "types" bit
_PERSIST_UNTIL_REVOKED = 2
_CALL_TIMEOUT_S = 5.0
# The first paste waits for the user's answer to the desktop's question.
ANSWER_TIMEOUT_S = 60.0

# X keysyms: the portal maps them through the active layout, AZERTY included.
CONTROL_L = 0xFFE3
LETTER_V = 0x0076


class PortalUnavailableError(Exception):
    """No RemoteDesktop portal with a keyboard on this desktop (Sway, Hyprland)."""


class PortalRefusedError(Exception):
    """The portal did not let the keys through; ``str()`` says why, for the user."""


def token_path() -> Path:
    return data_dir() / "remote-desktop-token"


def press_keys(
    keysyms: Sequence[int],
    *,
    cancelled: threading.Event | None = None,
    answer_timeout: float = ANSWER_TIMEOUT_S,
) -> None:
    """Press *keysyms* in order, then release them in reverse.

    Raises PortalUnavailableError when the desktop has no such portal, PortalRefusedError
    when the user declines or the portal fails, TimeoutError when the question
    stays unanswered.  When *cancelled* is set by the time the desktop answers,
    nothing is pressed: the caller gave up, and the focus may have moved since.
    """
    try:
        from jeepney.io.blocking import open_dbus_connection

        conn = open_dbus_connection(bus="SESSION")
    # ValueError: jeepney's AuthenticationError, a bus that refused the app.
    except (ImportError, KeyError, OSError, ValueError) as exc:
        raise PortalUnavailableError(f"no session bus ({type(exc).__name__})") from exc
    with conn:
        _require_keyboard(conn)
        session = _create_session(conn)
        try:
            _select_keyboard(conn, session)
            _start(conn, session, answer_timeout)
            if cancelled is not None and cancelled.is_set():
                logger.info("Paste abandoned before the desktop answered; no keys sent")
                return
            _press(conn, session, keysyms)
        finally:
            _close_session(conn, session)


def _press(conn: Any, session: str, keysyms: Sequence[int]) -> None:
    """Press the keys, then release in reverse every key the portal took, so a
    failure halfway leaves no modifier held."""
    from jeepney.wrappers import DBusErrorResponse

    pressed: list[int] = []
    try:
        for keysym in keysyms:
            _notify_keysym(conn, session, keysym, pressed=True)
            pressed.append(keysym)
    except DBusErrorResponse as exc:
        raise PortalRefusedError(f"The desktop refused the paste keystroke ({exc.name}).") from exc
    finally:
        for keysym in reversed(pressed):
            try:
                _notify_keysym(conn, session, keysym, pressed=False)
            except (DBusErrorResponse, OSError) as exc:
                logger.warning("Remote desktop key release failed: %s", exc)


def _require_keyboard(conn: Any) -> None:
    from jeepney import DBusAddress, Properties
    from jeepney.wrappers import DBusErrorResponse, unwrap_msg

    portal = DBusAddress(_PORTAL_PATH, bus_name=_BUS_NAME, interface=_REMOTE_DESKTOP)
    try:
        reply = conn.send_and_get_reply(
            Properties(portal).get("AvailableDeviceTypes"), timeout=_CALL_TIMEOUT_S
        )
        _signature, types = unwrap_msg(reply)[0]
    except DBusErrorResponse as exc:
        raise PortalUnavailableError(exc.name or "no RemoteDesktop portal") from exc
    except TimeoutError as exc:
        raise PortalUnavailableError("the portal service did not answer") from exc
    if not types & _KEYBOARD:
        raise PortalUnavailableError("the RemoteDesktop portal offers no keyboard")


def _create_session(conn: Any) -> str:
    results = _request(
        conn,
        "CreateSession",
        "a{sv}",
        (),
        {"session_handle_token": ("s", _token())},
        _CALL_TIMEOUT_S,
    )
    return str(results["session_handle"])


def _select_keyboard(conn: Any, session: str) -> None:
    options: dict[str, tuple[str, Any]] = {
        "types": ("u", _KEYBOARD),
        "persist_mode": ("u", _PERSIST_UNTIL_REVOKED),
    }
    restore_token = _load_token()
    if restore_token:
        options["restore_token"] = ("s", restore_token)
    _request(conn, "SelectDevices", "oa{sv}", (session,), options, _CALL_TIMEOUT_S)


def _start(conn: Any, session: str, answer_timeout: float) -> None:
    results = _request(conn, "Start", "osa{sv}", (session, ""), {}, answer_timeout)
    if not int(results.get("devices", 0)) & _KEYBOARD:
        raise PortalRefusedError("The desktop allowed remote interaction without the keyboard.")
    restore_token = results.get("restore_token")
    if restore_token:
        _save_token(str(restore_token))


def _request(
    conn: Any,
    method: str,
    signature: str,
    args: tuple[Any, ...],
    options: dict[str, tuple[str, Any]],
    timeout: float,
) -> dict[str, Any]:
    """Call a portal method and wait for its Request's Response.

    The match is added before the call: the response may come before the call's
    own reply.  Response codes: 0 granted, 1 declined, 2 anything else.
    """
    from jeepney import DBusAddress, MatchRule, message_bus, new_method_call
    from jeepney.wrappers import DBusErrorResponse, unwrap_msg

    token = _token()
    sender = str(conn.unique_name).lstrip(":").replace(".", "_")
    rule = MatchRule(
        type="signal",
        interface="org.freedesktop.portal.Request",
        member="Response",
        path=f"{_PORTAL_PATH}/request/{sender}/{token}",
    )
    portal = DBusAddress(_PORTAL_PATH, bus_name=_BUS_NAME, interface=_REMOTE_DESKTOP)
    call = new_method_call(
        portal, method, signature, (*args, {**options, "handle_token": ("s", token)})
    )
    try:
        unwrap_msg(conn.send_and_get_reply(message_bus.AddMatch(rule), timeout=_CALL_TIMEOUT_S))
        with conn.filter(rule) as queue:
            unwrap_msg(conn.send_and_get_reply(call, timeout=_CALL_TIMEOUT_S))
            code, results = conn.recv_until_filtered(queue, timeout=timeout).body
    except DBusErrorResponse as exc:
        raise PortalRefusedError(
            f"The desktop's remote interaction portal failed ({exc.name})."
        ) from exc
    if code == 1:
        raise PortalRefusedError(
            "Pasting needs the desktop's permission for remote interaction, and it was declined."
        )
    if code != 0:
        raise PortalRefusedError(f"The desktop's remote interaction portal refused {method}.")
    return {key: value for key, (_signature, value) in results.items()}


def _notify_keysym(conn: Any, session: str, keysym: int, *, pressed: bool) -> None:
    from jeepney import DBusAddress, new_method_call
    from jeepney.wrappers import unwrap_msg

    portal = DBusAddress(_PORTAL_PATH, bus_name=_BUS_NAME, interface=_REMOTE_DESKTOP)
    call = new_method_call(
        portal, "NotifyKeyboardKeysym", "oa{sv}iu", (session, {}, keysym, int(pressed))
    )
    unwrap_msg(conn.send_and_get_reply(call, timeout=_CALL_TIMEOUT_S))


def _close_session(conn: Any, session: str) -> None:
    from jeepney import DBusAddress, new_method_call

    target = DBusAddress(session, bus_name=_BUS_NAME, interface="org.freedesktop.portal.Session")
    try:
        conn.send_and_get_reply(new_method_call(target, "Close"), timeout=_CALL_TIMEOUT_S)
    except (OSError, TimeoutError):
        logger.warning("Remote desktop session %s did not close", session)


def _token() -> str:
    return "roomkit_" + secrets.token_hex(8)


def _load_token() -> str:
    try:
        return token_path().read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _save_token(token: str) -> None:
    """Keep the newest restore token, readable by its owner only: it lets the
    app press keys without asking again."""
    path = token_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.fchmod(fd, 0o600)  # also a file an older copy left wider
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(token)
    except OSError:
        logger.warning("Could not keep the remote desktop restore token", exc_info=True)
