"""Shared helpers for command modules.

Command authors should use these instead of reimplementing token handling.
"""

from __future__ import annotations

import click


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
