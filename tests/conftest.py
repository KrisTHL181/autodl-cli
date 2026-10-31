"""Global pytest setup: redirect the whole autodl-cli data tree.

The redirect must happen **before the first** ``import autodl_cli``. Modules
that capture :func:`autodl_cli.paths.autodl_home` at import time would
otherwise read or write the real ``~/.autodl-cli`` tree, and a fixture would be
too late. This conftest therefore installs the variable at the very top,
before any project import.

Nothing here imports ``autodl_cli``; nested conftest files and the tests do
that later, by which point the environment is already redirected.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from _pytest.config.argparsing import Parser

_TESTS_DIR = Path(__file__).resolve().parent

#: Where test runs keep their state. ``AUTODL_TEST_HOME`` overrides it so a
#: developer can point a run at a persistent sandbox.
HOME_DIR = Path(os.environ.get("AUTODL_TEST_HOME") or _TESTS_DIR / ".state").expanduser().resolve()

# Unconditional on purpose: an exported ``AUTODL_CLI_HOME`` must never aim a
# test run at the user's real data directory.
os.environ["AUTODL_CLI_HOME"] = str(HOME_DIR)


def pytest_addoption(parser: Parser) -> None:
    """Register the live-suite switches at the root.

    pytest only loads ``conftest.py`` files on the path given to the initial
    arguments, so an option registered in ``tests/live/conftest.py`` would be
    unknown to a bare ``pytest --live``. Registering here makes
    ``pytest --live`` and ``pytest tests/live --live`` equivalent; the hooks
    that consume the options stay in ``tests/live``.

    :param parser: pytest's option parser.
    """
    parser.addoption(
        "--live",
        action="store_true",
        default=False,
        help="run tests that hit the real AutoDL API",
    )
    parser.addoption(
        "--live-write",
        action="store_true",
        default=False,
        help="run live tests that modify a real AutoDL account (implies --live)",
    )
    parser.addoption(
        "--live-budget",
        action="store",
        type=int,
        default=80,
        help="maximum number of HTTP requests one live session may send (0 = unlimited)",
    )
