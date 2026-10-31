"""Instance-domain API handlers.

The plain-instance list lives behind ``POST /api/v1/instance``. That endpoint
takes its pagination and filters in a JSON body and returns them under ``data``
next to the ``list`` array. AutoDL clamps an out-of-range ``page_index`` back to
the first page instead of returning an empty page, so the walk in
:func:`list_instances` is bounded by the ``max_page`` reported by the server.

TODO: implement the remaining lifecycle handlers and return the structures
defined in :mod:`autodl_cli.models` instead of raw response dictionaries.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from autodl_cli.errors import APIError
from autodl_cli.handlers._common import require_success

if TYPE_CHECKING:
    from collections.abc import Iterable

    from autodl_cli.client import AutoDLClient

#: Path of the plain-instance list endpoint.
INSTANCE_LIST_PATH = "/api/v1/instance"

#: Number of instances requested per API call when the caller does not choose.
DEFAULT_PAGE_SIZE = 100


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


def list_instances(
    client: AutoDLClient,
    *,
    page_size: int = DEFAULT_PAGE_SIZE,
    statuses: Iterable[str] = (),
    charge_types: Iterable[str] = (),
    sub_name: str = "",
    unbind_sub_user: bool = False,
) -> list[dict[str, object]]:
    """Return every instance visible to the authenticated account.

    Every page is fetched, so the result is not limited by AutoDL's per-request
    page size. AutoDL clamps an out-of-range ``page_index`` back to the first
    page, which is why the loop stops on ``max_page`` instead of on an empty
    page.

    :param client: Authenticated API client.
    :param page_size: Instances requested per API call; must be positive.
    :param statuses: Only return instances whose status is one of these values.
    :param charge_types: Only return instances with one of these billing modes.
    :param sub_name: Only return instances whose bound sub-user name matches.
    :param unbind_sub_user: Only return instances with no bound sub-user.
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

    return instances


def get_instance(client: AutoDLClient, instance_id: str) -> dict[str, object]:
    """Return one instance's details.

    :param client: Authenticated API client.
    :param instance_id: Instance identifier.
    :returns: The instance mapping.
    """
    ...


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

    :param client: Authenticated API client.
    :param instance_id: Instance identifier.
    :returns: The operation result.
    """
    ...


def power_off(client: AutoDLClient, instance_id: str) -> dict[str, object]:
    """Power an instance off.

    :param client: Authenticated API client.
    :param instance_id: Instance identifier.
    :returns: The operation result.
    """
    ...


def release_instance(client: AutoDLClient, instance_id: str) -> dict[str, object]:
    """Release an instance.

    :param client: Authenticated API client.
    :param instance_id: Instance identifier.
    :returns: The operation result.
    """
    ...


def save_image(client: AutoDLClient, instance_id: str, image_name: str) -> dict[str, object]:
    """Save an instance as a custom image.

    :param client: Authenticated API client.
    :param instance_id: Instance identifier.
    :param image_name: Name for the new image.
    :returns: The operation result.
    """
    ...
