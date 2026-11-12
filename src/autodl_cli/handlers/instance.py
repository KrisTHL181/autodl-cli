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
same ``{"instance_uuid": ...}`` body. Passing ``non_gpu=True`` adds
``"payload": "non_gpu"``, the console's CPU-only (no-GPU) start mode. It answers
with ``"data": null`` too, so :func:`power_on` validates the envelope only and
returns the matching record.

Powering an instance off posts to ``POST /api/v1/instance/power_off`` with the
instance UUID in the body. It answers with ``"data": null`` as well, so
:func:`power_off` follows the same envelope-only validation and record shape.
Powering an instance off keeps its data; AutoDL releases it after the retention
window shown by ``instance list`` unless it is powered on again.

Releasing an instance posts to ``POST /api/v1/instance/release`` with the same
``{"instance_uuid": ...}`` body and answers with ``"data": null``. Release is
irreversible: the instance and its data disk are deleted. It does not go through
the power-off endpoint first.

Resetting an instance posts to ``POST /api/v1/instance/init`` with the same
``{"instance_uuid": ...}`` body and answers with ``"data": null``. It rebuilds
the system disk from the instance's image while keeping the data disk.

Changing an instance's image posts to ``POST /api/v1/instance/change_image``
with the instance UUID and the new base-image UUID, and answers with
``"data": null``. It rebuilds the system disk from that image while keeping the
data disk.

Renaming an instance sends a ``PUT /api/v1/instance/name`` with the instance
UUID and the new name. It also answers with ``"data": null``, and the new name
is immediately visible in ``instance list``.

Creating a pay-as-you-go instance posts the web console's order body to
``POST /api/v1/order/instance/create/payg``. Its ``data`` field is the new
instance UUID string rather than an object, so :func:`create_instance` unwraps
it with :func:`require_success_any` and returns a flat order record.
:func:`select_machine` resolves a region and GPU model to the first orderable
machine with enough idle cards.

Cloning an instance posts the web console's order body to
``POST /api/v1/order/instance/clone/payg``. The image and GPU count are
inherited from the source instance: :func:`resolve_clone_source` reads the
snapshot for the image and the instance list for ``req_gpu_amount``.
:func:`resolve_clone_image` resolves the image alone, for callers such as
``tools snipe --clone`` that choose their own GPU count. Like create, the
response's ``data`` is the new instance UUID string.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from autodl_cli.errors import APIError
from autodl_cli.handlers import gpu as gpu_handler
from autodl_cli.handlers._common import require_success, require_success_any
from autodl_cli.money import PRICE_FIELDS, to_yuan

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

#: Power-on payload that starts the instance in CPU-only (no-GPU) mode.
POWER_ON_NON_GPU_PAYLOAD = "non_gpu"

#: Path of the power-off endpoint.
INSTANCE_POWER_OFF_PATH = "/api/v1/instance/power_off"

#: Path of the scheduled auto-shutdown endpoint (also used to cancel/modify).
INSTANCE_TIMED_SHUTDOWN_PATH = "/api/v1/instance/timed/shutdown"

#: Fixed UTC+8 offset used for scheduled-shutdown times (China has no DST).
SHUTDOWN_TIMEZONE = timezone(timedelta(hours=8))

#: Path of the release endpoint.
INSTANCE_RELEASE_PATH = "/api/v1/instance/release"

#: Path of the reset endpoint.
INSTANCE_RESET_PATH = "/api/v1/instance/init"

#: Path of the change-image endpoint.
INSTANCE_CHANGE_IMAGE_PATH = "/api/v1/instance/change_image"

#: Path of the rename endpoint.
INSTANCE_RENAME_PATH = "/api/v1/instance/name"

#: Path of the pay-as-you-go instance-create endpoint.
INSTANCE_CREATE_PATH = "/api/v1/order/instance/create/payg"

#: Path of the pay-as-you-go instance-clone endpoint.
INSTANCE_CLONE_PATH = "/api/v1/order/instance/clone/payg"

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


def _with_yuan_prices(entry: dict[str, object]) -> dict[str, object]:
    """Return a shallow copy with integer price fields converted to yuan.

    AutoDL reports prices in a smaller integer unit. Fields from
    :data:`autodl_cli.money.PRICE_FIELDS` are exposed in yuan instead; absent
    fields and non-integer values are left untouched.

    :param entry: One raw instance or snapshot mapping from the API.
    :returns: A shallow copy with yuan price fields.
    """
    converted = dict(entry)
    for field in PRICE_FIELDS:
        if field not in converted:
            continue
        yuan = to_yuan(converted[field])
        if yuan is not None:
            converted[field] = yuan
    return converted


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
        Price fields are yuan floats.
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
    return [_with_yuan_prices(instance) for instance in instances]


def get_instance(client: AutoDLClient, instance_id: str) -> dict[str, object]:
    """Return one instance's configuration snapshot.

    The snapshot names the instance's base image, GPU allocation, and host
    machine, and repeats the machine's stock prices in yuan. It carries no live
    status or connection details, so pair it with :func:`list_instances` when
    those are needed.

    :param client: Authenticated API client.
    :param instance_id: Instance UUID from :func:`list_instances`.
    :returns: The snapshot mapping, with price fields as yuan floats.
    :raises autodl_cli.errors.AuthError: When the token is rejected.
    :raises autodl_cli.errors.APIError: When the API reports a failure or
        returns malformed data.
    """
    payload = client.request(
        "GET",
        INSTANCE_DETAIL_PATH,
        params={"instance_uuid": instance_id},
    )
    return _with_yuan_prices(require_success(payload, action="instance detail"))


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


def resolve_clone_image(client: AutoDLClient, instance_uuid: str) -> dict[str, object]:
    """Resolve the image to carry over when cloning an instance.

    The source instance's snapshot names its image. An image is treated as
    private when the snapshot says so, or when its type is unknown but its UUID
    uses the ``image-`` private-image prefix. Every other image is treated as a
    base image.

    This resolves only the image; :func:`resolve_clone_source` additionally
    looks up the GPU count in the instance list.

    :param client: Authenticated API client.
    :param instance_uuid: Source instance UUID from :func:`list_instances`.
    :returns: A mapping with ``instance_uuid``, ``base_image_uuid``, and
        ``private_image_uuid``.
    :raises ValueError: When ``instance_uuid`` is blank.
    :raises autodl_cli.errors.AuthError: When the token is rejected.
    :raises autodl_cli.errors.APIError: When the snapshot is malformed.
    """
    source_uuid = instance_uuid.strip()
    if not source_uuid:
        raise ValueError("instance_uuid must not be empty")

    snapshot = get_instance(client, source_uuid)
    image = snapshot.get("image")
    if not isinstance(image, dict):
        raise APIError("AutoDL instance snapshot returned malformed image data")
    image_uuid = image.get("base_image_uuid")
    if not isinstance(image_uuid, str) or not image_uuid.strip():
        raise APIError("AutoDL instance snapshot returned malformed image data")
    image_uuid = image_uuid.strip()

    image_type = image.get("image_type")
    is_private = image_type == "private" or (image_type != "public" and image_uuid.startswith("image-"))
    base_image = "" if is_private else image_uuid
    private_image = image_uuid if is_private else ""

    return {
        "instance_uuid": source_uuid,
        "base_image_uuid": base_image,
        "private_image_uuid": private_image,
    }


def resolve_clone_source(client: AutoDLClient, instance_uuid: str) -> dict[str, object]:
    """Resolve the image and GPU count to carry over when cloning.

    The snapshot names the source instance's image, but not how many GPUs it
    uses. That count lives in the instance list, so the source is looked up
    there by exact UUID. The list endpoint's ``query`` is a substring match, so
    a result is accepted only when its ``uuid`` equals ``instance_uuid``. The
    image itself is resolved by :func:`resolve_clone_image`.

    :param client: Authenticated API client.
    :param instance_uuid: Source instance UUID from :func:`list_instances`.
    :returns: A mapping with ``instance_uuid``, ``base_image_uuid``,
        ``private_image_uuid``, and ``gpu_amount``.
    :raises ValueError: When ``instance_uuid`` is blank.
    :raises autodl_cli.errors.AuthError: When the token is rejected.
    :raises autodl_cli.errors.APIError: When the snapshot or instance list is
        malformed, the GPU amount cannot be determined, or the source is not in
        the instance list.
    """
    resolved = resolve_clone_image(client, instance_uuid)
    source_uuid = str(resolved["instance_uuid"])

    for instance in list_instances(client, query=source_uuid):
        if instance.get("uuid") != source_uuid:
            continue
        gpu_amount = instance.get("req_gpu_amount")
        if isinstance(gpu_amount, bool) or not isinstance(gpu_amount, int) or gpu_amount < 1:
            raise APIError(f"AutoDL could not determine the GPU amount of instance {source_uuid!r}")
        return {
            "instance_uuid": source_uuid,
            "base_image_uuid": resolved["base_image_uuid"],
            "private_image_uuid": resolved["private_image_uuid"],
            "gpu_amount": gpu_amount,
        }

    raise APIError(f"AutoDL instance {source_uuid!r} was not found in the instance list")


def clone_instance(
    client: AutoDLClient,
    instance_uuid: str,
    *,
    machine_id: str,
    base_image_uuid: str = "",
    private_image_uuid: str = "",
    gpu_amount: int = 1,
    instance_name: str = "",
    expand_data_disk: int = 0,
    copy_data_disk: bool = True,
    keep_src_user_service_address: bool = False,
) -> dict[str, object]:
    """Clone an instance onto a machine as a new pay-as-you-go order.

    ``POST /api/v1/order/instance/clone/payg`` answers with the new instance
    UUID as a bare string under ``data``, not as an object. Success is therefore
    checked with :func:`require_success_any` and the string is validated before
    it is returned.

    Exactly one of ``base_image_uuid`` and ``private_image_uuid`` must be set.
    Call :func:`resolve_clone_source` first to derive both values, plus the
    source instance's GPU count, from the source instance. The request is
    accepted immediately; the clone may take a moment to appear in
    ``instance list``.

    :param client: Authenticated API client.
    :param instance_uuid: Source instance UUID from :func:`list_instances`.
    :param machine_id: Machine to clone onto, from ``gpu machines``.
    :param base_image_uuid: Base-image UUID inherited from the source instance.
    :param private_image_uuid: Private-image UUID inherited from the source
        instance.
    :param gpu_amount: Number of GPUs to request; must be at least 1.
    :param instance_name: Optional name for the clone; surrounding whitespace is
        stripped.
    :param expand_data_disk: Extra data-disk size in GB; must not be negative.
    :param copy_data_disk: Whether to copy the source's data disk.
    :param keep_src_user_service_address: Whether to keep the source's user
        service address.
    :returns: A mapping with ``instance_uuid`` (the new clone),
        ``source_instance_uuid``, ``machine_id``, ``gpu_amount``,
        ``charge_type``, ``base_image_uuid``, ``private_image_uuid``,
        ``instance_name``, ``expand_data_disk``, ``copy_data_disk``, and
        ``keep_src_user_service_address``.
    :raises ValueError: When ``instance_uuid`` or ``machine_id`` is blank,
        ``gpu_amount`` is below 1, ``expand_data_disk`` is negative, or not
        exactly one image UUID is set.
    :raises autodl_cli.errors.AuthError: When the token is rejected.
    :raises autodl_cli.errors.APIError: When the API reports a failure or
        returns malformed data.
    """
    source_uuid = instance_uuid.strip()
    if not source_uuid:
        raise ValueError("instance_uuid must not be empty")
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
        "instance_uuid": source_uuid,
        "instance_info": {
            "machine_id": machine,
            "charge_type": CREATE_CHARGE_TYPE,
            "req_gpu_amount": gpu_amount,
            "base_image_uuid": base_image,
            "instance_name": name,
            "private_image_uuid": private_image,
            "reproduction_uuid": "",
            "cg_application_uuid": "",
            "cg_application_info": {},
            "expand_data_disk": expand_data_disk,
            "copy_data_disk_after_clone": copy_data_disk,
            "keep_src_user_service_address_after_clone": keep_src_user_service_address,
            "reproduction_id": 0,
            "ft_sparse": True,
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
    payload = client.request("POST", INSTANCE_CLONE_PATH, json=body)
    data = require_success_any(payload, action="clone instance")
    if not isinstance(data, str) or not data.strip():
        raise APIError("AutoDL clone instance returned malformed data")
    new_uuid = data.strip()

    return {
        "instance_uuid": new_uuid,
        "source_instance_uuid": source_uuid,
        "machine_id": machine,
        "gpu_amount": gpu_amount,
        "charge_type": CREATE_CHARGE_TYPE,
        "base_image_uuid": base_image,
        "private_image_uuid": private_image,
        "instance_name": name,
        "expand_data_disk": expand_data_disk,
        "copy_data_disk": copy_data_disk,
        "keep_src_user_service_address": keep_src_user_service_address,
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


def power_on(client: AutoDLClient, instance_id: str, *, non_gpu: bool = False) -> dict[str, object]:
    """Power an instance on, optionally in CPU-only mode.

    ``POST /api/v1/instance/power_on`` answers with ``"data": null`` on
    success, so success is signalled by the envelope's ``code`` alone. The
    request is accepted immediately; the instance may take a moment to start.

    When ``non_gpu`` is true the body carries ``"payload": "non_gpu"``, which is
    the web console's no-GPU start mode: the instance boots without its cards.

    :param client: Authenticated API client.
    :param instance_id: Instance UUID from :func:`list_instances`.
    :param non_gpu: Start the instance in CPU-only (no-GPU) mode.
    :returns: A mapping with ``instance_uuid``, ``powered_on``, and ``non_gpu``.
    :raises ValueError: When ``instance_id`` is blank.
    :raises autodl_cli.errors.AuthError: When the token is rejected.
    :raises autodl_cli.errors.APIError: When the API reports a failure.
    """
    instance_uuid = instance_id.strip()
    if not instance_uuid:
        raise ValueError("instance_id must not be empty")

    body: dict[str, object] = {"instance_uuid": instance_uuid}
    if non_gpu:
        body["payload"] = POWER_ON_NON_GPU_PAYLOAD
    payload = client.request("POST", INSTANCE_POWER_ON_PATH, json=body)
    require_success_any(payload, action="power on instance")

    return {
        "instance_uuid": instance_uuid,
        "powered_on": True,
        "non_gpu": non_gpu,
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


def schedule_shutdown(client: AutoDLClient, instance_id: str, *, shutdown_at: datetime) -> dict[str, object]:
    """Schedule an instance to shut down automatically at a given time.

    ``POST /api/v1/instance/timed/shutdown`` accepts a non-null
    ``shutdown_at`` as a naive Beijing-time string in ``"%Y-%m-%d %H:%M"``
    format and answers with ``"data": null`` on success, so success is
    signalled by the envelope's ``code`` alone. Re-running the request with a
    new time modifies the existing schedule; no separate endpoint is needed.

    A naive ``shutdown_at`` is interpreted as Beijing time (UTC+8). An aware
    value is converted to UTC+8 before formatting.

    :param client: Authenticated API client.
    :param instance_id: Instance UUID from :func:`list_instances`.
    :param shutdown_at: Time at which the instance should shut down.
    :returns: A mapping with ``instance_uuid`` and ``shutdown_at`` (the
        Beijing-time wire string).
    :raises ValueError: When ``instance_id`` is blank.
    :raises autodl_cli.errors.AuthError: When the token is rejected.
    :raises autodl_cli.errors.APIError: When the API reports a failure.
    """
    instance_uuid = instance_id.strip()
    if not instance_uuid:
        raise ValueError("instance_id must not be empty")

    if shutdown_at.tzinfo is None:
        local_time = shutdown_at.replace(tzinfo=SHUTDOWN_TIMEZONE)
    else:
        local_time = shutdown_at.astimezone(SHUTDOWN_TIMEZONE)
    wire_time = local_time.strftime("%Y-%m-%d %H:%M")

    body: dict[str, object] = {
        "instance_uuid": instance_uuid,
        "shutdown_at": wire_time,
    }
    payload = client.request("POST", INSTANCE_TIMED_SHUTDOWN_PATH, json=body)
    require_success_any(payload, action="schedule instance shutdown")

    return {
        "instance_uuid": instance_uuid,
        "shutdown_at": wire_time,
    }


def cancel_scheduled_shutdown(client: AutoDLClient, instance_id: str) -> dict[str, object]:
    """Cancel an instance's scheduled automatic shutdown.

    ``POST /api/v1/instance/timed/shutdown`` cancels the schedule when
    ``shutdown_at`` is JSON null and answers with ``"data": null`` on success,
    so success is signalled by the envelope's ``code`` alone.

    :param client: Authenticated API client.
    :param instance_id: Instance UUID from :func:`list_instances`.
    :returns: A mapping with ``instance_uuid`` and ``shutdown_scheduled``
        (always ``False``).
    :raises ValueError: When ``instance_id`` is blank.
    :raises autodl_cli.errors.AuthError: When the token is rejected.
    :raises autodl_cli.errors.APIError: When the API reports a failure.
    """
    instance_uuid = instance_id.strip()
    if not instance_uuid:
        raise ValueError("instance_id must not be empty")

    body: dict[str, object] = {
        "instance_uuid": instance_uuid,
        "shutdown_at": None,
    }
    payload = client.request("POST", INSTANCE_TIMED_SHUTDOWN_PATH, json=body)
    require_success_any(payload, action="cancel scheduled instance shutdown")

    return {
        "instance_uuid": instance_uuid,
        "shutdown_scheduled": False,
    }


def reset_instance(client: AutoDLClient, instance_id: str) -> dict[str, object]:
    """Reset an instance, rebuilding its system disk.

    ``POST /api/v1/instance/init`` answers with ``"data": null`` on success, so
    success is signalled by the envelope's ``code`` alone. The system disk is
    restored from the instance's image; the data disk is preserved.

    :param client: Authenticated API client.
    :param instance_id: Instance UUID from :func:`list_instances`.
    :returns: A mapping with ``instance_uuid`` and ``reset``.
    :raises ValueError: When ``instance_id`` is blank.
    :raises autodl_cli.errors.AuthError: When the token is rejected.
    :raises autodl_cli.errors.APIError: When the API reports a failure.
    """
    instance_uuid = instance_id.strip()
    if not instance_uuid:
        raise ValueError("instance_id must not be empty")

    body: dict[str, object] = {"instance_uuid": instance_uuid}
    payload = client.request("POST", INSTANCE_RESET_PATH, json=body)
    require_success_any(payload, action="reset instance")

    return {
        "instance_uuid": instance_uuid,
        "reset": True,
    }


def change_image(client: AutoDLClient, instance_id: str, base_image_uuid: str) -> dict[str, object]:
    """Change an instance's image, rebuilding its system disk.

    ``POST /api/v1/instance/change_image`` answers with ``"data": null`` on
    success, so success is signalled by the envelope's ``code`` alone. The
    system disk is rebuilt from the chosen base image; the data disk is
    preserved.

    :param client: Authenticated API client.
    :param instance_id: Instance UUID from :func:`list_instances`.
    :param base_image_uuid: Base-image UUID from :func:`list_images`.
    :returns: A mapping with ``instance_uuid``, ``base_image_uuid``, and
        ``image_changed``.
    :raises ValueError: When ``instance_id`` or ``base_image_uuid`` is blank.
    :raises autodl_cli.errors.AuthError: When the token is rejected.
    :raises autodl_cli.errors.APIError: When the API reports a failure.
    """
    instance_uuid = instance_id.strip()
    image_uuid = base_image_uuid.strip()
    if not instance_uuid:
        raise ValueError("instance_id must not be empty")
    if not image_uuid:
        raise ValueError("base_image_uuid must not be empty")

    body: dict[str, object] = {
        "instance_uuid": instance_uuid,
        "base_image_uuid": image_uuid,
    }
    payload = client.request("POST", INSTANCE_CHANGE_IMAGE_PATH, json=body)
    require_success_any(payload, action="change instance image")

    return {
        "instance_uuid": instance_uuid,
        "base_image_uuid": image_uuid,
        "image_changed": True,
    }


def rename_instance(client: AutoDLClient, instance_id: str, instance_name: str) -> dict[str, object]:
    """Rename an instance.

    ``PUT /api/v1/instance/name`` answers with ``"data": null`` on success, so
    success is signalled by the envelope's ``code`` alone. The new name is
    immediately visible in ``instance list``.

    :param client: Authenticated API client.
    :param instance_id: Instance UUID from :func:`list_instances`.
    :param instance_name: New instance name; surrounding whitespace is stripped.
    :returns: A mapping with ``instance_uuid``, ``instance_name``, and
        ``renamed``.
    :raises ValueError: When ``instance_id`` or ``instance_name`` is blank.
    :raises autodl_cli.errors.AuthError: When the token is rejected.
    :raises autodl_cli.errors.APIError: When the API reports a failure.
    """
    instance_uuid = instance_id.strip()
    name = instance_name.strip()
    if not instance_uuid:
        raise ValueError("instance_id must not be empty")
    if not name:
        raise ValueError("instance_name must not be empty")

    body: dict[str, object] = {
        "instance_name": name,
        "instance_uuid": instance_uuid,
    }
    payload = client.request("PUT", INSTANCE_RENAME_PATH, json=body)
    require_success_any(payload, action="rename instance")

    return {
        "instance_uuid": instance_uuid,
        "instance_name": name,
        "renamed": True,
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
