"""Public library entry point.

Code that consumes autodl-cli as a library should import from here rather
than from :mod:`autodl_cli.handlers` directly. This module re-exports the
handler surface for password login, browser-token lookup, account balance,
instance listing/details, instance lifecycle actions, and the base-image
catalogue, and normalises internal exceptions into the
:class:`~autodl_cli.errors.AutoDLError` hierarchy.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from autodl_cli.client import AutoDLClient
from autodl_cli.handlers import account as account_handler
from autodl_cli.handlers import auth as auth_handler
from autodl_cli.handlers import image as image_handler
from autodl_cli.handlers import instance as instance_handler

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = [
    "AutoDLClient",
    "delete_private_image",
    "get_balance",
    "get_current_user",
    "get_instance",
    "list_images",
    "list_instances",
    "list_private_images",
    "login",
    "power_off",
    "power_on",
    "release_instance",
    "save_image",
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


def list_images(
    token: str,
    *,
    frameworks: Iterable[str] = (),
    framework_versions: Iterable[str] = (),
    python_versions: Iterable[str] = (),
    cuda_versions: Iterable[str] = (),
    chip_corps: Iterable[str] = (),
    cpu_archs: Iterable[str] = (),
) -> list[dict[str, object]]:
    """Return the base images available for new instances.

    The API returns a four-level option tree; this function flattens it into
    one record per selectable image. Filters are case-insensitive substrings,
    ORed within one argument and ANDed across arguments.

    :param token: AutoDL API token, typically copied from a browser session.
    :param frameworks: Framework names or fragments to include.
    :param framework_versions: Framework versions or fragments to include.
    :param python_versions: Python/OS labels or fragments to include.
    :param cuda_versions: CUDA versions or fragments to include.
    :param chip_corps: Chip vendors to include, for example ``nvidia``.
    :param cpu_archs: CPU architectures to include, for example ``x86``.
    :returns: One mapping per image with ``framework_name``,
        ``framework_version``, ``python_version``, ``cuda_version``,
        ``image_uuid``, ``chip_corp``, ``cpu_arch``, and ``is_desktop``.
    :raises autodl_cli.errors.AutoDLError: For every authentication or API
        failure.
    """
    with AutoDLClient(token) as client:
        return image_handler.list_images(
            client,
            frameworks=frameworks,
            framework_versions=framework_versions,
            python_versions=python_versions,
            cuda_versions=cuda_versions,
            chip_corps=chip_corps,
            cpu_archs=cpu_archs,
        )


def list_private_images(
    token: str,
    *,
    page_size: int = image_handler.DEFAULT_PRIVATE_PAGE_SIZE,
) -> list[dict[str, object]]:
    """Return the images saved from this account's instances.

    Every page is fetched, so the result is not limited by AutoDL's per-request
    page size. The API's entries are returned unchanged.

    :param token: AutoDL API token, typically copied from a browser session.
    :param page_size: Images requested per API call; must be positive.
    :returns: One mapping per private image.
    :raises autodl_cli.errors.AutoDLError: For every authentication or API
        failure.
    """
    with AutoDLClient(token) as client:
        return image_handler.list_private_images(client, page_size=page_size)


def delete_private_image(token: str, image_id: int) -> dict[str, object]:
    """Delete one of the account's private images.

    ``image_id`` is the numeric ``id`` field from :func:`list_private_images`,
    not the ``image-uuid`` string. Deletion is irreversible.

    :param token: AutoDL API token, typically copied from a browser session.
    :param image_id: Numeric private-image ID; must be positive.
    :returns: A mapping with ``image_id`` and ``deleted``.
    :raises autodl_cli.errors.AutoDLError: For every authentication or API
        failure.
    """
    with AutoDLClient(token) as client:
        return image_handler.delete_private_image(client, image_id)


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


def power_on(token: str, instance_uuid: str) -> dict[str, object]:
    """Power an instance on.

    AutoDL accepts the request immediately and answers with a null ``data``
    payload; the instance may take a moment to start.

    :param token: AutoDL API token, typically copied from a browser session.
    :param instance_uuid: Instance UUID as returned by :func:`list_instances`.
    :returns: A mapping with ``instance_uuid`` and ``powered_on``.
    :raises autodl_cli.errors.AutoDLError: For every authentication or API
        failure.
    """
    with AutoDLClient(token) as client:
        return instance_handler.power_on(client, instance_uuid)


def power_off(token: str, instance_uuid: str) -> dict[str, object]:
    """Power an instance off.

    The data disk is preserved; AutoDL releases a powered-off instance after
    the retention window unless it is powered on again.

    :param token: AutoDL API token, typically copied from a browser session.
    :param instance_uuid: Instance UUID as returned by :func:`list_instances`.
    :returns: A mapping with ``instance_uuid`` and ``powered_off``.
    :raises autodl_cli.errors.AutoDLError: For every authentication or API
        failure.
    """
    with AutoDLClient(token) as client:
        return instance_handler.power_off(client, instance_uuid)


def release_instance(token: str, instance_uuid: str) -> dict[str, object]:
    """Release an instance, deleting it and its data disk.

    Release is irreversible. AutoDL accepts the request immediately and answers
    with a null ``data`` payload; the instance does not need to be powered off
    first.

    :param token: AutoDL API token, typically copied from a browser session.
    :param instance_uuid: Instance UUID as returned by :func:`list_instances`.
    :returns: A mapping with ``instance_uuid`` and ``released``.
    :raises autodl_cli.errors.AutoDLError: For every authentication or API
        failure.
    """
    with AutoDLClient(token) as client:
        return instance_handler.release_instance(client, instance_uuid)


def save_image(
    token: str,
    instance_uuid: str,
    image_name: str,
    *,
    try_again: bool = False,
) -> dict[str, object]:
    """Save an instance as a custom image.

    AutoDL accepts the request and answers with a null ``data`` payload; the
    image may take longer to appear under the account's private images.

    :param token: AutoDL API token, typically copied from a browser session.
    :param instance_uuid: Instance UUID as returned by :func:`list_instances`.
    :param image_name: Name for the new image.
    :param try_again: Whether AutoDL should retry a previously failed save.
    :returns: A mapping with ``instance_uuid``, ``image_name``, ``try_again``,
        and ``saved``.
    :raises autodl_cli.errors.AutoDLError: For every authentication or API
        failure.
    """
    with AutoDLClient(token) as client:
        return instance_handler.save_image(
            client,
            instance_uuid,
            image_name,
            try_again=try_again,
        )


def get_current_user(token: str) -> dict[str, object]:
    """Return the user owning an API token.

    :param token: AutoDL API token, typically copied from a browser session.
    :returns: The user detail mapping.
    :raises autodl_cli.errors.AutoDLError: For every authentication or API
        failure.
    """
    with AutoDLClient(token) as client:
        return auth_handler.get_current_user(client)
