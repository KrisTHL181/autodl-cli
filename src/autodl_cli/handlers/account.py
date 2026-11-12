"""Account-domain API handlers.

The wallet balance lives behind ``GET /api/v1/wallet/balance`` and the account
profile behind ``GET /api/v1/user/detail``. AutoDL returns money values in a
smaller integer unit; :func:`get_balance` converts every monetary field to a
yuan float, so callers never have to handle it.

Billing usage lives behind ``GET /api/v1/billing/statistic``. Unlike the wallet
endpoints, it reports money as decimal strings that are already in yuan, so
:func:`get_usage_statistics` converts them to floats without applying the
milliyuan unit.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from autodl_cli.errors import APIError, AuthError
from autodl_cli.handlers._common import require_success, require_success_list
from autodl_cli.money import BALANCE_MONEY_FIELDS, to_yuan

if TYPE_CHECKING:
    from autodl_cli.client import AutoDLClient

#: Path of the wallet balance endpoint.
WALLET_BALANCE_PATH = "/api/v1/wallet/balance"

#: Path of the account profile endpoint.
USER_DETAIL_PATH = "/api/v1/user/detail"

#: Path of the billing-statistic endpoint used by ``account usage``.
BILLING_STATISTIC_PATH = "/api/v1/billing/statistic"

#: Granularities accepted by the billing-statistic endpoint.
USAGE_GRANULARITIES = ("monthly", "daily")

#: Billing-statistic fields reported as decimal yuan strings.
USAGE_MONEY_FIELDS = (
    "asset_sum",
    "pay_by_balance_sum",
    "pay_by_voucher_sum",
    "refund_asset_sum",
)


def get_balance(client: AutoDLClient, *, charge_type: str = "payg") -> dict[str, object]:
    """Return the account balance for one billing mode.

    :param client: Authenticated API client.
    :param charge_type: Billing mode to query; ``"payg"`` (pay-as-you-go) by
        default.
    :returns: The wallet mapping. Monetary fields (``assets``,
        ``blocked_asset``, ``accumulate``, ``voucher_balance``, and the other
        fields in :data:`autodl_cli.money.BALANCE_MONEY_FIELDS`) are yuan
        floats; every other field is returned unchanged.
    :raises autodl_cli.errors.AuthError: When the token is rejected.
    :raises autodl_cli.errors.APIError: When the API reports any other failure
        or returns malformed data.
    """
    payload = client.request("GET", WALLET_BALANCE_PATH, params={"charge_type": charge_type})
    balance = require_success(payload, action="balance")
    converted = dict(balance)
    for field in BALANCE_MONEY_FIELDS:
        if field in converted:
            converted[field] = to_yuan(converted[field])
    return converted


def _to_yuan_float(value: object) -> object:
    """Convert a billing-statistic money value to a float.

    The endpoint reports money as decimal strings that are already in yuan, so
    no milliyuan conversion applies. Missing, ``None``, and non-numeric values
    are returned unchanged instead of failing the whole request.

    :param value: Raw money field from one billing-statistic entry.
    :returns: A float when the value is numeric, otherwise the value unchanged.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return value
    return value


def get_usage_statistics(
    client: AutoDLClient,
    *,
    granularity: str = "monthly",
    sub_name: str = "",
    exclude_sub_user: bool = False,
) -> list[dict[str, object]]:
    """Return billing usage statistics for the account.

    ``time_granularity`` controls the bucket size: ``"monthly"`` reports
    roughly the last twelve months and ``"daily"`` roughly the last fourteen
    days, in ascending date order.

    :param client: Authenticated API client.
    :param granularity: ``"monthly"`` or ``"daily"``.
    :param sub_name: Sub-user name to filter by; an empty string means every
        sub-user.
    :param exclude_sub_user: Whether to exclude sub-user transactions.
    :returns: One mapping per period. The four money fields in
        :data:`USAGE_MONEY_FIELDS` are yuan floats; ``report_date`` and
        ``transaction_count`` are returned unchanged.
    :raises ValueError: When ``granularity`` is not supported.
    :raises autodl_cli.errors.AuthError: When the token is rejected.
    :raises autodl_cli.errors.APIError: When the API reports any other failure
        or returns malformed data.
    """
    if granularity not in USAGE_GRANULARITIES:
        raise ValueError(f"granularity must be one of {', '.join(USAGE_GRANULARITIES)}")

    payload = client.request(
        "GET",
        BILLING_STATISTIC_PATH,
        params={
            "time_granularity": granularity,
            "sub_name": sub_name,
            "exclude_sub_user": exclude_sub_user,
        },
    )
    entries = require_success_list(payload, action="usage statistics")

    statistics: list[dict[str, object]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise APIError("AutoDL usage statistics returned malformed data")
        converted = dict(entry)
        for field in USAGE_MONEY_FIELDS:
            if field in converted:
                converted[field] = _to_yuan_float(converted[field])
        statistics.append(converted)
    return statistics


def get_me(client: AutoDLClient) -> dict[str, object]:
    """Return the account profile owning the client's token.

    ``user/detail`` also accepts an optional ``id`` query parameter, but
    omitting it makes AutoDL resolve the token's own account.

    :param client: Authenticated API client.
    :returns: The account mapping, including identity, contact, and quota
        fields such as ``username``, ``email``, and ``max_instance_num``.
    :raises autodl_cli.errors.AuthError: When the token is rejected.
    :raises autodl_cli.errors.APIError: When a successful response has no
        object-valued ``data`` field.
    """
    payload = client.request("GET", USER_DETAIL_PATH)
    return require_success(payload, action="user detail", error_type=AuthError)
