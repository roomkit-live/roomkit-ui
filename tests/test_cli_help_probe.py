"""--help probing: spawn count bounded by the byte cap, results cached."""

import os
import sys

import pytest

from roomkit_ui.cli_exec import ProcessRegistry
from roomkit_ui.cli_help import _PROBE_BATCH, clear_help_cache, probe_help

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX script as a CLI")

# A CLI with 40 commands at every level, each help ~1.6 KB, Click-style.
# Every invocation is logged, so a test can count the spawns.
_FAKE_CLI = """#!{python}
import sys
with open({log!r}, "a") as log:
    log.write(" ".join(sys.argv[1:]) + "\\n")
where = " ".join(sys.argv[1:-1])
names = "\\n".join(f"  c{{i:02d}}  Does thing {{i}} of {{where}}" for i in range(40))
print("Usage: fake [OPTIONS] COMMAND [ARGS]...\\n\\nCommands:\\n" + names)
"""


@pytest.fixture
def fake_cli(tmp_path):
    log = tmp_path / "calls.log"
    cli = tmp_path / "fake"
    cli.write_text(_FAKE_CLI.format(python=sys.executable, log=str(log)))
    cli.chmod(0o755)
    clear_help_cache()
    yield cli, log
    clear_help_cache()


def _calls(log):
    return log.read_text().splitlines() if log.exists() else []


async def _probe(cli, depth, byte_cap):
    return await probe_help(
        [str(cli)],
        display="fake",
        depth=depth,
        timeout=10,
        byte_cap=byte_cap,
        registry=ProcessRegistry(),
        env={},
    )


async def test_the_byte_cap_bounds_the_spawns_not_just_the_text(fake_cli):
    cli, log = fake_cli
    root_size = len(await _probe(cli, depth=1, byte_cap=10**6))
    clear_help_cache()
    log.unlink()

    # Room for the root and about two sections: a whole level of 40 was
    # spawned before the cap was looked at.
    text = await _probe(cli, depth=3, byte_cap=root_size * 3)

    assert len(text) <= root_size * 3
    assert len(_calls(log)) <= 1 + _PROBE_BATCH


async def test_a_probe_is_reused_for_the_next_session(fake_cli):
    cli, log = fake_cli
    first = await _probe(cli, depth=2, byte_cap=10**6)
    spawned = len(_calls(log))

    second = await _probe(cli, depth=2, byte_cap=10**6)

    assert second == first
    assert len(_calls(log)) == spawned  # nothing launched the second time
    assert spawned == 1 + 40


async def test_an_upgraded_cli_is_probed_again(fake_cli):
    cli, log = fake_cli
    await _probe(cli, depth=1, byte_cap=10**6)
    stat = cli.stat()
    os.utime(cli, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))

    await _probe(cli, depth=1, byte_cap=10**6)

    assert len(_calls(log)) == 2


async def test_a_different_declared_env_is_probed_again(fake_cli):
    cli, log = fake_cli
    await _probe(cli, depth=1, byte_cap=10**6)

    await probe_help(
        [str(cli)],
        display="fake",
        depth=1,
        timeout=10,
        byte_cap=10**6,
        registry=ProcessRegistry(),
        env={"PROFILE": "work"},
    )

    assert len(_calls(log)) == 2
