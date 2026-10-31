"""Plumbing for the live integration suite: gating and isolation.

Nothing here runs by default. The ``live`` tests are collected but skipped
unless ``--live`` is passed at the command line, and anything marked
``live_write`` additionally needs ``--live-write``. A plain ``pytest`` run
therefore makes zero network requests.

The data tree is relocated by ``tests/conftest.py`` before any project import.
The autouse :func:`_live_home_guard` below re-checks that redirect anyway: if
``AUTODL_CLI_HOME`` points outside the test sandbox, every live test is skipped
with a loud message rather than touching real data or a real account.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from _pytest.config import Config
    from _pytest.nodes import Item

_LIVE_DIR = Path(__file__).resolve().parent
_DEFAULT_TEST_HOME = _LIVE_DIR.parent / ".state"


def pytest_collection_modifyitems(config: Config, items: list[Item]) -> None:
    """Skip live tests unless the matching flags were passed.

    The options themselves are registered in ``tests/conftest.py`` so they also
    parse from the repository root.

    :param config: pytest's configuration object.
    :param items: Every collected test item.
    """
    run_write = config.getoption("--live-write")
    # --live-write implies --live, as its help text promises.
    run_live = config.getoption("--live") or run_write

    skip_live = pytest.mark.skip(reason="live test: pass --live to run it against the real AutoDL API")
    skip_write = pytest.mark.skip(reason="live write test: pass --live --live-write to run it against a real account")

    for item in items:
        if item.get_closest_marker("live") is not None and not run_live:
            item.add_marker(skip_live)
        elif item.get_closest_marker("live_write") is not None and not run_write:
            item.add_marker(skip_write)


@pytest.fixture(scope="session", autouse=True)
def _live_home_guard() -> None:
    """Refuse to run live tests unless the data tree is inside the test sandbox.

    :raises pytest.skip.Exception: If ``AUTODL_CLI_HOME`` is unset or points
        outside the isolated test tree.
    """
    expected = Path(os.environ.get("AUTODL_TEST_HOME") or _DEFAULT_TEST_HOME).expanduser().resolve()
    configured = os.environ.get("AUTODL_CLI_HOME", "").strip()
    actual = Path(configured).expanduser().resolve() if configured else None

    if actual is None or not actual.is_relative_to(expected):
        pytest.skip(
            "REFUSING TO RUN LIVE TESTS: AUTODL_CLI_HOME is "
            f"{actual}, outside the isolated test tree {expected}. "
            "Run the suite from the repository root, or unset AUTODL_CLI_HOME."
        )


@pytest.fixture(scope="session")
def budget(request: pytest.FixtureRequest) -> int:
    """Return the maximum number of HTTP requests a live session may send.

    :param request: pytest's fixture request, used to read ``--live-budget``.
    :returns: The request cap; ``0`` means unlimited.
    """
    return request.config.getoption("--live-budget")
