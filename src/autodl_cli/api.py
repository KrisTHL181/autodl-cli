"""Public library entry point.

Code that consumes autodl-toolkit as a library should import from here rather
than from :mod:`autodl_cli.handlers` directly. This module re-exports the
handler surface for password login, browser-token lookup, and account balance,
and normalises internal exceptions into the
:class:`~autodl_cli.errors.AutoDLError` hierarchy.
"""

from __future__ import annotations

from autodl_cli.client import AutoDLClient
from autodl_cli.handlers import account as account_handler
from autodl_cli.handlers import auth as auth_handler

__all__ = ["AutoDLClient", "get_balance", "get_current_user", "login"]


def login(
    phone: str,
    password: str,
    *,
    phone_area: str = "+86",
    device_fingerprint: str | None = None,
) -> dict[str, object]:
    """Log in with a phone number and password.

    :param phone: Phone number registered with AutoDL.
    :param password: Plaintext password.
    :param phone_area: Phone area prefix, ``"+86"`` by default.
    :param device_fingerprint: Reusable 32-character fingerprint; generated
        when ``None``.
    :returns: Mapping with ``token``, ``user``, and ``device_fingerprint``.
    :raises autodl_cli.errors.AutoDLError: For every authentication or API
        failure.
    """
    with AutoDLClient(None) as client:
        return auth_handler.login(
            client,
            phone,
            password,
            phone_area=phone_area,
            device_fingerprint=device_fingerprint,
        )


def get_balance(token: str, *, charge_type: str = "payg") -> dict[str, object]:
    """Return the account balance for one billing mode.

    :param token: AutoDL API token obtained by logging in.
    :param charge_type: Billing mode to query, ``"payg"`` by default.
    :returns: The wallet mapping; monetary fields are raw thousandths of a yuan.
    :raises autodl_cli.errors.AutoDLError: For every authentication or API
        failure.
    """
    with AutoDLClient(token) as client:
        return account_handler.get_balance(client, charge_type=charge_type)


def get_current_user(token: str) -> dict[str, object]:
    """Return the user owning an API token.

    :param token: AutoDL API token, typically copied from a browser session.
    :returns: The user detail mapping.
    :raises autodl_cli.errors.AutoDLError: For every authentication or API
        failure.
    """
    with AutoDLClient(token) as client:
        return auth_handler.get_current_user(client)
