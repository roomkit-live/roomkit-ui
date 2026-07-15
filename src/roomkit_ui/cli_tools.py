"""CLI tools: let the voice agent invoke local command-line binaries.

One tool per declared binary, not one per subcommand — a CLI like ``gh`` has
34 command groups and hundreds of leaf commands, and declaring each would
flood the prompt. The model composes the argv itself, guided by ``--help``
output seeded into the tool description (see ``cli_help``).

Mirrors ``MCPManager``'s public shape so ``Engine`` treats the two tool
sources alike: ``probe_all`` / ``get_tools`` / ``handle_tool_call`` /
``terminate_all``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any

from roomkit_ui.builtin_tools import BUILTIN_TOOLS
from roomkit_ui.cli_exec import ProcessRegistry, resolve_command, run_sync, truncate
from roomkit_ui.cli_help import probe_help
from roomkit_ui.cli_tools_config import help_depth, slugify_tool_name, tool_env, tool_timeout

logger = logging.getLogger(__name__)

# Depth-2 help measures ~47 KB (~12K tokens) for gh, and much the same for
# other large CLIs. That buys the model the argument syntax up front, so it
# calls commands without a --help round trip first. Past this the context cost
# stops paying for itself.
HELP_BYTE_CAP = 64_000

# A voice agent cannot use a 50 KB JSON dump, and the model can always re-run
# with --limit. Truncation says so explicitly rather than lying by omission.
OUTPUT_CAP = 8_000

_BUILTIN_NAMES = frozenset(t["name"] for t in BUILTIN_TOOLS)

# Deliberately names no real command: this text goes into EVERY declared
# tool's description, so a concrete example from one CLI would be nonsense in
# another's. The seeded --help supplies the real inventory; this only has to
# teach the argv shape.
_ARGS_HINT = (
    "Call it by passing `args` as an argv array, one element per argument: "
    '["<command>", "<subcommand>", "--flag", "value"]. Prefer a JSON output '
    "flag where a command offers one — the output is easier to read back. "
    "To learn a command's exact arguments, call this tool with "
    '["<command>", "--help"] first; usage errors come back with the fix in stderr.'
)


@dataclass(frozen=True)
class _Spec:
    """A validated, resolved CLI tool declaration."""

    name: str
    argv: list[str]
    description: str
    env: dict[str, str]
    depth: int
    timeout: float


class CliToolManager:
    """Builds and dispatches tools backed by local CLI binaries."""

    def __init__(self, cli_tools: list[dict[str, Any]]) -> None:
        self._registry = ProcessRegistry()
        self._specs: dict[str, _Spec] = {}
        self._tools: list[dict] = []
        self.failed_tools: list[str] = []
        for cfg in cli_tools:
            spec = self._build_spec(cfg)
            if spec is not None:
                self._specs[spec.name] = spec

    def _build_spec(self, cfg: dict[str, Any]) -> _Spec | None:
        """Validate one declaration. Returns None (and logs why) if unusable.

        Rejections report the name as declared, not the slug — that is the
        string the user typed and the one they can go find in settings.
        """
        declared = str(cfg.get("name", "")).strip()
        name = slugify_tool_name(declared)
        if not name:
            self._reject(declared, "name has no usable characters")
            return None

        # Dispatch order is builtin → CLI → MCP, so a builtin name silently
        # shadows a CLI tool of the same name. Refuse rather than advertise
        # something that can never be reached.
        if name in _BUILTIN_NAMES:
            self._reject(declared, f"{name!r} collides with a built-in tool")
            return None
        if name in self._specs:
            self._reject(declared, f"duplicate tool name {name!r}")
            return None

        command = str(cfg.get("command", "")).strip()
        argv = resolve_command(command)
        if argv is None:
            self._reject(declared, f"command not found: {command!r}")
            return None

        return _Spec(
            name=name,
            argv=argv,
            description=str(cfg.get("description", "")).strip(),
            env=tool_env(cfg),
            depth=help_depth(cfg),
            timeout=tool_timeout(cfg),
        )

    def _reject(self, name: str, reason: str) -> None:
        logger.warning("Skipping CLI tool %r: %s", name or "<unnamed>", reason)
        self.failed_tools.append(name or "<unnamed>")

    async def probe_all(self) -> None:
        """Seed each tool's ``--help`` and build the advertised schemas."""
        specs = list(self._specs.values())
        helps = await asyncio.gather(
            *(
                probe_help(
                    spec.argv,
                    display=spec.argv[0].rsplit("/", 1)[-1],
                    depth=spec.depth,
                    timeout=spec.timeout,
                    byte_cap=HELP_BYTE_CAP,
                    registry=self._registry,
                    env=spec.env,
                )
                for spec in specs
            )
        )
        self._tools = [
            self._schema(spec, help_text) for spec, help_text in zip(specs, helps, strict=True)
        ]
        if self._tools:
            logger.info("CLI tools: %s", ", ".join(t["name"] for t in self._tools))

    def _schema(self, spec: _Spec, help_text: str) -> dict:
        """Build the tool schema handed to the provider.

        Hand-authored, so it needs no ``_clean_schema`` pass — and must not
        gain ``additionalProperties``, which has no strip pass on this path
        and which Gemini rejects.
        """
        command = " ".join(spec.argv)
        parts = [
            spec.description or f"Run the {spec.name} command-line tool.",
            f"\n\nWraps the local CLI `{command}`. {_ARGS_HINT}",
        ]
        if help_text:
            parts.append(f"\n\n$ {spec.name} --help\n{help_text}")
        return {
            "type": "function",
            "name": spec.name,
            "description": "".join(parts),
            "parameters": {
                "type": "object",
                "properties": {
                    "args": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Arguments to pass to the CLI, one array element per argument. "
                            "Do not include the command name itself."
                        ),
                    },
                },
                "required": ["args"],
            },
        }

    def get_tools(self) -> list[dict]:
        return list(self._tools)

    def has_tool(self, name: str) -> bool:
        return name in self._specs

    async def handle_tool_call(self, name: str, arguments: dict[str, Any]) -> str:
        spec = self._specs.get(name)
        if spec is None:
            return json.dumps({"error": f"Unknown CLI tool: {name}"})

        args = arguments.get("args", [])
        if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
            return json.dumps({"error": "args must be an array of strings"})

        result = await asyncio.to_thread(
            run_sync,
            [*spec.argv, *args],
            timeout=spec.timeout,
            registry=self._registry,
            extra_env=spec.env,
        )
        if result.timed_out:
            logger.warning("CLI tool %r timed out after %ss", name, spec.timeout)
            return json.dumps({"error": f"Command timed out after {spec.timeout}s"})

        # stderr goes back verbatim: CLIs put the correction there
        # ("unknown flag: --foo", "Missing argument 'NAME'"), and that is how
        # the model recovers from a wrong guess.
        return json.dumps(
            {
                "exit_code": result.exit_code,
                "stdout": truncate(result.stdout, OUTPUT_CAP),
                "stderr": truncate(result.stderr, OUTPUT_CAP),
            }
        )

    def terminate_all(self) -> None:
        """Kill any child still running. Called from Engine cleanup."""
        self._registry.terminate_all()
