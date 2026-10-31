"""Instance-domain API handlers.

The plain-instance list lives behind ``POST /api/v1/instance``. That endpoint
takes its pagination and filters in a JSON body and returns them under ``data``
next to the ``list`` array. AutoDL clamps an out-of-range ``page_index`` back to
the first page instead of returning an empty page, so the walk in
:func:`list_instances` is bounded by the ``max_page`` reported by the server.

One instance's configuration snapshot lives behind
``GET /api/v1/instance/snapshot``, keyed by the instance UUID. It describes the
base image, GPU allocation, and host machine, but not the live status.

Saving an instance as a custom image posts to
``POST /api/v1/instance/image/save``. A successful save answers with
``"data": null``, so :func:`save_image` validates only the envelope and returns
a small record of what it requested.

Powering an instance on posts to ``POST /api/v1/instance/power_on`` with the
same ``{"instance_uuid": ...}`` body. It answers with ``"data": null`` too, so
:func:`power_on` validates the envelope only and returns the matching record.

Powering an instance off posts to ``POST /api/v1/instance/power_off`` with the
instance UUID in the body. It answers with ``"data": null`` as well, so
:func:`power_off` follows the same envelope-only validation and record shape.
Powering an instance off keeps its data; AutoDL releases it after the retention
window shown by ``instance list`` unless it is powered on again.

Releasing an instance posts to ``POST /api/v1/instance/release`` with the same
``{"instance_uuid": ...}`` body and answers with ``"data": null``. Release is
irreversible: the instance and its data disk are deleted. It does not go through
the power-off endpoint first.

TODO: implement the remaining lifecycle handlers and return the structures
defined in :mod:`autodl_cli.models` instead of raw response dictionaries.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from autodl_cli.errors import APIError
from autodl_cli.handlers._common import require_success, require_success_any

if TYPE_CHECKING:
    from collections.abc import Iterable

    from autodl_cli.client import AutoDLClient

#: Path of the plain-instance list endpoint.
INSTANCE_LIST_PATH = "/api/v1/instance"

#: Path of the per-instance configuration snapshot endpoint.
INSTANCE_DETAIL_PATH = "/api/v1/instance/snapshot"

#: Path of the save-as-custom-image endpoint.
INSTANCE_IMAGE_SAVE_PATH = "/api/v1/instance/image/save"

#: Path of the power-on endpoint.
INSTANCE_POWER_ON_PATH = "/api/v1/instance/power_on"

#: Path of the power-off endpoint.
INSTANCE_POWER_OFF_PATH = "/api/v1/instance/power_off"

#: Path of the release endpoint.
INSTANCE_RELEASE_PATH = "/api/v1/instance/release"

#: Number of instances requested per API call when the caller does not choose.
DEFAULT_PAGE_SIZE = 100

#: Instance fields searched by the client-side ``query`` filter.
_QUERY_FIELDS = (
    "uuid",
    "name",
    "region_name",
    "region_sign",
    "machine_alias",
    "user_define_gpu_name",
    "snapshot_gpu_alias_name",
)


def _fetch_page(
    client: AutoDLClient,
    *,
    page_index: int,
    page_size: int,
    statuses: tuple[str, ...],
    charge_types: tuple[str, ...],
    sub_name: str,
    unbind_sub_user: bool,
) -> tuple[list[dict[str, object]], int]:
    """Fetch one page of the instance list.

    :param client: Authenticated API client.
    :param page_index: One-based page number to request.
    :param page_size: Instances to request for this page.
    :param statuses: Status filter values; empty means no status filter.
    :param charge_types: Billing-mode filter values; empty means no filter.
    :param sub_name: Sub-user name filter.
    :param unbind_sub_user: Whether to keep only instances with no bound
        sub-user.
    :returns: The page's instance mappings and the total number of pages.
    :raises autodl_cli.errors.AuthError: When the token is rejected.
    :raises autodl_cli.errors.APIError: When the API reports a failure or
        returns malformed data.
    """
    body: dict[str, object] = {
        "page_index": page_index,
        "page_size": page_size,
        "status": list(statuses),
        "charge_type": list(charge_types),
        "sub_name": sub_name,
        "unbind_sub_user": unbind_sub_user,
    }
    payload = client.request("POST", INSTANCE_LIST_PATH, json=body)
    data = require_success(payload, action="instance list")

    entries = data.get("list")
    if not isinstance(entries, list):
        raise APIError("AutoDL instance list returned malformed data")

    instances: list[dict[str, object]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise APIError("AutoDL instance list returned a non-object entry")
        instances.append(entry)

    # A missing or non-integer max_page means the server did not say how many
    # pages exist; stop after this one rather than risk looping forever.
    max_page = data.get("max_page")
    if not isinstance(max_page, int) or isinstance(max_page, bool):
        max_page = page_index

    return instances, max_page


def _matches_query(instance: dict[str, object], needle: str) -> bool:
    """Check whether any searchable string field contains ``needle``.

    :param instance: One instance mapping from the list endpoint.
    :param needle: Stripped and case-folded search text.
    :returns: Whether a non-empty searchable field contains the text.
    """
    for field in _QUERY_FIELDS:
        value = instance.get(field)
        if isinstance(value, str) and needle in value.casefold():
            return True
    return False


def list_instances(
    client: AutoDLClient,
    *,
    page_size: int = DEFAULT_PAGE_SIZE,
    statuses: Iterable[str] = (),
    charge_types: Iterable[str] = (),
    sub_name: str = "",
    unbind_sub_user: bool = False,
    query: str = "",
) -> list[dict[str, object]]:
    """Return every instance visible to the authenticated account.

    Every page is fetched, so the result is not limited by AutoDL's per-request
    page size. AutoDL clamps an out-of-range ``page_index`` back to the first
    page, which is why the loop stops on ``max_page`` instead of on an empty
    page.

    ``query`` is applied locally after every page has been fetched: the API has
    no keyword field. It matches case-insensitively against the instance UUID,
    name, region, machine alias, and GPU name fields.

    :param client: Authenticated API client.
    :param page_size: Instances requested per API call; must be positive.
    :param statuses: Only return instances whose status is one of these values.
    :param charge_types: Only return instances with one of these billing modes.
    :param sub_name: Only return instances whose bound sub-user name matches.
    :param unbind_sub_user: Only return instances with no bound sub-user.
    :param query: Only return instances whose UUID, name, region, machine alias,
        or GPU name contains this text; empty means no filtering.
    :returns: One mapping per instance, in the order AutoDL returns them.
    :raises ValueError: When ``page_size`` is not positive.
    :raises autodl_cli.errors.AuthError: When the token is rejected.
    :raises autodl_cli.errors.APIError: When the API reports a failure or
        returns malformed data.
    """
    if page_size < 1:
        raise ValueError("page_size must be at least 1")

    # Materialise once: a caller-supplied iterator would otherwise be exhausted
    # when the second page is requested.
    status_filter = tuple(statuses)
    charge_filter = tuple(charge_types)

    instances: list[dict[str, object]] = []
    page_index = 1
    while True:
        entries, max_page = _fetch_page(
            client,
            page_index=page_index,
            page_size=page_size,
            statuses=status_filter,
            charge_types=charge_filter,
            sub_name=sub_name,
            unbind_sub_user=unbind_sub_user,
        )
        instances.extend(entries)
        if not entries or page_index >= max_page:
            break
        page_index += 1

    needle = query.strip().casefold()
    if needle:
        instances = [instance for instance in instances if _matches_query(instance, needle)]
    return instances


def get_instance(client: AutoDLClient, instance_id: str) -> dict[str, object]:
    """Return one instance's configuration snapshot.

    The snapshot names the instance's base image, GPU allocation, and host
    machine, and repeats the machine's stock prices. It carries no live status
    or connection details, so pair it with :func:`list_instances` when those are
    needed.

    :param client: Authenticated API client.
    :param instance_id: Instance UUID from :func:`list_instances`.
    :returns: The snapshot mapping.
    :raises autodl_cli.errors.AuthError: When the token is rejected.
    :raises autodl_cli.errors.APIError: When the API reports a failure or
        returns malformed data.
    """
    payload = client.request(
        "GET",
        INSTANCE_DETAIL_PATH,
        params={"instance_uuid": instance_id},
    )
    return require_success(payload, action="instance detail")


def get_instance_status(client: AutoDLClient, instance_id: str) -> dict[str, object]:
    """Return one instance's current status.

    :param client: Authenticated API client.
    :param instance_id: Instance identifier.
    :returns: The status mapping.
    """
    ...


def create_instance(client: AutoDLClient, options: dict[str, object]) -> dict[str, object]:
    """Create an instance.

    :param client: Authenticated API client.
    :param options: Order parameters (image, GPU type, region, …).
    :returns: The created instance mapping.
    """
    ...


def power_on(client: AutoDLClient, instance_id: str) -> dict[str, object]:
    """Power an instance on.

    ``POST /api/v1/instance/power_on`` answers with ``"data": null`` on
    success, so success is signalled by the envelope's ``code`` alone. The
    request is accepted immediately; the instance may take a moment to start.

    :param client: Authenticated API client.
    :param instance_id: Instance UUID from :func:`list_instances`.
    :returns: A mapping with ``instance_uuid`` and ``powered_on``.
    :raises ValueError: When ``instance_id`` is blank.
    :raises autodl_cli.errors.AuthError: When the token is rejected.
    :raises autodl_cli.errors.APIError: When the API reports a failure.
    """
    instance_uuid = instance_id.strip()
    if not instance_uuid:
        raise ValueError("instance_id must not be empty")

    body: dict[str, object] = {"instance_uuid": instance_uuid}
    payload = client.request("POST", INSTANCE_POWER_ON_PATH, json=body)
    require_success_any(payload, action="power on instance")

    return {
        "instance_uuid": instance_uuid,
        "powered_on": True,
    }


def power_off(client: AutoDLClient, instance_id: str) -> dict[str, object]:
    """Power an instance off.

    ``POST /api/v1/instance/power_off`` answers with ``"data": null`` on
    success, so success is signalled by the envelope's ``code`` alone. The data
    disk is preserved; AutoDL releases a powered-off instance after the
    retention window unless it is powered on again.

    :param client: Authenticated API client.
    :param instance_id: Instance UUID from :func:`list_instances`.
    :returns: A mapping with ``instance_uuid`` and ``powered_off``.
    :raises ValueError: When ``instance_id`` is blank.
    :raises autodl_cli.errors.AuthError: When the token is rejected.
    :raises autodl_cli.errors.APIError: When the API reports a failure.
    """
    instance_uuid = instance_id.strip()
    if not instance_uuid:
        raise ValueError("instance_id must not be empty")

    body: dict[str, object] = {"instance_uuid": instance_uuid}
    payload = client.request("POST", INSTANCE_POWER_OFF_PATH, json=body)
    require_success_any(payload, action="power off instance")

    return {
        "instance_uuid": instance_uuid,
        "powered_off": True,
    }


def release_instance(client: AutoDLClient, instance_id: str) -> dict[str, object]:
    """Release an instance, deleting it and its data disk.

    ``POST /api/v1/instance/release`` answers with ``"data": null`` on success,
    so success is signalled by the envelope's ``code`` alone. Release is
    irreversible: AutoDL deletes the instance and its data disk. The instance
    does not need to be powered off first.

    :param client: Authenticated API client.
    :param instance_id: Instance UUID from :func:`list_instances`.
    :returns: A mapping with ``instance_uuid`` and ``released``.
    :raises ValueError: When ``instance_id`` is blank.
    :raises autodl_cli.errors.AuthError: When the token is rejected.
    :raises autodl_cli.errors.APIError: When the API reports a failure.
    """
    instance_uuid = instance_id.strip()
    if not instance_uuid:
        raise ValueError("instance_id must not be empty")

    body: dict[str, object] = {"instance_uuid": instance_uuid}
    payload = client.request("POST", INSTANCE_RELEASE_PATH, json=body)
    require_success_any(payload, action="release instance")

    return {
        "instance_uuid": instance_uuid,
        "released": True,
    }


def save_image(
    client: AutoDLClient,
    instance_id: str,
    image_name: str,
    *,
    try_again: bool = False,
) -> dict[str, object]:
    """Save an instance as a custom image.

    ``POST /api/v1/instance/image/save`` answers with ``"data": null`` on
    success, so success is signalled by the envelope's ``code`` alone. The
    request is accepted immediately; the image itself may take longer to
    appear in the account.

    :param client: Authenticated API client.
    :param instance_id: Instance UUID from :func:`list_instances`.
    :param image_name: Name for the new image.
    :param try_again: Whether AutoDL should retry a previously failed save.
    :returns: A mapping with ``instance_uuid``, ``image_name``, ``try_again``,
        and ``saved``.
    :raises ValueError: When ``instance_id`` or ``image_name`` is blank.
    :raises autodl_cli.errors.AuthError: When the token is rejected.
    :raises autodl_cli.errors.APIError: When the API reports a failure.
    """
    instance_uuid = instance_id.strip()
    name = image_name.strip()
    if not instance_uuid:
        raise ValueError("instance_id must not be empty")
    if not name:
        raise ValueError("image_name must not be empty")

    body: dict[str, object] = {
        "image_name": name,
        "instance_uuid": instance_uuid,
        "try_again": try_again,
    }
    payload = client.request("POST", INSTANCE_IMAGE_SAVE_PATH, json=body)
    require_success_any(payload, action="save image")

    return {
        "instance_uuid": instance_uuid,
        "image_name": name,
        "try_again": try_again,
        "saved": True,
    }
