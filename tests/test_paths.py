"""Tests for :mod:`autodl_cli.paths` and the ``AUTODL_CLI_HOME`` override.

TODO: once :func:`autodl_cli.paths.autodl_home` is implemented, fill in the
default-directory, override, ``~`` expansion, and empty-value fallback cases
that ``zhihu-cli`` keeps in its ``test_paths.py``.
"""

from __future__ import annotations

import pytest

from autodl_cli.paths import HOME_ENV


def test_home_env_name() -> None:
    """The data-directory environment variable name stays stable."""
    assert HOME_ENV == "AUTODL_CLI_HOME"


@pytest.mark.skip(reason="TODO: paths.autodl_home() is not implemented yet")
def test_default_home() -> None:
    """Without the override the directory is ``$HOME/.autodl-cli``."""


@pytest.mark.skip(reason="TODO: paths.autodl_home() is not implemented yet")
def test_override() -> None:
    """A non-empty override is returned verbatim."""
