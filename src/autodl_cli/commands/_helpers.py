"""Shared helpers for command modules.

Command authors should use these instead of reimplementing token handling or
client construction.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import click

from autodl_cli.client import AutoDLClient
from autodl_cli.config import get_app_version, get_base_url, get_timeout

if TYPE_CHECKING:
    from collections.abc import Mapping


def build_client(token: str | None, config: Mapping[str, object]) -> AutoDLClient:
    """Create a client configured from the local settings.

    :param token: API token, or ``None`` for an unauthenticated client.
    :param config: Parsed local config.
    :returns: A client using the configured base URL, timeout, and AppVersion.
    """
    return AutoDLClient(
        token,
        base_url=get_base_url(config),
        timeout=get_timeout(config),
        app_version=get_app_version(config),
    )


def require_token(config: dict[str, object]) -> str:
    """Return the API token, or fail with a clean CLI error.

    :param config: Parsed local config.
    :returns: The API token.
    :raises click.ClickException: When no token is configured.
    """
    token = config.get("token")
    if isinstance(token, str) and token:
        return token
    raise click.ClickException("Not authenticated. Run `autodl auth paste` first.")
