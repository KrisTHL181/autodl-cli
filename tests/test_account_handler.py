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

USAGE = [
    {
        "asset_sum": "78.59",
        "refund_asset_sum": "0.00",
        "pay_by_balance_sum": "78.59",
        "pay_by_voucher_sum": "0.00",
        "report_date": "2025-12",
        "transaction_count": 83,
    },
]
USAGE_YUAN = [
    {
        "asset_sum": 78.59,
        "refund_asset_sum": 0.0,
        "pay_by_balance_sum": 78.59,
        "pay_by_voucher_sum": 0.0,
        "report_date": "2025-12",
        "transaction_count": 83,
    },
]

Handler = Callable[[httpx.Request], httpx.Response]


def _success(data: object) -> httpx.Response:
    """Build a successful API envelope.

    :param data: The ``data`` value to wrap.
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


def test_get_usage_statistics_requests_monthly_statistics() -> None:
    """The handler sends the monthly statistics query and converts money to floats."""
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        seen["authorization"] = request.headers.get("Authorization")
        return _success(USAGE)

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        assert account_handler.get_usage_statistics(client) == USAGE_YUAN

    assert seen == {
        "method": "GET",
        "path": "/api/v1/billing/statistic",
        "params": {
            "time_granularity": "monthly",
            "sub_name": "",
            "exclude_sub_user": "false",
        },
        "authorization": TOKEN,
    }


def test_get_usage_statistics_forwards_daily_and_filters() -> None:
    """The daily granularity and sub-user filters reach the query string."""
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        return _success(USAGE)

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        account_handler.get_usage_statistics(
            client,
            granularity="daily",
            sub_name="alice",
            exclude_sub_user=True,
        )

    assert seen == {
        "time_granularity": "daily",
        "sub_name": "alice",
        "exclude_sub_user": "true",
    }


def test_get_usage_statistics_rejects_unknown_granularity() -> None:
    """An unsupported granularity fails before any request is sent."""

    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("the API must not be called for an invalid granularity")

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError) as excinfo:
            account_handler.get_usage_statistics(client, granularity="weekly")

    assert "monthly" in str(excinfo.value)
    assert "daily" in str(excinfo.value)


def test_get_usage_statistics_tolerates_missing_or_non_numeric_money() -> None:
    """Missing, ``None``, and non-numeric money values are left untouched."""
    entry = {
        "asset_sum": "12.50",
        "pay_by_balance_sum": None,
        "pay_by_voucher_sum": "not-a-number",
        "report_date": "2025-11",
        "transaction_count": 3,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return _success([entry])

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        assert account_handler.get_usage_statistics(client) == [
            {
                "asset_sum": 12.5,
                "pay_by_balance_sum": None,
                "pay_by_voucher_sum": "not-a-number",
                "report_date": "2025-11",
                "transaction_count": 3,
            }
        ]


def test_get_usage_statistics_malformed_entry_raises_api_error() -> None:
    """A successful envelope whose list holds a non-object entry is malformed."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _success(["not-an-object"])

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(APIError) as excinfo:
            account_handler.get_usage_statistics(client)

    assert "malformed data" in str(excinfo.value)
