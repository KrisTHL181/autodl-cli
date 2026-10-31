"""Phone/password authentication against the AutoDL web-console API.

The login flow is two POSTs: ``/api/v1/new_login`` exchanges a phone number and
SHA-1 password hash for a short-lived ticket, then ``/api/v1/passport`` buys a
JWT with that ticket. Handlers never print and never read environment
variables; persistence is the caller's job.
"""

from __future__ import annotations

import hashlib
import platform
import uuid
from typing import TYPE_CHECKING

from autodl_cli import __version__
from autodl_cli.errors import APIError, AuthError
from autodl_cli.handlers import account as account_handler
from autodl_cli.handlers._common import require_success

if TYPE_CHECKING:
    from autodl_cli.client import AutoDLClient

#: Phone area prefix sent when the caller does not supply one.
_DEFAULT_PHONE_AREA = "+86"


def generate_device_fingerprint() -> str:
    """Generate a device fingerprint with the same shape as FingerprintJS v5.

    The AutoDL website uses FingerprintJS 5.2.0, whose visitor ID is a
    128-bit MurmurHash3 value rendered as exactly 32 lowercase hexadecimal
    characters. The browser does not persist that value and the server cannot
    recompute it, so a random UUID4 hex string is indistinguishable to the API
    and is persisted by the CLI across logins.

    :returns: A random 32-character lowercase hexadecimal string.
    """
    return uuid.uuid4().hex


def hash_password(password: str) -> str:
    """Hash a plaintext password the way the website does.

    :param password: Plaintext password.
    :returns: Lowercase SHA-1 hex digest of the UTF-8 encoded password.
    """
    return hashlib.sha1(password.encode("utf-8")).hexdigest()


def describe_device() -> dict[str, object]:
    """Describe this client for the passport exchange.

    :returns: A device mapping containing the OS name and the CLI's own
        browser-like identity.
    """
    return {
        "os": {"name": platform.system() or "Unknown"},
        "browser": {
            "name": "autodl-cli",
            "version": __version__,
            "major": __version__.partition(".")[0],
        },
    }


def login(
    client: AutoDLClient,
    phone: str,
    password: str,
    *,
    phone_area: str = _DEFAULT_PHONE_AREA,
    device_fingerprint: str | None = None,
) -> dict[str, object]:
    """Log in with a phone number and password.

    The ticket returned by ``new_login`` is short-lived, so the exchange with
    ``/api/v1/passport`` happens immediately inside this function. Do not add
    retries, prompts, or other requests between the two calls.

    :param client: Client used for the two unauthenticated POSTs. It is not
        mutated.
    :param phone: Phone number in the selected area.
    :param password: Plaintext password; hashed before transmission.
    :param phone_area: Phone area prefix, ``"+86"`` by default.
    :param device_fingerprint: Reusable 32-character fingerprint; generated
        when ``None``.
    :returns: Mapping with ``token``, ``user``, and ``device_fingerprint``.
    :raises autodl_cli.errors.AuthError: When either step reports a non-success
        ``code``.
    :raises autodl_cli.errors.APIError: When a successful response lacks a
        usable ticket, token, or ``data`` object.
    """
    fingerprint = device_fingerprint if device_fingerprint is not None else generate_device_fingerprint()

    login_payload: dict[str, object] = {
        "phone": phone,
        "password": hash_password(password),
        "v_code": "",
        "phone_area": phone_area,
        "captcha_verify_param": None,
        "device_fingerprint": fingerprint,
    }
    login_response = client.request("POST", "/api/v1/new_login", json=login_payload)
    login_data = require_success(login_response, action="login", error_type=AuthError)

    ticket = login_data.get("ticket")
    if not isinstance(ticket, str) or not ticket:
        raise APIError("AutoDL login did not return a ticket")

    # The ticket is short-lived: exchange it immediately, with no retries or
    # waits in between.
    passport_response = client.request(
        "POST",
        "/api/v1/passport",
        json={"ticket": ticket, "device": describe_device()},
    )
    passport_data = require_success(passport_response, action="passport exchange", error_type=AuthError)

    token = passport_data.get("token")
    if not isinstance(token, str) or not token:
        raise APIError("AutoDL login did not return a token")

    return {
        "token": token,
        "user": login_data.get("user"),
        "device_fingerprint": fingerprint,
    }


def get_current_user(client: AutoDLClient) -> dict[str, object]:
    """Return the user owning the client's token.

    This is the token-verification view of :func:`autodl_cli.handlers.account.get_me`.

    :param client: Client authenticated with the token to inspect.
    :returns: The user detail mapping.
    :raises autodl_cli.errors.AuthError: When the API rejects the token.
    :raises autodl_cli.errors.APIError: When a successful response has no
        object-valued ``data`` field.
    """
    return account_handler.get_me(client)
