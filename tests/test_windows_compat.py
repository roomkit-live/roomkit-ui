"""Guards for the Unix-only APIs a Windows release trips over.

Every CI job runs on Linux, where ``resource`` imports and ``os.killpg``
resolves, so nothing here is observable on the machines that run the suite.
Each test removes the API the way Windows lacks it and asserts the code copes.
"""

import builtins
import importlib
import os
import subprocess
import sys

import pytest

import roomkit_ui.cleanup
from roomkit_ui.cleanup import post_cleanup_monitor
from roomkit_ui.cli_exec import _kill, resolve_command


@pytest.fixture
def no_resource_module(monkeypatch):
    """Make ``import resource`` raise, the way it does on Windows."""
    real_import = builtins.__import__

    def _import(name, *args, **kwargs):
        if name == "resource":
            raise ImportError("No module named 'resource'")
        return real_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "resource", raising=False)
    monkeypatch.setattr(builtins, "__import__", _import)


def test_cleanup_imports_without_the_resource_module(no_resource_module):
    # engine imports cleanup at startup, so a module-scope `import resource`
    # here takes the whole app down before a window opens.
    importlib.reload(roomkit_ui.cleanup)


async def test_cpu_monitor_gives_up_quietly_without_the_resource_module(no_resource_module):
    # The monitor only logs CPU usage. Losing it where the API does not exist
    # is the intended trade; taking the session down with it is not.
    await post_cleanup_monitor()


def test_kill_falls_back_where_the_platform_has_no_process_groups(monkeypatch):
    # os.killpg/os.getpgid are POSIX-only, so Windows raises AttributeError on
    # the lookup — which the OSError catch around the call never covered.
    monkeypatch.delattr(os, "killpg", raising=False)
    monkeypatch.delattr(os, "getpgid", raising=False)
    proc = subprocess.Popen(resolve_command("sleep") + ["30"])

    _kill(proc)

    assert proc.wait(timeout=5) != 0
