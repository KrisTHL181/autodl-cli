"""Public library entry point.

Code that consumes autodl-toolkit as a library should import from here rather
than from :mod:`autodl_cli.handlers` directly. This module re-exports the
handler surface for password login, browser-token lookup, account balance, and
instance listing/details, and normalises internal exceptions into the
:class:`~autodl_cli.errors.AutoDLError` hierarchy.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from autodl_cli.client import AutoDLClient
from autodl_cli.handlers import account as account_handler
from autodl_cli.handlers import auth as auth_handler
from autodl_cli.handlers import instance as instance_handler

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = [
    "AutoDLClient",
    "get_balance",
    "get_current_user",
    "get_instance",
    "list_instances",
    "login",
]


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


def list_instances(
    token: str,
    *,
    page_size: int = instance_handler.DEFAULT_PAGE_SIZE,
    statuses: Iterable[str] = (),
    charge_types: Iterable[str] = (),
    sub_name: str = "",
    unbind_sub_user: bool = False,
    query: str = "",
) -> list[dict[str, object]]:
    """Return every instance visible to an API token.

    Every page is fetched, so the result is not limited by AutoDL's
    per-request page size.

    ``query`` is applied locally, after every page has been fetched, because
    the API has no keyword field. It matches case-insensitively against the
    instance UUID, name, region, machine alias, and GPU name fields.

    :param token: AutoDL API token, typically copied from a browser session.
    :param page_size: Instances requested per API call; must be positive.
    :param statuses: Only return instances whose status is one of these values.
    :param charge_types: Only return instances with one of these billing modes.
    :param sub_name: Only return instances whose bound sub-user name matches.
    :param unbind_sub_user: Only return instances with no bound sub-user.
    :param query: Only return instances matching this text; empty means no
        filtering.
    :returns: One mapping per instance.
    :raises autodl_cli.errors.AutoDLError: For every authentication or API
        failure.
    """
    with AutoDLClient(token) as client:
        return instance_handler.list_instances(
            client,
            page_size=page_size,
            statuses=statuses,
            charge_types=charge_types,
            sub_name=sub_name,
            unbind_sub_user=unbind_sub_user,
            query=query,
        )


def get_instance(token: str, instance_uuid: str) -> dict[str, object]:
    """Return one instance's configuration snapshot.

    The snapshot describes the base image, GPU allocation, host machine, and
    prices. It does not include the live status or connection details.

    :param token: AutoDL API token, typically copied from a browser session.
    :param instance_uuid: Instance UUID as returned by :func:`list_instances`.
    :returns: The snapshot mapping.
    :raises autodl_cli.errors.AutoDLError: For every authentication or API
        failure.
    """
    with AutoDLClient(token) as client:
        return instance_handler.get_instance(client, instance_uuid)


def get_current_user(token: str) -> dict[str, object]:
    """Return the user owning an API token.

    :param token: AutoDL API token, typically copied from a browser session.
    :returns: The user detail mapping.
    :raises autodl_cli.errors.AutoDLError: For every authentication or API
        failure.
    """
    with AutoDLClient(token) as client:
        return auth_handler.get_current_user(client)
