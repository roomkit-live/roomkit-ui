"""Explicit HTTP authentication fields, backed by the existing secret header storage."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass

from roomkit_ui.mcp_config import header_line, split_header_line

MCP_AUTH_MODES = [
    ("None", "none"),
    ("API token (Bearer)", "bearer"),
    ("API key (raw Authorization)", "api_key"),
    ("Username & password (Basic)", "basic"),
    ("OAuth 2.0", "oauth2"),
]


def separate_authorization(raw: str) -> tuple[str, str]:
    """Remove Authorization case-insensitively; leave other header lines intact."""
    authorization = ""
    remaining = []
    for line in raw.splitlines():
        pair = split_header_line(line)
        if pair is not None and pair[0].lower() == "authorization":
            authorization = pair[1]
        else:
            remaining.append(line)
    return authorization, "\n".join(remaining)


@dataclass
class HTTPAuthentication:
    mode: str = "none"
    credential: str = ""
    username: str = ""
    password: str = ""
    headers: str = ""

    @classmethod
    def from_server(cls, server: dict) -> HTTPAuthentication:
        value, headers = separate_authorization(str(server.get("headers") or ""))
        mode = str(server.get("auth") or "none")
        # Old versions represented manual authentication as None + a header.
        if mode == "oauth2":
            return cls(mode=mode, headers=headers)
        if mode == "api_key":
            return cls(mode, value, headers=headers)
        if value:
            scheme, _, credential = value.partition(" ")
            if scheme.lower() == "bearer" and credential.strip():
                return cls("bearer", credential.strip(), headers=headers)
            if scheme.lower() == "basic":
                try:
                    decoded = base64.b64decode(credential, validate=True).decode("utf-8")
                    username, separator, password = decoded.partition(":")
                    if separator:
                        return cls("basic", username=username, password=password, headers=headers)
                except (ValueError, UnicodeError, binascii.Error):
                    pass
            # Preserve unusual schemes and malformed Basic values verbatim.
            return cls("api_key", value, headers=headers)
        return cls(mode=mode, headers=headers)

    def problem(self) -> str | None:
        if self.mode in {"bearer", "api_key"} and not self.credential.strip():
            return "Enter the API token or key."
        if self.mode == "basic":
            if not self.username:
                return "Enter a username."
            if ":" in self.username:
                return "A Basic authentication username cannot contain a colon."
        if self.mode in {"bearer", "api_key"} and any(c in self.credential for c in "\r\n"):
            return "An authentication value must fit on one line."
        return None

    def header_block(self) -> str:
        """Only the selected method supplies Authorization; OAuth supplies it later."""
        _, extra = separate_authorization(self.headers)
        value = ""
        if self.problem():
            return "\n".join(filter(None, ["Authorization:", extra]))
        if self.mode == "bearer":
            token = self.credential.strip()
            if token.lower().startswith("bearer "):
                token = token[7:].strip()
            value = f"Bearer {token}" if token else ""
        elif self.mode == "api_key":
            value = self.credential.strip()
        elif self.mode == "basic" and self.username:
            encoded = base64.b64encode(f"{self.username}:{self.password}".encode()).decode()
            value = f"Basic {encoded}"
        if self.mode in {"bearer", "api_key", "basic"}:
            return "\n".join(filter(None, [header_line("Authorization", value), extra]))
        return extra
