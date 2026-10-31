"""Live CLI smoke test over a subprocess.

TODO: once ``autodl_cli.main.main`` is implemented, run the real console entry
point (``python -m autodl_cli.main``) and check the contract ``--json``
promises to scripts: exit code 0, clean JSON on stdout, no ANSI escapes.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.live


@pytest.mark.skip(reason="TODO: implement autodl_cli.main.main() first")
def test_cli_help_smoke() -> None:
    """``autodl --help`` starts and exits cleanly."""
