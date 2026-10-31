"""Tests for :mod:`autodl_cli.commands._helpers`."""

from __future__ import annotations

import click
import pytest

from autodl_cli.client import APP_VERSION, DEFAULT_BASE_URL
from autodl_cli.commands._helpers import build_client, require_token
from autodl_cli.config import DEFAULT_TIMEOUT


def test_build_client_uses_configured_settings() -> None:
    """Base URL, timeout, and AppVersion come from the config mapping."""
    config = {
        "base_url": "https://mirror.example.com",
        "timeout": 5,
        "app_version": "v9.99.0",
    }

    with build_client("fake-token", config) as client:
        assert client.base_url == "https://mirror.example.com"
        assert client.app_version == "v9.99.0"
        assert client._client.timeout.read == 5.0
        assert client.headers_for()["AppVersion"] == "v9.99.0"


def test_build_client_falls_back_to_defaults() -> None:
    """An empty config yields the module defaults."""
    with build_client(None, {}) as client:
        assert client.base_url == DEFAULT_BASE_URL
        assert client.app_version == APP_VERSION
        assert client._client.timeout.read == DEFAULT_TIMEOUT
        assert "Authorization" not in client.headers_for()


def test_require_token_returns_non_empty_token() -> None:
    """A configured token is returned unchanged."""
    assert require_token({"token": "fake-token"}) == "fake-token"


@pytest.mark.parametrize("config", [{}, {"token": ""}, {"token": None}, {"token": 123}])
def test_require_token_raises_with_paste_hint(config: dict[str, object]) -> None:
    """Missing or non-string tokens produce the paste hint."""
    with pytest.raises(click.ClickException) as excinfo:
        require_token(config)

    assert "autodl auth paste" in str(excinfo.value)
