"""Authenticated HTTP client for the AutoDL developer API.

TODO: implement request signing headers, timeouts, retries, and translation
of HTTP failures into the exception types in :mod:`autodl_cli.errors`.
Handlers must go through this class instead of calling ``httpx`` directly.
"""

from __future__ import annotations


class AutoDLClient:
    """Authenticated client for the AutoDL developer API."""

    def __init__(self, token: str, *, base_url: str, timeout: float = 30.0) -> None:
        """Create a client.

        :param token: AutoDL API token.
        :param base_url: API root, without a trailing slash.
        :param timeout: Per-request timeout in seconds.
        """
        ...

    def request(self, method: str, path: str, **kwargs: object) -> dict[str, object]:
        """Send one API request.

        :param method: HTTP method.
        :param path: Path relative to ``base_url``.
        :param kwargs: Extra arguments forwarded to the underlying client.
        :returns: The decoded JSON object.
        :raises autodl_cli.errors.AutoDLError: For every API failure.
        """
        ...
