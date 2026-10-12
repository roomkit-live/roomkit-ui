"""The user's answer before code runs on behalf of a skill an MCP server serves.

While such a skill is active in a conversation, roomkit serves a tool that
runs code (here the CLI tools) only once the host approves that skill
(``approve_execution``).  The engine asks through ``SkillApprovals``: the UI
shows the question, and no answer within ``APPROVAL_TIMEOUT_S`` refuses.
roomkit keeps a yes for that conversation and that version of the skill;
a skill whose files changed is asked again.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

APPROVAL_TIMEOUT_S = 60.0


@dataclass
class SkillApproval:
    """One question to the user: may *tool* run while *skill* is active?"""

    skill: str  # its name in the registry, "hugging_face:hf-cli"
    server: str  # the name the user gave its MCP server
    tool: str
    future: asyncio.Future[bool] = field(repr=False)

    @property
    def question(self) -> str:
        return (
            f"The skill “{self.skill}”, published by the MCP server “{self.server}”, "
            f"is active in this conversation, and the assistant wants to run "
            f"“{self.tool}”, which starts a program on this computer.\n\n"
            "Allow programs to run on this skill's behalf for the rest of this "
            "conversation? A refusal only stops this call."
        )

    def answer(self, approved: bool) -> None:
        if not self.future.done():
            self.future.set_result(approved)

    @property
    def settled(self) -> bool:
        return self.future.done()


class SkillApprovals:
    """The questions in flight: one per conversation and skill at a time."""

    def __init__(
        self,
        ask_user: Callable[[SkillApproval], None],
        notice: Callable[[str], None],
        *,
        timeout: float = APPROVAL_TIMEOUT_S,
    ) -> None:
        self._ask_user = ask_user
        self._notice = notice
        self._timeout = timeout
        self._servers: dict[str, str] = {}  # label → the server's name
        self._pending: dict[tuple[str | None, str, str | None], SkillApproval] = {}

    def set_servers(self, names: dict[str, str]) -> None:
        """The session's servers, label → name, for the question to name them."""
        self._servers = dict(names)

    async def approve(self, request: Any) -> bool:
        """roomkit's ``approve_execution``: the user's answer to *request*
        (a ``SkillExecutionRequest``), False once the time is up."""
        key = (request.room_id, request.name, request.fingerprint)
        approval = self._pending.get(key)
        if approval is None:
            approval = SkillApproval(
                skill=request.name,
                server=self._servers.get(request.label, request.label),
                tool=request.tool,
                future=asyncio.get_running_loop().create_future(),
            )
            self._pending[key] = approval
            approval.future.add_done_callback(lambda _f: self._pending.pop(key, None))
            logger.info("Asking whether %s may run while %s is active", request.tool, request.name)
            self._ask_user(approval)
        try:
            # Shielded: a call that gives up does not take the question away
            # from another one waiting on the same answer.
            approved = await asyncio.wait_for(asyncio.shield(approval.future), self._timeout)
        except TimeoutError:
            if not approval.settled:
                approval.answer(False)
                self._notice(f"No answer: “{request.tool}” did not run for {request.name}.")
            return False
        logger.info(
            "%s %s for %s", "Approved" if approved else "Refused", request.tool, request.name
        )
        return approved

    def cancel_all(self) -> None:
        """The session ends: every question still open is refused and closed."""
        for approval in list(self._pending.values()):
            approval.answer(False)
        self._pending.clear()
        self._servers = {}
