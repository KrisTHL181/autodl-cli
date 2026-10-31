"""Tests for :mod:`autodl_cli.handlers.auth`."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable

import httpx
import pytest

from autodl_cli import __version__
from autodl_cli.client import APP_VERSION, AutoDLClient
from autodl_cli.errors import APIError, AuthError
from autodl_cli.handlers import auth as auth_handler

PHONE = "13800138000"
PASSWORD = "secret"
PHONE_AREA = "+86"
TICKET = "fake-ticket"
TOKEN = "fake-token"
FINGERPRINT = "0123456789abcdef0123456789abcdef"
USER = {"id": 42, "username": "tester"}

Handler = Callable[[httpx.Request], httpx.Response]


def test_hash_password_matches_sha1_vector() -> None:
    """Passwords are hashed as unsalted lowercase SHA-1 hex digests."""
    assert auth_handler.hash_password("password") == hashlib.sha1(b"password").hexdigest()
    assert auth_handler.hash_password("password") == "5baa61e4c9b93f3f0682250b6cf8331b7ee68fd8"


def test_generate_device_fingerprint_shape() -> None:
    """A generated fingerprint is 32 lowercase hexadecimal characters."""
    first = auth_handler.generate_device_fingerprint()
    second = auth_handler.generate_device_fingerprint()

    assert re.fullmatch(r"[0-9a-f]{32}", first)
    assert re.fullmatch(r"[0-9a-f]{32}", second)
    assert first != second


def test_describe_device_shape() -> None:
    """The passport device block identifies the CLI and its version."""
    device = auth_handler.describe_device()

    assert set(device) == {"os", "browser"}
    browser = device["browser"]
    assert isinstance(browser, dict)
    assert browser["name"] == "autodl-cli"
    assert browser["version"] == __version__
    assert browser["major"] == __version__.partition(".")[0]


def test_login_sends_exact_two_request_flow() -> None:
    """Both request bodies match the verified website contract."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/v1/new_login":
            return httpx.Response(
                200,
                json={
                    "code": "Success",
                    "data": {"ticket": TICKET, "user": USER},
                    "msg": "",
                    "request_id": "request-1",
                },
            )
        if request.url.path == "/api/v1/passport":
            return httpx.Response(
                200,
                json={"code": "Success", "data": {"token": TOKEN}, "msg": "", "request_id": "request-2"},
            )
        return httpx.Response(404, json={"code": "NotFound", "msg": "unexpected path"})

    with AutoDLClient(None, transport=httpx.MockTransport(handler)) as client:
        result = auth_handler.login(
            client,
            PHONE,
            PASSWORD,
            phone_area=PHONE_AREA,
            device_fingerprint=FINGERPRINT,
        )

    assert result == {"token": TOKEN, "user": USER, "device_fingerprint": FINGERPRINT}
    assert [request.url.path for request in requests] == ["/api/v1/new_login", "/api/v1/passport"]
    first, second = requests

    assert first.method == "POST"
    assert first.headers["AppVersion"] == APP_VERSION
    assert json.loads(first.content) == {
        "phone": PHONE,
        "password": hashlib.sha1(PASSWORD.encode("utf-8")).hexdigest(),
        "v_code": "",
        "phone_area": PHONE_AREA,
        "captcha_verify_param": None,
        "device_fingerprint": FINGERPRINT,
    }

    assert second.method == "POST"
    assert second.headers["AppVersion"] == APP_VERSION
    passport = json.loads(second.content)
    assert passport == {"ticket": TICKET, "device": auth_handler.describe_device()}
    assert passport["device"]["browser"]["name"] == "autodl-cli"


def test_login_generates_fingerprint_when_omitted() -> None:
    """A fingerprint is generated and reported when the caller passes none."""
    login_bodies: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/new_login":
            login_bodies.append(json.loads(request.content))
            return httpx.Response(200, json={"code": "Success", "data": {"ticket": TICKET, "user": USER}})
        return httpx.Response(200, json={"code": "Success", "data": {"token": TOKEN}})

    with AutoDLClient(None, transport=httpx.MockTransport(handler)) as client:
        result = auth_handler.login(client, PHONE, PASSWORD)

    fingerprint = result["device_fingerprint"]
    assert isinstance(fingerprint, str)
    assert re.fullmatch(r"[0-9a-f]{32}", fingerprint)
    assert login_bodies[0]["device_fingerprint"] == fingerprint


def test_login_non_success_raises_auth_error() -> None:
    """A non-``Success`` envelope becomes an :class:`AuthError` with context."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"code": "PasswordError", "data": None, "msg": "wrong password", "request_id": "req-9"},
        )

    with AutoDLClient(None, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AuthError) as excinfo:
            auth_handler.login(client, PHONE, PASSWORD, device_fingerprint=FINGERPRINT)

    assert "wrong password" in str(excinfo.value)
    assert "req-9" in str(excinfo.value)


def test_login_missing_ticket_raises_api_error() -> None:
    """A successful login response without a ticket is malformed."""
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(200, json={"code": "Success", "data": {"user": USER}})

    with AutoDLClient(None, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(APIError) as excinfo:
            auth_handler.login(client, PHONE, PASSWORD, device_fingerprint=FINGERPRINT)

    assert "ticket" in str(excinfo.value)
    assert paths == ["/api/v1/new_login"]


def test_login_missing_token_raises_api_error() -> None:
    """A successful passport response without a token is malformed."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/new_login":
            return httpx.Response(200, json={"code": "Success", "data": {"ticket": TICKET, "user": USER}})
        return httpx.Response(200, json={"code": "Success", "data": {}})

    with AutoDLClient(None, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(APIError) as excinfo:
            auth_handler.login(client, PHONE, PASSWORD, device_fingerprint=FINGERPRINT)

    assert "token" in str(excinfo.value)


def test_get_current_user_unwraps_user_detail() -> None:
    """``GET /api/v1/user/detail`` is authenticated and unwrapped."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/v1/user/detail"
        assert request.headers["Authorization"] == TOKEN
        return httpx.Response(200, json={"code": "Success", "data": USER, "msg": "", "request_id": "req-3"})

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        assert auth_handler.get_current_user(client) == USER


def test_get_current_user_non_success_raises_auth_error() -> None:
    """A rejected token becomes an :class:`AuthError` with the server message."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": "AuthError", "data": None, "msg": "token expired"})

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AuthError) as excinfo:
            auth_handler.get_current_user(client)

    assert "token expired" in str(excinfo.value)


def test_get_current_user_malformed_data_raises_api_error() -> None:
    """A successful envelope without object ``data`` is malformed."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": "Success", "data": None, "msg": ""})

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(APIError) as excinfo:
            auth_handler.get_current_user(client)

    assert "malformed data" in str(excinfo.value)
