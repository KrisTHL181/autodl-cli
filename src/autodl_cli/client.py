"""Authenticated HTTP client for the AutoDL developer API.

Handlers go through this class instead of calling ``httpx`` directly. The
client adds the mandatory ``AppVersion`` header, attaches the bearer token
when one is configured, and translates every transport or HTTP failure into
the exception types in :mod:`autodl_cli.errors`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx

from autodl_cli.errors import APIError, AuthError, NotFoundError, RateLimitError

if TYPE_CHECKING:
    from collections.abc import Mapping
    from types import TracebackType

#: Root of the public AutoDL website, which also serves the developer API.
DEFAULT_BASE_URL = "https://www.autodl.com"

#: Value of the ``AppVersion`` header required by every API call.
APP_VERSION = "v6.53.0"

#: Maximum number of response-body characters included in an error message.
_SNIPPET_LIMIT = 200


def _response_detail(response: httpx.Response) -> str:
    """Return the server ``msg`` field or a short body snippet.

    :param response: Response whose body should be summarised.
    :returns: The server message when present, otherwise up to
        :data:`_SNIPPET_LIMIT` characters of the body.
    """
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        message = payload.get("msg")
        if isinstance(message, str) and message:
            return message

    snippet = " ".join(response.text.split())
    if len(snippet) > _SNIPPET_LIMIT:
        snippet = f"{snippet[:_SNIPPET_LIMIT]}..."
    return snippet


def _error_message(response: httpx.Response, method: str, path: str) -> str:
    """Build an error message that includes the status and server detail.

    :param response: The failed response.
    :param method: HTTP method used for the request.
    :param path: Path used for the request.
    :returns: A human-readable error message.
    """
    message = f"AutoDL API returned HTTP {response.status_code} for {method.upper()} {path}"
    detail = _response_detail(response)
    if detail:
        message = f"{message}: {detail}"
    return message


class AutoDLClient:
    """Authenticated client for the AutoDL developer API.

    The client is safe to use as a context manager, which closes the
    underlying connection pool on exit. It performs no automatic retries,
    because the API is not idempotent for every method.
    """

    def __init__(
        self,
        token: str | None = None,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        """Create a client.

        :param token: AutoDL API token; an empty or ``None`` value sends no
            ``Authorization`` header.
        :param base_url: API root; a trailing slash is stripped.
        :param timeout: Per-request timeout in seconds.
        :param transport: Optional httpx transport, used by offline tests to
            inject :class:`httpx.MockTransport`.
        """
        self._token = token or ""
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            transport=transport,
        )

    def headers_for(
        self,
        extra: Mapping[str, str] | None = None,
        *,
        include_auth: bool = True,
        app_version: bool = True,
    ) -> dict[str, str]:
        """Build the headers for one request.

        :param extra: Per-request headers, which override the defaults
            regardless of case.
        :param include_auth: Whether to attach the ``Authorization`` header
            when a token is configured.
        :param app_version: Whether to attach the mandatory ``AppVersion``
            header.
        :returns: The effective request headers.
        """
        headers = {"Accept": "application/json"}
        if app_version:
            headers["AppVersion"] = APP_VERSION
        if include_auth and self._token:
            headers["Authorization"] = self._token
        if extra:
            overridden = {name.lower() for name in extra}
            for name in [key for key in headers if key.lower() in overridden]:
                del headers[name]
            headers.update(extra)
        return headers

    def request(self, method: str, path: str, **kwargs: Any) -> dict[str, object]:
        """Send one API request and return its decoded JSON object.

        :param method: HTTP method.
        :param path: Path relative to ``base_url``.
        :param kwargs: Extra arguments forwarded to the underlying client.
        :returns: The decoded JSON object.
        :raises autodl_cli.errors.AuthError: On HTTP 401 or 403.
        :raises autodl_cli.errors.NotFoundError: On HTTP 404.
        :raises autodl_cli.errors.RateLimitError: On HTTP 429.
        :raises autodl_cli.errors.APIError: On a transport failure, any other
            non-2xx response, or an invalid/non-object JSON body.
        """
        headers = self.headers_for(kwargs.pop("headers", None))
        try:
            response = self._client.request(method, path, headers=headers, **kwargs)
        except httpx.RequestError as exc:
            raise APIError(f"Request to {method.upper()} {path} failed: {exc}") from exc

        status = response.status_code
        if status in (401, 403):
            raise AuthError(_error_message(response, method, path))
        if status == 404:
            raise NotFoundError(_error_message(response, method, path))
        if status == 429:
            raise RateLimitError(_error_message(response, method, path))
        if not 200 <= status < 300:
            raise APIError(_error_message(response, method, path))

        try:
            payload = response.json()
        except ValueError as exc:
            raise APIError(f"AutoDL API returned invalid JSON for {method.upper()} {path} (HTTP {status})") from exc
        if not isinstance(payload, dict):
            raise APIError(f"AutoDL API returned a non-object JSON body for {method.upper()} {path} (HTTP {status})")
        return payload

    def raw_request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        include_auth: bool = True,
        app_version: bool = True,
        **kwargs: Any,
    ) -> httpx.Response:
        """Send one request without validating or decoding the response.

        This is the debugging entry point behind ``autodl tools request``. It
        merges ``headers`` with :meth:`headers_for` and returns the response
        unchanged, so the caller can inspect non-2xx statuses and arbitrary
        bodies.

        :param method: HTTP method.
        :param url: Absolute URL, or a path relative to ``base_url``.
        :param headers: Per-request headers, which override the defaults.
        :param include_auth: Whether to attach the ``Authorization`` header
            when a token is configured.
        :param app_version: Whether to attach the ``AppVersion`` header.
        :param kwargs: Extra arguments forwarded to the underlying client.
        :returns: The raw httpx response.
        :raises autodl_cli.errors.APIError: On a transport failure.
        """
        request_headers = self.headers_for(headers, include_auth=include_auth, app_version=app_version)
        try:
            return self._client.request(method, url, headers=request_headers, **kwargs)
        except httpx.RequestError as exc:
            raise APIError(f"Request to {method.upper()} {url} failed: {exc}") from exc

    def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        self._client.close()

    def __enter__(self) -> AutoDLClient:
        """Return the client itself for use in a ``with`` statement.

        :returns: This client.
        """
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the client when leaving a ``with`` block.

        :param exc_type: Exception type, if any.
        :param exc: Exception instance, if any.
        :param traceback: Traceback, if any.
        """
        self.close()
