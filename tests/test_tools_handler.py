"""Tests for :mod:`autodl_cli.handlers.tools`, all offline."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from autodl_cli.client import AutoDLClient
from autodl_cli.handlers import tools

Handler = Callable[[httpx.Request], httpx.Response]

AUTODL_URL = "https://www.autodl.com/api/v1/example"


def _client(handler: Handler, token: str | None = "fake-token") -> AutoDLClient:
    """Build a client backed by an in-process mock transport.

    :param handler: Mock transport callback.
    :param token: Optional API token.
    :returns: A client that never touches the network.
    """
    return AutoDLClient(token, transport=httpx.MockTransport(handler))


def test_relative_url_joins_base_url_and_sends_autodl_headers() -> None:
    """A relative path is joined to the base URL and gets AutoDL headers."""
    seen: dict[str, str | None] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers.get("Authorization")
        seen["app_version"] = request.headers.get("AppVersion")
        return httpx.Response(200, json={"ok": True})

    with _client(handler) as client:
        result = tools.send_request(client, "GET", "/api/v1/example")

    assert seen == {
        "url": AUTODL_URL,
        "authorization": "fake-token",
        "app_version": "v6.53.0",
    }
    assert result["url"] == AUTODL_URL
    assert result["status"] == 200
    assert result["is_json"] is True
    assert result["json"] == {"ok": True}


def test_absolute_external_url_withholds_autodl_headers() -> None:
    """An external host never receives the AutoDL token or AppVersion."""
    seen: dict[str, str | None] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers.get("Authorization")
        seen["app_version"] = request.headers.get("AppVersion")
        return httpx.Response(200, text="pong")

    with _client(handler) as client:
        result = tools.send_request(client, "GET", "https://example.com/ping")

    assert seen == {"url": "https://example.com/ping", "authorization": None, "app_version": None}
    assert result["url"] == "https://example.com/ping"
    assert result["status"] == 200
    assert result["is_json"] is False
    assert result["json"] is None
    assert result["text"] == "pong"


def test_absolute_autodl_url_sends_autodl_headers() -> None:
    """An absolute URL on the AutoDL origin is treated as an API request."""
    seen: dict[str, str | None] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers.get("Authorization")
        seen["app_version"] = request.headers.get("AppVersion")
        return httpx.Response(200, json={})

    with _client(handler) as client:
        tools.send_request(client, "GET", AUTODL_URL)

    assert seen == {
        "url": AUTODL_URL,
        "authorization": "fake-token",
        "app_version": "v6.53.0",
    }


@pytest.mark.parametrize(
    "url",
    [
        "https://autodl.com/api/v1/example",
        "https://www.autodl.com/api/v1/example",
        "https://region-1.autodl.com/api/v1/example",
    ],
)
def test_every_autodl_com_host_receives_autodl_headers(url: str) -> None:
    """The apex domain and all of its subdomains receive AutoDL headers."""
    seen: dict[str, str | None] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers.get("Authorization")
        seen["app_version"] = request.headers.get("AppVersion")
        return httpx.Response(200, json={})

    with _client(handler) as client:
        tools.send_request(client, "GET", url)

    assert seen == {"url": url, "authorization": "fake-token", "app_version": "v6.53.0"}


@pytest.mark.parametrize(
    "url",
    [
        "https://autodl.com.example.org/api/v1/example",
        "https://notautodl.com/api/v1/example",
    ],
)
def test_lookalike_hosts_never_receive_autodl_headers(url: str) -> None:
    """A host that merely resembles AutoDL is treated as external."""
    seen: dict[str, str | None] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers.get("Authorization")
        seen["app_version"] = request.headers.get("AppVersion")
        return httpx.Response(200, json={})

    with _client(handler) as client:
        tools.send_request(client, "GET", url)

    assert seen == {"authorization": None, "app_version": None}


def test_json_data_is_sent_as_json() -> None:
    """JSON ``--data`` becomes a JSON body with a JSON content type."""
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["content"] = request.content
        seen["content_type"] = request.headers.get("Content-Type")
        return httpx.Response(200, json={})

    with _client(handler) as client:
        tools.send_request(client, "POST", "/api/v1/example", data='{"name": "value"}')

    assert seen["content"] == b'{"name":"value"}'
    assert str(seen["content_type"]).startswith("application/json")


def test_non_json_data_is_sent_as_form_content() -> None:
    """Non-JSON ``--data`` becomes raw form content."""
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["content"] = request.content
        seen["content_type"] = request.headers.get("Content-Type")
        return httpx.Response(200, json={})

    with _client(handler) as client:
        tools.send_request(client, "POST", "/api/v1/example", data="name=value&other=1")

    assert seen["content"] == b"name=value&other=1"
    assert seen["content_type"] == "application/x-www-form-urlencoded"


def test_user_supplied_content_type_is_kept() -> None:
    """An explicit ``Content-Type`` header is not overwritten."""
    seen: dict[str, str | None] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["content_type"] = request.headers.get("Content-Type")
        return httpx.Response(200, json={})

    with _client(handler) as client:
        tools.send_request(
            client,
            "POST",
            "/api/v1/example",
            headers={"Content-Type": "text/plain"},
            data="raw body",
        )

    assert seen["content_type"] == "text/plain"


def test_non_2xx_response_is_returned_raw() -> None:
    """A failed response is returned instead of raising an API error."""
    payload = {"code": "Fail", "msg": "boom"}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json=payload)

    with _client(handler) as client:
        result = tools.send_request(client, "GET", "/api/v1/example")

    assert result["status"] == 500
    assert result["reason"] == "Internal Server Error"
    assert result["is_json"] is True
    assert result["json"] == payload


def test_include_auth_false_omits_authorization() -> None:
    """``--no-auth`` withholds the token but keeps AppVersion on AutoDL."""
    seen: dict[str, str | None] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers.get("Authorization")
        seen["app_version"] = request.headers.get("AppVersion")
        return httpx.Response(200, json={})

    with _client(handler) as client:
        tools.send_request(client, "GET", "/api/v1/example", include_auth=False)

    assert seen == {"authorization": None, "app_version": "v6.53.0"}


def test_extra_header_overrides_default_case_insensitively() -> None:
    """A differently-cased header replaces the default instead of duplicating it."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.extend(request.headers.get_list("Authorization"))
        return httpx.Response(200, json={})

    with _client(handler) as client:
        tools.send_request(
            client,
            "GET",
            "/api/v1/example",
            headers={"authorization": "Bearer override"},
        )

    assert seen == ["Bearer override"]


def test_build_curl_includes_method_headers_data_and_quoting() -> None:
    """The generated command carries the method, headers, body, and URL."""
    headers = {
        "Authorization": "fake-token",
        "AppVersion": "v6.53.0",
        "Content-Length": "10",
        "Host": "www.autodl.com",
    }

    command = tools.build_curl(AUTODL_URL, "post", headers, data='{"name": "value"}')

    assert command.startswith("curl ")
    assert "-X POST" in command
    assert "-H 'Authorization: fake-token'" in command
    assert "-H 'AppVersion: v6.53.0'" in command
    assert '--data \'{"name": "value"}\'' in command
    assert AUTODL_URL in command
    assert "Content-Length" not in command
    assert "Host" not in command
    assert " \\\n  " in command


def test_build_curl_omits_method_for_get() -> None:
    """``-X`` is omitted for GET requests."""
    command = tools.build_curl(AUTODL_URL, "GET", {"Accept": "application/json"})

    assert "-X" not in command
    assert "-H 'Accept: application/json'" in command
