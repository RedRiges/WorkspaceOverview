"""Exercise actual command forwarding and resident lifetime on a private bus."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

if os.environ.get("WORKSPACE_OVERVIEW_NATIVE_TESTS") != "1":
    pytest.skip("requires an isolated X11 test display", allow_module_level=True)


def test_resident_ram_cache_lifecycle():
    result = subprocess.run(
        [
            "dbus-run-session",
            "--",
            sys.executable,
            str(Path(__file__).with_name("resident_session.py")),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
