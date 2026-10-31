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

Creating a pay-as-you-go instance posts the web console's order body to
``POST /api/v1/order/instance/create/payg``. Its ``data`` field is the new
instance UUID string rather than an object, so :func:`create_instance` unwraps
it with :func:`require_success_any` and returns a flat order record.
:func:`select_machine` resolves a region and GPU model to the first orderable
machine with enough idle cards.

TODO: implement :func:`get_instance_status` and return the structures defined
in :mod:`autodl_cli.models` instead of raw response dictionaries.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from autodl_cli.errors import APIError
from autodl_cli.handlers import gpu as gpu_handler
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

#: Path of the pay-as-you-go instance-create endpoint.
INSTANCE_CREATE_PATH = "/api/v1/order/instance/create/payg"

#: Billing mode used by the instance-create endpoint.
CREATE_CHARGE_TYPE = "payg"

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


def create_instance(
    client: AutoDLClient,
    *,
    machine_id: str,
    base_image_uuid: str = "",
    private_image_uuid: str = "",
    gpu_amount: int = 1,
    instance_name: str = "",
    expand_data_disk: int = 0,
) -> dict[str, object]:
    """Order a pay-as-you-go instance on one machine.

    ``POST /api/v1/order/instance/create/payg`` answers with the new instance
    UUID as a bare string under ``data``, not as an object. Success is therefore
    checked with :func:`require_success_any` and the string is validated before
    it is returned.

    Exactly one of ``base_image_uuid`` and ``private_image_uuid`` must be set.
    The request is accepted immediately; the instance may take a moment to
    appear in ``instance list``.

    :param client: Authenticated API client.
    :param machine_id: Machine to order on, from ``gpu machines``.
    :param base_image_uuid: Base-image UUID from ``image list``.
    :param private_image_uuid: Private-image UUID from ``image list-private``.
    :param gpu_amount: Number of GPUs to request; must be at least 1.
    :param instance_name: Optional instance name; surrounding whitespace is
        stripped.
    :param expand_data_disk: Extra data-disk size in GB; must not be negative.
    :returns: A mapping with ``instance_uuid``, ``machine_id``, ``gpu_amount``,
        ``charge_type``, ``base_image_uuid``, ``private_image_uuid``,
        ``instance_name``, and ``expand_data_disk``.
    :raises ValueError: When ``machine_id`` is blank, ``gpu_amount`` is below 1,
        ``expand_data_disk`` is negative, or not exactly one image UUID is set.
    :raises autodl_cli.errors.AuthError: When the token is rejected.
    :raises autodl_cli.errors.APIError: When the API reports a failure or
        returns malformed data.
    """
    machine = machine_id.strip()
    if not machine:
        raise ValueError("machine_id must not be empty")
    if isinstance(gpu_amount, bool) or gpu_amount < 1:
        raise ValueError("gpu_amount must be at least 1")
    if isinstance(expand_data_disk, bool) or expand_data_disk < 0:
        raise ValueError("expand_data_disk must not be negative")

    base_image = base_image_uuid.strip()
    private_image = private_image_uuid.strip()
    if bool(base_image) == bool(private_image):
        raise ValueError("exactly one of base_image_uuid and private_image_uuid must be set")
    name = instance_name.strip()

    body: dict[str, object] = {
        "instance_info": {
            "machine_id": machine,
            "charge_type": CREATE_CHARGE_TYPE,
            "req_gpu_amount": gpu_amount,
            "base_image_uuid": base_image,
            "private_image_uuid": private_image,
            "reproduction_uuid": "",
            "cg_application_uuid": "",
            "cg_application_info": {
                "image_name": "",
                "current_version_id": 0,
                "current_version": "",
                "image_id": 0,
            },
            "instance_name": name,
            "expand_data_disk": expand_data_disk,
            "reproduction_id": 0,
        },
        "price_info": {
            "coupon_id_list": [],
            "machine_id": machine,
            "charge_type": CREATE_CHARGE_TYPE,
            "duration": 1,
            "num": 1,
            "expand_data_disk": expand_data_disk,
        },
    }
    payload = client.request("POST", INSTANCE_CREATE_PATH, json=body)
    data = require_success_any(payload, action="create instance")
    if not isinstance(data, str) or not data.strip():
        raise APIError("AutoDL create instance returned malformed data")
    instance_uuid = data.strip()

    return {
        "instance_uuid": instance_uuid,
        "machine_id": machine,
        "gpu_amount": gpu_amount,
        "charge_type": CREATE_CHARGE_TYPE,
        "base_image_uuid": base_image,
        "private_image_uuid": private_image,
        "instance_name": name,
        "expand_data_disk": expand_data_disk,
    }


def select_machine(
    client: AutoDLClient,
    *,
    region: str,
    gpu: str,
    gpu_amount: int = 1,
) -> dict[str, object]:
    """Resolve a region and GPU model to an orderable machine.

    The region identifier is resolved through the region catalogue, then the
    machine listing for that data center is searched for the first machine
    whose GPU name matches ``gpu`` case-insensitively and that has at least
    ``gpu_amount`` idle cards. The description is advisory: the order can still
    fail if another user takes the capacity first.

    :param client: Authenticated API client.
    :param region: Region sign, data center, or region name.
    :param gpu: Exact GPU model name to require.
    :param gpu_amount: Number of idle GPUs the machine must have; must be at
        least 1.
    :returns: The normalised machine mapping from :func:`list_machines`.
    :raises ValueError: When ``region`` or ``gpu`` is blank, ``gpu_amount`` is
        below 1, or the region is unknown.
    :raises autodl_cli.errors.AuthError: When the token is rejected.
    :raises autodl_cli.errors.APIError: When the API reports a failure or no
        machine has enough idle capacity.
    """
    region_text = region.strip()
    if not region_text:
        raise ValueError("region must not be empty")
    gpu_text = gpu.strip()
    if not gpu_text:
        raise ValueError("gpu must not be empty")
    if isinstance(gpu_amount, bool) or gpu_amount < 1:
        raise ValueError("gpu_amount must be at least 1")

    regions = gpu_handler.select_regions(gpu_handler.list_regions(client), [region_text])
    page = gpu_handler.list_machines(
        client,
        charge_type=CREATE_CHARGE_TYPE,
        region_signs=gpu_handler.region_signs(regions[0]),
        gpu_types=(gpu_text,),
        gpu_idle_num=gpu_amount,
        all_pages=True,
    )

    machines = page.get("machines")
    if isinstance(machines, list):
        for machine in machines:
            if not isinstance(machine, dict):
                continue
            gpu_name = machine.get("gpu_name")
            idle = machine.get("gpu_idle_num")
            if (
                isinstance(gpu_name, str)
                and gpu_name.strip().casefold() == gpu_text.casefold()
                and isinstance(idle, int)
                and not isinstance(idle, bool)
                and idle >= gpu_amount
            ):
                return machine

    raise APIError(f"No machine with {gpu_amount} idle {gpu!r} GPU(s) in region {region!r}")


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
