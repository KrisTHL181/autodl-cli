"""Tests for :mod:`autodl_cli.commands._helpers`."""

from __future__ import annotations

import click
import pytest

from autodl_cli.commands._helpers import require_token


def test_require_token_returns_non_empty_token() -> None:
    """A configured token is returned unchanged."""
    assert require_token({"token": "fake-token"}) == "fake-token"


@pytest.mark.parametrize("config", [{}, {"token": ""}, {"token": None}, {"token": 123}])
def test_require_token_raises_with_paste_hint(config: dict[str, object]) -> None:
    """Missing or non-string tokens produce the paste hint."""
    with pytest.raises(click.ClickException) as excinfo:
        require_token(config)

    assert "autodl auth paste" in str(excinfo.value)
