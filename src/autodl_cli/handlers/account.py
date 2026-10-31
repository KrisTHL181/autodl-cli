"""Account-domain API handlers.

The wallet balance lives behind ``GET /api/v1/wallet/balance`` and the account
profile behind ``GET /api/v1/user/detail``. AutoDL returns money values as
integers of thousandths of a yuan, so callers that display or aggregate them
must divide by :data:`MILLIYUAN_PER_YUAN`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from autodl_cli.errors import AuthError
from autodl_cli.handlers._common import require_success

if TYPE_CHECKING:
    from autodl_cli.client import AutoDLClient

#: Path of the wallet balance endpoint.
WALLET_BALANCE_PATH = "/api/v1/wallet/balance"

#: Path of the account profile endpoint.
USER_DETAIL_PATH = "/api/v1/user/detail"

#: Every monetary field AutoDL returns is an integer of thousandths of a yuan.
MILLIYUAN_PER_YUAN = 1000


def get_balance(client: AutoDLClient, *, charge_type: str = "payg") -> dict[str, object]:
    """Return the account balance for one billing mode.

    :param client: Authenticated API client.
    :param charge_type: Billing mode to query; ``"payg"`` (pay-as-you-go) by
        default.
    :returns: The wallet mapping. Monetary fields (``assets``,
        ``blocked_asset``, ``accumulate``, ``voucher_balance``, and others) are
        raw thousandths of a yuan.
    :raises autodl_cli.errors.AuthError: When the token is rejected.
    :raises autodl_cli.errors.APIError: When the API reports any other failure
        or returns malformed data.
    """
    payload = client.request("GET", WALLET_BALANCE_PATH, params={"charge_type": charge_type})
    return require_success(payload, action="balance")


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
