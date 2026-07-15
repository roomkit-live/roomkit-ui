import json
import time

from roomkit_ui.cli_exec import ProcessRegistry, resolve_command, run_sync, truncate
from roomkit_ui.cli_help import parse_subcommands
from roomkit_ui.cli_tools import OUTPUT_CAP, CliToolManager
from roomkit_ui.env_config import invalid_env_lines, parse_env_block

RICH_HELP = """
 Usage: tool [OPTIONS] COMMAND [ARGS]...

╭─ Options ────────────────────────────────────────────────────╮
│ --version          Show the version and exit.                │
│ --help             Show this message and exit.               │
╰──────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────╮
│ issue       Manage issues.                                   │
│ pr          Manage pull requests.                            │
│ repo        Manage repositories.                             │
╰──────────────────────────────────────────────────────────────╯
"""

PLAIN_HELP = """Usage: tool [OPTIONS] COMMAND [ARGS]...

Options:
  --help  Show this message and exit.

Commands:
  build   Build the thing.
  deploy  Ship the thing.
"""

# Cobra, as `gh --help` really prints it: colon-suffixed names, several
# command sections, and trailing sections that are not commands at all.
COBRA_HELP = """Work seamlessly with GitHub from the command line.

USAGE
  gh <command> <subcommand> [flags]

CORE COMMANDS
  auth:          Authenticate gh and git with GitHub
  issue:         Manage issues
  pr:            Manage pull requests

GITHUB ACTIONS COMMANDS
  run:           View details about workflow runs
  workflow:      View details about GitHub Actions workflows

ADDITIONAL COMMANDS
  alias:         Create command shortcuts
  api:           Make an authenticated GitHub API request

HELP TOPICS
  environment:   Environment variables that can be used with gh

FLAGS
  --help      Show help for command
  --version   Show gh version
"""

CLASSIC_COBRA_HELP = """kubectl controls the Kubernetes cluster manager.

Basic Commands (Beginner):
  create        Create a resource from a file
  expose        Take a replication controller and expose it

Available Commands:
  get           Display one or many resources
  delete        Delete resources

Usage:
  kubectl [flags] [options]
"""


# -- help parsing --------------------------------------------------------


def test_parse_subcommands_reads_rich_boxed_help():
    assert parse_subcommands(RICH_HELP) == ["issue", "pr", "repo"]


def test_parse_subcommands_reads_plain_click_help():
    assert parse_subcommands(PLAIN_HELP) == ["build", "deploy"]


def test_parse_subcommands_reads_every_cobra_command_section():
    # gh spreads its commands over several sections; stopping at the first
    # one would hide most of the CLI from the model.
    assert parse_subcommands(COBRA_HELP) == [
        "auth",
        "issue",
        "pr",
        "run",
        "workflow",
        "alias",
        "api",
    ]


def test_parse_subcommands_ignores_cobra_sections_that_are_not_commands():
    # "HELP TOPICS" and "FLAGS" are shaped like command lists but are not.
    names = parse_subcommands(COBRA_HELP)

    assert "environment" not in names
    assert "help" not in names


def test_parse_subcommands_reads_classic_cobra_headings():
    assert parse_subcommands(CLASSIC_COBRA_HELP) == ["create", "expose", "get", "delete"]


def test_parse_subcommands_ignores_options_and_help_without_commands():
    assert parse_subcommands("Usage: tool [OPTIONS]\n\nOptions:\n  --help  Show help.\n") == []


# -- command resolution --------------------------------------------------


def test_resolve_command_returns_absolute_path():
    argv = resolve_command("echo")
    assert argv is not None and argv[0].endswith("/echo")


def test_resolve_command_keeps_trailing_args_and_honours_quoting():
    argv = resolve_command('echo "hello world" second')
    assert argv is not None
    assert argv[1:] == ["hello world", "second"]


def test_resolve_command_returns_none_for_missing_binary():
    assert resolve_command("definitely-not-a-real-binary-xyz") is None
    assert resolve_command("") is None


# -- execution -----------------------------------------------------------


def test_run_sync_captures_stdout_and_exit_code():
    result = run_sync(resolve_command("echo") + ["hi"], timeout=5, registry=ProcessRegistry())

    assert result.exit_code == 0
    assert result.stdout.strip() == "hi"
    assert result.timed_out is False


def test_run_sync_kills_a_process_that_outlives_its_timeout():
    started = time.monotonic()
    result = run_sync(resolve_command("sleep") + ["30"], timeout=1, registry=ProcessRegistry())

    assert result.timed_out is True
    assert time.monotonic() - started < 5


def test_run_sync_reports_a_launch_failure_instead_of_raising():
    result = run_sync(["/nonexistent/binary"], timeout=5, registry=ProcessRegistry())

    assert result.exit_code == -1
    assert "Failed to launch" in result.stderr


def test_truncate_says_it_truncated_rather_than_silently_clipping():
    assert truncate("abc", 10) == "abc"
    out = truncate("x" * 100, 10)
    assert out.startswith("x" * 10)
    assert "truncated, 100 chars total" in out


# -- environment ---------------------------------------------------------


def test_parse_env_block_reads_one_pair_per_line():
    assert parse_env_block("LUGE_CLI_JSON=1\nTOKEN=abc") == {"LUGE_CLI_JSON": "1", "TOKEN": "abc"}


def test_parse_env_block_keeps_an_equals_sign_inside_a_value():
    # Base64 and connection strings both carry "=", so only the first splits.
    assert parse_env_block("KEY=a=b==") == {"KEY": "a=b=="}


def test_parse_env_block_drops_junk_instead_of_raising():
    assert parse_env_block("no-equals-here\n=novalue\n\nOK=1") == {"OK": "1"}
    assert parse_env_block("") == {}
    assert parse_env_block(None) == {}


def test_invalid_env_lines_names_exactly_what_the_parser_dropped():
    # The two must agree line for line, or the page reports a variable as set
    # that never arrives — blank lines are not a mistake and must not appear.
    assert invalid_env_lines("OK=1\nno-equals-here\n\n=novalue") == ["no-equals-here", "=novalue"]
    assert invalid_env_lines("OK=1\n\n") == []
    assert invalid_env_lines(None) == []


async def test_declared_env_reaches_the_child_process():
    # The whole point: "FOO=1 mycli" cannot go in the command field, so the
    # variable has to arrive from the env field instead.
    mgr = CliToolManager(
        [{"name": "sh", "command": "sh", "seed_help": False, "env": "LUGE_CLI_JSON=1"}]
    )
    await mgr.probe_all()

    out = json.loads(await mgr.handle_tool_call("sh", {"args": ["-c", "echo $LUGE_CLI_JSON"]}))

    assert out["stdout"].strip() == "1"


async def test_declared_env_does_not_replace_the_inherited_environment():
    # extra_env merges into the child env; wiping PATH would break every CLI.
    mgr = CliToolManager([{"name": "sh", "command": "sh", "seed_help": False, "env": "FOO=1"}])
    await mgr.probe_all()

    out = json.loads(await mgr.handle_tool_call("sh", {"args": ["-c", "echo $PATH"]}))

    assert out["stdout"].strip()


async def test_declared_env_reaches_the_help_probe():
    # Help is seeded from the CLI as configured, so the probe must see the
    # declared variables too. `sh -c printenv` dumps its environment whatever
    # the probe appends, which is what makes it a usable witness here.
    mgr = CliToolManager(
        [{"name": "dump", "command": "sh -c printenv", "env": "LUGE_CLI_JSON=1", "help_depth": 1}]
    )
    await mgr.probe_all()

    assert "LUGE_CLI_JSON=1" in mgr.get_tools()[0]["description"]


# -- declaration validation ----------------------------------------------


def test_manager_skips_declarations_it_cannot_honour():
    mgr = CliToolManager(
        [
            {"name": "", "command": "echo"},
            {"name": "ghost", "command": "definitely-not-a-real-binary-xyz"},
            {"name": "ok", "command": "echo"},
        ]
    )

    assert mgr.has_tool("ok")
    assert not mgr.has_tool("ghost")
    assert mgr.failed_tools == ["<unnamed>", "ghost"]


def test_manager_accepts_a_human_name_and_exposes_its_slug():
    # A space is legal in a declaration and illegal in a provider function
    # name, so the manager must derive one rather than drop the tool.
    mgr = CliToolManager([{"name": "GitHub CLI", "command": "echo"}])

    assert mgr.has_tool("github_cli")
    assert mgr.failed_tools == []


def test_manager_rejects_a_name_a_builtin_would_shadow():
    # Dispatch tries builtins first, so such a tool could never be reached.
    mgr = CliToolManager([{"name": "get_current_time", "command": "echo"}])

    assert not mgr.has_tool("get_current_time")
    assert mgr.failed_tools == ["get_current_time"]


def test_manager_rejects_a_builtin_collision_the_slug_creates():
    # "Get Current Time" slugifies onto a builtin — catch it after slugifying.
    mgr = CliToolManager([{"name": "Get Current Time", "command": "echo"}])

    assert mgr.get_tools() == []
    assert mgr.failed_tools == ["Get Current Time"]


def test_manager_keeps_only_the_first_of_duplicate_names():
    mgr = CliToolManager(
        [
            {"name": "dup", "command": "echo", "description": "first"},
            {"name": "dup", "command": "printf", "description": "second"},
        ]
    )

    assert mgr.failed_tools == ["dup"]
    assert mgr._specs["dup"].description == "first"


# -- schema --------------------------------------------------------------


async def test_schema_advertises_an_argv_array_and_no_rejected_keys():
    mgr = CliToolManager([{"name": "ok", "command": "echo", "seed_help": False}])
    await mgr.probe_all()

    tool = mgr.get_tools()[0]
    assert tool["type"] == "function"
    assert tool["name"] == "ok"
    params = tool["parameters"]
    assert params["properties"]["args"] == {
        "type": "array",
        "items": {"type": "string"},
        "description": (
            "Arguments to pass to the CLI, one array element per argument. "
            "Do not include the command name itself."
        ),
    }
    assert params["required"] == ["args"]
    # Gemini rejects these, and this hand-authored path has no strip pass.
    assert "additionalProperties" not in params
    assert "$schema" not in params


async def test_description_leads_with_the_user_text_so_summaries_stay_readable():
    mgr = CliToolManager(
        [{"name": "ok", "command": "echo", "description": "Says things", "seed_help": False}]
    )
    await mgr.probe_all()

    assert mgr.get_tools()[0]["description"].split("\n")[0] == "Says things"


# -- dispatch ------------------------------------------------------------


async def test_handle_tool_call_returns_exit_code_and_stdout():
    mgr = CliToolManager([{"name": "ok", "command": "echo", "seed_help": False}])
    await mgr.probe_all()

    out = json.loads(await mgr.handle_tool_call("ok", {"args": ["hello"]}))

    assert out["exit_code"] == 0
    assert out["stdout"].strip() == "hello"


async def test_handle_tool_call_returns_stderr_verbatim_for_self_correction():
    # The model recovers from usage errors by reading stderr, so it must survive.
    mgr = CliToolManager([{"name": "sh", "command": "sh", "seed_help": False}])
    await mgr.probe_all()

    out = json.loads(await mgr.handle_tool_call("sh", {"args": ["-c", "echo oops >&2; exit 3"]}))

    assert out["exit_code"] == 3
    assert out["stderr"].strip() == "oops"


async def test_handle_tool_call_truncates_a_flood_of_output():
    mgr = CliToolManager([{"name": "sh", "command": "sh", "seed_help": False}])
    await mgr.probe_all()

    out = json.loads(
        await mgr.handle_tool_call(
            "sh", {"args": ["-c", f"printf 'x%.0s' $(seq {OUTPUT_CAP * 2})"]}
        )
    )

    assert "truncated" in out["stdout"]
    assert len(out["stdout"]) < OUTPUT_CAP * 2


async def test_handle_tool_call_rejects_non_string_args_without_spawning():
    mgr = CliToolManager([{"name": "ok", "command": "echo", "seed_help": False}])
    await mgr.probe_all()

    assert "error" in json.loads(await mgr.handle_tool_call("ok", {"args": ["a", 42]}))
    assert "error" in json.loads(await mgr.handle_tool_call("ok", {"args": "not-a-list"}))


async def test_handle_tool_call_reports_an_unknown_tool():
    mgr = CliToolManager([])

    assert "error" in json.loads(await mgr.handle_tool_call("nope", {"args": []}))


async def test_handle_tool_call_reports_a_timeout_rather_than_hanging():
    mgr = CliToolManager([{"name": "slow", "command": "sleep", "seed_help": False, "timeout": 1}])
    await mgr.probe_all()

    started = time.monotonic()
    out = json.loads(await mgr.handle_tool_call("slow", {"args": ["30"]}))

    assert "timed out" in out["error"]
    assert time.monotonic() - started < 5


async def test_terminate_all_kills_a_child_still_running():
    mgr = CliToolManager([{"name": "sh", "command": "sh", "seed_help": False, "timeout": 60}])
    await mgr.probe_all()

    import asyncio

    call = asyncio.create_task(mgr.handle_tool_call("sh", {"args": ["-c", "sleep 30"]}))
    await asyncio.sleep(0.3)
    mgr.terminate_all()

    out = json.loads(await asyncio.wait_for(call, timeout=5))
    assert out["exit_code"] != 0
