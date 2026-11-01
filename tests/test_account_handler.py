"""Tests for :mod:`autodl_cli.handlers.account`, all offline."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from autodl_cli.client import APP_VERSION, AutoDLClient
from autodl_cli.errors import APIError, AuthError
from autodl_cli.handlers import account as account_handler

TOKEN = "fake-token"
BALANCE = {
    "id": 1,
    "uid": 42,
    "assets": 12345,
    "blocked_asset": 0,
    "accumulate": 67890,
    "created_at": "2026-01-01 00:00:00",
    "updated_at": "2026-10-31 00:00:00",
    "voucher_balance": 1000,
    "available_coupon_num": 2,
    "to_expire_voucher_num": 1,
    "certain_conditions_voucher_balance": 0,
    "remittance_code": "",
    "total_recharge_asset": 500000,
    "exclusive_transfer_account": "",
}
BALANCE_YUAN = {
    **BALANCE,
    "assets": 12.345,
    "blocked_asset": 0.0,
    "accumulate": 67.89,
    "voucher_balance": 1.0,
    "certain_conditions_voucher_balance": 0.0,
    "total_recharge_asset": 500.0,
}
ACCOUNT = {
    "id": 42,
    "username": "tester",
    "nickname": "",
    "email": "tester@example.com",
    "email_confirmed": True,
    "phone_area": "+86",
    "phone": "13800138000",
    "status": "normal",
    "created_at": "2026-01-01T00:00:00+08:00",
    "logged_in_at": "2026-10-31T23:28:26.905+08:00",
    "max_instance_num": 30,
    "sub_user_num": 10,
    "private_image_num": 20,
}

Handler = Callable[[httpx.Request], httpx.Response]


def _success(data: dict[str, object]) -> httpx.Response:
    """Build a successful API envelope.

    :param data: The ``data`` object to wrap.
    :returns: A mock HTTP response.
    """
    return httpx.Response(200, json={"code": "Success", "msg": "", "data": data, "request_id": "req-1"})


def test_get_balance_requests_wallet_endpoint() -> None:
    """The handler sends an authenticated GET with the billing mode as a query parameter."""
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["charge_type"] = request.url.params.get("charge_type")
        seen["authorization"] = request.headers.get("Authorization")
        seen["app_version"] = request.headers.get("AppVersion")
        seen["body"] = request.content
        return _success(BALANCE)

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        assert account_handler.get_balance(client) == BALANCE_YUAN

    assert seen == {
        "method": "GET",
        "path": "/api/v1/wallet/balance",
        "charge_type": "payg",
        "authorization": TOKEN,
        "app_version": APP_VERSION,
        "body": b"",
    }


def test_get_balance_forwards_custom_charge_type() -> None:
    """A non-default billing mode is sent unchanged."""
    seen: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params.get("charge_type"))
        return _success(BALANCE)

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        account_handler.get_balance(client, charge_type="prepaid")

    assert seen == ["prepaid"]


def test_get_balance_auth_failure_raises_auth_error() -> None:
    """An ``AuthorizeFailed`` envelope becomes an :class:`AuthError` with context."""
    payload = {
        "code": "AuthorizeFailed",
        "msg": "login timed out",
        "data": None,
        "request_id": "req-9",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AuthError) as excinfo:
            account_handler.get_balance(client)

    assert "login timed out" in str(excinfo.value)
    assert "req-9" in str(excinfo.value)


def test_get_balance_other_failure_raises_api_error() -> None:
    """Any other non-success code becomes an :class:`APIError`."""
    payload = {"code": "RequestParameterIsWrong", "msg": "bad charge_type", "data": None}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(APIError) as excinfo:
            account_handler.get_balance(client, charge_type="nope")

    assert "bad charge_type" in str(excinfo.value)


def test_get_me_requests_user_detail_endpoint() -> None:
    """``GET /api/v1/user/detail`` is authenticated and unwrapped."""
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        seen["authorization"] = request.headers.get("Authorization")
        return _success(ACCOUNT)

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        assert account_handler.get_me(client) == ACCOUNT

    assert seen == {
        "method": "GET",
        "path": "/api/v1/user/detail",
        "params": {},
        "authorization": TOKEN,
    }


def test_get_me_auth_failure_raises_auth_error() -> None:
    """A rejected token becomes an :class:`AuthError` with context."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"code": "TokenExpired", "msg": "token expired", "data": None, "request_id": "req-7"},
        )

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AuthError) as excinfo:
            account_handler.get_me(client)

    assert "token expired" in str(excinfo.value)
    assert "req-7" in str(excinfo.value)


def test_get_me_malformed_data_raises_api_error() -> None:
    """A successful envelope without object ``data`` is malformed."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": "Success", "msg": "", "data": None})

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(APIError) as excinfo:
            account_handler.get_me(client)

    assert "malformed data" in str(excinfo.value)


def test_get_balance_malformed_data_raises_api_error() -> None:
    """A successful envelope without object ``data`` is malformed."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": "Success", "msg": "", "data": None})

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(APIError) as excinfo:
            account_handler.get_balance(client)

    assert "malformed data" in str(excinfo.value)
