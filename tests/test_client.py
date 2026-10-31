"""Tests for :mod:`autodl_cli.client`, all offline via ``httpx.MockTransport``."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from autodl_cli.client import APP_VERSION, AutoDLClient
from autodl_cli.errors import APIError, AuthError, NotFoundError, RateLimitError

Handler = Callable[[httpx.Request], httpx.Response]


def _client(handler: Handler, token: str | None = None) -> AutoDLClient:
    """Build a client backed by an in-process mock transport.

    :param handler: Mock transport callback.
    :param token: Optional API token.
    :returns: A client that never touches the network.
    """
    return AutoDLClient(token, transport=httpx.MockTransport(handler))


def test_returns_decoded_object() -> None:
    """A successful request returns the decoded JSON object."""
    payload = {"code": "Success", "data": {"ok": True}}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    with _client(handler) as client:
        assert client.request("GET", "/api/v1/example") == payload


def test_app_version_header_on_every_request() -> None:
    """Every request carries the mandatory ``AppVersion`` header."""
    seen: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("AppVersion"))
        return httpx.Response(200, json={})

    with _client(handler) as client:
        client.request("GET", "/api/v1/one")
        client.request("POST", "/api/v1/two", json={})

    assert seen == [APP_VERSION, APP_VERSION]


@pytest.mark.parametrize(("token", "expected"), [(None, None), ("", None), ("fake-token", "fake-token")])
def test_authorization_header_present_iff_token(token: str | None, expected: str | None) -> None:
    """``Authorization`` is sent only when the token is non-empty."""
    seen: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("Authorization"))
        return httpx.Response(200, json={})

    with _client(handler, token) as client:
        client.request("GET", "/api/v1/example")

    assert seen == [expected]


@pytest.mark.parametrize(
    ("status", "error_type"),
    [
        (401, AuthError),
        (403, AuthError),
        (404, NotFoundError),
        (429, RateLimitError),
        (500, APIError),
    ],
)
def test_http_errors_map_to_api_exceptions(status: int, error_type: type[Exception]) -> None:
    """Each status code maps to its dedicated exception with context."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"code": "Fail", "msg": "server said no"})

    with _client(handler) as client:
        with pytest.raises(error_type) as excinfo:
            client.request("GET", "/api/v1/example")

    message = str(excinfo.value)
    assert str(status) in message
    assert "server said no" in message


def test_network_error_maps_to_api_error() -> None:
    """A transport failure becomes an :class:`APIError`."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with _client(handler) as client:
        with pytest.raises(APIError) as excinfo:
            client.request("GET", "/api/v1/example")

    assert "connection refused" in str(excinfo.value)


def test_non_json_body_maps_to_api_error() -> None:
    """A 2xx response with a non-JSON body becomes an :class:`APIError`."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not json</html>")

    with _client(handler) as client:
        with pytest.raises(APIError) as excinfo:
            client.request("GET", "/api/v1/example")

    assert "invalid JSON" in str(excinfo.value)


def test_non_object_json_body_maps_to_api_error() -> None:
    """A 2xx response whose JSON is not an object becomes an :class:`APIError`."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[1, 2, 3])

    with _client(handler) as client:
        with pytest.raises(APIError) as excinfo:
            client.request("GET", "/api/v1/example")

    assert "non-object" in str(excinfo.value)
