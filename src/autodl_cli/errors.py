"""Exception hierarchy raised by the public API.

Every error that escapes :mod:`autodl_cli.api` should be an
:class:`AutoDLError`, so library consumers can catch one type instead of the
mix of ``httpx`` and built-in exceptions handlers raise internally.

This module defines classes only and imports no third-party package.
"""

from __future__ import annotations

__all__ = [
    "APIError",
    "AutoDLError",
    "AuthError",
    "NotFoundError",
    "RateLimitError",
]


class AutoDLError(Exception):
    """Base class for every error raised by this toolkit."""


class AuthError(AutoDLError):
    """The API token is missing, invalid, or lacks permission for the operation."""


class RateLimitError(AutoDLError):
    """The AutoDL API refused the request because of rate limiting."""


class NotFoundError(AutoDLError):
    """The requested instance, image, or other resource does not exist."""


class APIError(AutoDLError):
    """A non-2xx response that does not fit a more specific error."""
