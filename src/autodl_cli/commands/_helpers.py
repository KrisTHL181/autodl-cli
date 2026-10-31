"""Shared helpers for command modules.

Command authors should use these instead of reimplementing argument
normalisation or token handling.
"""

from __future__ import annotations


def parse_instance_id(value: str) -> str:
    """Normalise an instance identifier from the command line.

    :param value: Raw ``--instance`` value or positional argument.
    :returns: The canonical instance ID.
    :raises click.BadParameter: When the value is not a valid instance ID.
    """
    ...


def require_token(config: dict[str, object]) -> str:
    """Return the API token, or fail with a clean CLI error.

    :param config: Parsed local config.
    :returns: The API token.
    :raises click.ClickException: When no token is configured.
    """
    ...
