"""CLI smoke test over a subprocess.

Runs the real console entry point (``python -m autodl_cli.main``) the way a
script would and checks the contract ``--json`` promises: exit code 0, clean
JSON on stdout, and no ANSI escapes even when the output is piped.

The subprocess inherits ``AUTODL_CLI_HOME`` from the test session, so it reads
and writes the isolated test tree rather than the user's real data directory.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

#: Variables that would force colour on a piped stdout and make the
#: "no ANSI escapes" assertion depend on the developer's shell.
_COLOUR_OVERRIDES = ("FORCE_COLOR", "CLICOLOR_FORCE")


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    """Run the ``autodl`` console entry point in a subprocess.

    :param args: Arguments passed after ``python -m autodl_cli.main``.
    :returns: The completed process, with stdout and stderr captured as text.
    """
    env = {key: value for key, value in os.environ.items() if key not in _COLOUR_OVERRIDES}
    return subprocess.run(
        [sys.executable, "-m", "autodl_cli.main", *args],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_cli_help_smoke() -> None:
    """``autodl --help`` starts and exits cleanly."""
    result = _run("--help")

    assert result.returncode == 0, result.stderr
    assert "Commands:" in result.stdout
    assert not _ANSI_ESCAPE.search(result.stdout)


def test_json_output_is_clean() -> None:
    """``--json`` writes parseable JSON to stdout and nothing else."""
    result = _run("--json", "config", "base-url", "show")

    assert result.returncode == 0, result.stderr
    assert not _ANSI_ESCAPE.search(result.stdout)

    payload = json.loads(result.stdout)
    assert isinstance(payload, dict)
    assert "base_url" in payload
