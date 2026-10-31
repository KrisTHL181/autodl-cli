"""GPU-capacity API handlers.

The region catalogue comes from ``GET /api/v1/common`` and is shared by every
GPU query: the endpoint reports one record per region sign, while stock is
queried per data center. :func:`list_regions` groups those records so a caller
can resolve a sign, data center, or display name with
:func:`select_regions`.

Per-data-center stock lives behind ``POST /api/v1/machine/region/gpu_type``.
:func:`get_region_gpu` flattens its single-key-per-GPU response,
:func:`list_gpu_availability` keeps the region structure, and
:func:`find_gpu` searches a model across several regions.

The individual machines behind that stock live behind
``POST /api/v1/user/machine/list``. :func:`list_machines` sends the web
console's filter body, normalises each machine record, and optionally walks
every result page.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from autodl_cli.errors import APIError
from autodl_cli.handlers._common import require_success, require_success_list

if TYPE_CHECKING:
    from collections.abc import Iterable

    from autodl_cli.client import AutoDLClient

#: Path of the region catalogue used to resolve region identifiers.
COMMON_PATH = "/api/v1/common"

#: Path of the per-data-center GPU availability endpoint.
REGION_GPU_PATH = "/api/v1/machine/region/gpu_type"

#: Path of the machine-level availability endpoint used by the create page.
MACHINE_LIST_PATH = "/api/v1/user/machine/list"

#: Number of machines requested per API call when the caller does not choose.
DEFAULT_MACHINE_PAGE_SIZE = 20

#: Largest page size offered by the command's ``--page-size`` option.
MAX_MACHINE_PAGE_SIZE = 100

#: Page size used internally when the complete result set is needed. The
#: endpoint accepts large pages, so a full walk takes only a few requests.
FULL_FETCH_PAGE_SIZE = 1000

#: Billing modes a machine can be required to support.
MACHINE_CHARGE_TYPES = ("payg", "daily", "weekly", "monthly", "yearly")

#: Sort fields accepted by :func:`list_machines`.
MACHINE_SORT_FIELDS = ("price", "idle", "disk")

#: Request body field that carries each sort field.
_MACHINE_SORT_BODY_FIELDS = {
    "price": "pay_price_order",
    "idle": "gpu_idle_type",
    "disk": "instance_disk_size_order",
}

#: Machine record field used for each local sort field.
_MACHINE_SORT_KEYS = {
    "price": "payg_price",
    "idle": "gpu_idle_num",
    "disk": "max_instance_disk_size",
}


def list_regions(client: AutoDLClient) -> list[dict[str, object]]:
    """Return the region catalogue as one entry per data center.

    The ``region_list`` returned by ``GET /api/v1/common`` has one record per
    region sign, while stock is queried per data center. This handler groups
    the records so each data center appears once, with its signs deduplicated
    and kept in the order the API reported them.

    :param client: Authenticated API client.
    :returns: One mapping per data center with ``data_center``,
        ``region_name``, ``region_signs``, ``visible``, and ``used_for``, in
        first-seen order.
    :raises autodl_cli.errors.AuthError: When the token is rejected.
    :raises autodl_cli.errors.APIError: When the API reports a failure or
        returns malformed data.
    """
    payload = client.request("GET", COMMON_PATH)
    data = require_success(payload, action="region list")

    entries = data.get("region_list")
    if not isinstance(entries, list):
        raise APIError("AutoDL region list returned malformed data")

    regions: list[dict[str, object]] = []
    by_center: dict[str, dict[str, object]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise APIError("AutoDL region list returned malformed data")
        data_center = entry.get("data_center")
        region_sign = entry.get("region_sign")
        if not isinstance(data_center, str) or not data_center or not isinstance(region_sign, str) or not region_sign:
            raise APIError("AutoDL region list returned malformed data")

        region = by_center.get(data_center)
        if region is None:
            region_name = entry.get("region_name")
            if not isinstance(region_name, str) or not region_name:
                region_name = data_center
            region = {
                "data_center": data_center,
                "region_name": region_name,
                "region_signs": [],
                "visible": entry.get("visible"),
                "used_for": entry.get("used_for"),
            }
            by_center[data_center] = region
            regions.append(region)

        signs = region["region_signs"]
        if isinstance(signs, list) and region_sign not in signs:
            signs.append(region_sign)

    return regions


def region_signs(region: dict[str, object]) -> list[str]:
    """Return the region signs of a grouped region entry.

    :param region: One mapping returned by :func:`list_regions`.
    :returns: The non-empty string signs, in the order they were reported.
    """
    signs = region.get("region_signs")
    if not isinstance(signs, list):
        return []
    return [sign for sign in signs if isinstance(sign, str) and sign]


def _region_matches(region: dict[str, object], identifier: str) -> bool:
    """Check whether a region identifier names a grouped region.

    Matching is case-insensitive and ignores surrounding whitespace on both
    sides. A region is identified by its data center, its display name, or any
    of its region signs.

    :param region: One mapping returned by :func:`list_regions`.
    :param identifier: Normalised identifier (stripped and case-folded).
    :returns: Whether the identifier names the region.
    """
    data_center = region.get("data_center")
    if isinstance(data_center, str) and data_center.strip().casefold() == identifier:
        return True
    region_name = region.get("region_name")
    if isinstance(region_name, str) and region_name.strip().casefold() == identifier:
        return True
    return any(sign.strip().casefold() == identifier for sign in region_signs(region))


def _region_label(region: dict[str, object]) -> str:
    """Format a region for the unknown-identifier error message.

    :param region: One mapping returned by :func:`list_regions`.
    :returns: ``"西北B区 (west-B, west-C, west-D, west-E)"``.
    """
    name = region.get("region_name")
    if not isinstance(name, str) or not name:
        name = str(region.get("data_center", ""))
    return f"{name} ({', '.join(region_signs(region))})"


def select_regions(
    regions: Iterable[dict[str, object]],
    identifiers: Iterable[str],
) -> list[dict[str, object]]:
    """Resolve region identifiers to grouped regions, without duplicates.

    An identifier may be a region sign (``west-B``), a data center
    (``westDC3``), or a region name (``西北B区``). Repeated identifiers that
    resolve to the same data center are returned once, in first-seen order.

    :param regions: Grouped regions returned by :func:`list_regions`.
    :param identifiers: Region identifiers from the command line.
    :returns: One mapping per selected region, in first-seen order.
    :raises ValueError: When an identifier matches no known region.
    """
    known = list(regions)
    selected: list[dict[str, object]] = []
    seen: set[int] = set()
    for identifier in identifiers:
        lookup = identifier.strip().casefold()
        match_index: int | None = None
        for index, region in enumerate(known):
            if _region_matches(region, lookup):
                match_index = index
                break
        if match_index is None:
            labels = "; ".join(_region_label(region) for region in known)
            raise ValueError(f"Unknown region {identifier!r}. Known regions: {labels}")
        if match_index not in seen:
            seen.add(match_index)
            selected.append(known[match_index])
    return selected


def get_region_gpu(client: AutoDLClient, region: dict[str, object]) -> list[dict[str, object]]:
    """Return the GPU stock of one data center.

    The API answers with one single-key mapping per GPU type, where the key is
    the GPU name and the value holds the stock figures. Those mappings are
    flattened into one dict per GPU, sorted by idle capacity (descending) and
    then by GPU name.

    :param client: Authenticated API client.
    :param region: One mapping returned by :func:`list_regions`.
    :returns: One mapping per GPU type with ``region_name``, ``data_center``,
        ``region_signs``, ``gpu_type``, ``total_gpu_num``, ``idle_gpu_num``,
        ``chip_corp``, and ``cpu_arch``.
    :raises autodl_cli.errors.AuthError: When the token is rejected.
    :raises autodl_cli.errors.APIError: When the API reports a failure or
        returns malformed data.
    """
    signs = region_signs(region)
    payload = client.request("POST", REGION_GPU_PATH, json={"region_sign_list": signs})
    entries = require_success_list(payload, action="GPU availability")

    gpus: list[dict[str, object]] = []
    for entry in entries:
        if not isinstance(entry, dict) or len(entry) != 1:
            raise APIError("AutoDL GPU availability returned malformed data")
        gpu_type, stats = next(iter(entry.items()))
        if not isinstance(stats, dict):
            raise APIError("AutoDL GPU availability returned malformed data")
        total = stats.get("total_gpu_num")
        idle = stats.get("idle_gpu_num")
        if not isinstance(total, int) or isinstance(total, bool):
            raise APIError("AutoDL GPU availability returned malformed data")
        if not isinstance(idle, int) or isinstance(idle, bool):
            raise APIError("AutoDL GPU availability returned malformed data")
        gpus.append(
            {
                "region_name": region.get("region_name"),
                "data_center": region.get("data_center"),
                "region_signs": signs,
                "gpu_type": gpu_type,
                "total_gpu_num": total,
                "idle_gpu_num": idle,
                "chip_corp": stats.get("chip_corp"),
                "cpu_arch": stats.get("cpu_arch"),
            }
        )

    gpus.sort(key=lambda gpu: (-int(gpu["idle_gpu_num"]), str(gpu["gpu_type"])))
    return gpus


def list_gpu_availability(
    client: AutoDLClient,
    regions: Iterable[dict[str, object]],
    *,
    available_only: bool = False,
) -> list[dict[str, object]]:
    """Return the GPU stock for every selected region.

    A region with no GPU types is kept with an empty ``gpus`` list, so callers
    can still show that the region was queried.

    :param client: Authenticated API client.
    :param regions: Grouped regions returned by :func:`list_regions` or
        :func:`select_regions`.
    :param available_only: Drop GPU types whose ``idle_gpu_num`` is zero.
    :returns: One mapping per region with ``data_center``, ``region_name``,
        ``region_signs``, and ``gpus``, in the order the regions were given.
    :raises autodl_cli.errors.AuthError: When the token is rejected.
    :raises autodl_cli.errors.APIError: When the API reports a failure or
        returns malformed data.
    """
    availability: list[dict[str, object]] = []
    for region in regions:
        gpus = get_region_gpu(client, region)
        if available_only:
            gpus = [gpu for gpu in gpus if gpu["idle_gpu_num"] > 0]
        availability.append(
            {
                "data_center": region.get("data_center"),
                "region_name": region.get("region_name"),
                "region_signs": region_signs(region),
                "gpus": gpus,
            }
        )
    return availability


def find_gpu(
    client: AutoDLClient,
    regions: Iterable[dict[str, object]],
    model: str,
    *,
    available_only: bool = False,
) -> list[dict[str, object]]:
    """Search every selected region for GPU types matching a model name.

    The model is matched case-insensitively as a substring of each GPU's
    ``gpu_type``, after stripping surrounding whitespace on both sides. One
    request is sent per region. ``available_only`` drops GPU types with no idle
    capacity; matching types without idle capacity are otherwise kept, so a
    caller can still see that the model exists.

    :param client: Authenticated API client.
    :param regions: Grouped regions returned by :func:`list_regions` or
        :func:`select_regions`.
    :param model: Model name or fragment to match (for example ``4090``).
    :param available_only: Drop GPU types whose ``idle_gpu_num`` is zero.
    :returns: A flat list of the per-GPU mappings produced by
        :func:`get_region_gpu`, sorted by idle capacity (descending), then GPU
        type, then region name.
    :raises ValueError: When ``model`` is empty or whitespace.
    :raises autodl_cli.errors.AuthError: When the token is rejected.
    :raises autodl_cli.errors.APIError: When the API reports a failure or
        returns malformed data.
    """
    needle = model.strip().casefold()
    if not needle:
        raise ValueError("model must not be empty")

    matches: list[dict[str, object]] = []
    for region in regions:
        for gpu in get_region_gpu(client, region):
            gpu_type = gpu.get("gpu_type")
            if not isinstance(gpu_type, str) or needle not in gpu_type.strip().casefold():
                continue
            if available_only and gpu["idle_gpu_num"] == 0:
                continue
            matches.append(gpu)

    matches.sort(
        key=lambda gpu: (
            -int(gpu["idle_gpu_num"]),
            str(gpu["gpu_type"]),
            str(gpu["region_name"]),
        )
    )
    return matches


def _text(entry: dict[str, object], key: str) -> str:
    """Return a string field, or ``""`` when it is missing or not a string.

    :param entry: Machine record from the API.
    :param key: Field name.
    :returns: The value, or an empty string.
    """
    value = entry.get(key)
    return value if isinstance(value, str) else ""


def _integer(entry: dict[str, object], key: str) -> int | None:
    """Return an integer field, rejecting booleans.

    :param entry: Machine record from the API.
    :param key: Field name.
    :returns: The value, or ``None`` when it is missing or not an integer.
    """
    value = entry.get(key)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def _machine_prices(entry: dict[str, object]) -> dict[str, int]:
    """Collect the machine's prices by billing mode.

    ``machine_sku_info`` is the authoritative source; the top-level
    ``payg_price`` is used as a fallback for ``payg`` when the SKU list omits
    it.

    :param entry: Machine record from the API.
    :returns: Billing mode to price mapping, in raw thousandths of a yuan.
    """
    prices: dict[str, int] = {}
    skus = entry.get("machine_sku_info")
    if isinstance(skus, list):
        for sku in skus:
            if not isinstance(sku, dict):
                continue
            kind = sku.get("type")
            price = _integer(sku, "current_price")
            if isinstance(kind, str) and kind and price is not None:
                prices[kind] = price
    payg = _integer(entry, "payg_price")
    if payg is not None:
        prices["payg"] = payg
    return prices


def _machine_tags(entry: dict[str, object]) -> list[str]:
    """Collect the machine's tag names.

    The API currently reports tags either as strings or as objects with a
    ``name``/``tag_name`` field.

    :param entry: Machine record from the API.
    :returns: Tag names in the order they were reported, without duplicates.
    """
    tags: list[str] = []
    info = entry.get("machine_tag_info")
    if not isinstance(info, list):
        return tags
    for tag in info:
        name: object = tag
        if isinstance(tag, dict):
            name = tag.get("name") or tag.get("tag_name")
        if isinstance(name, str) and name and name not in tags:
            tags.append(name)
    return tags


def _normalize_machine(entry: object) -> dict[str, object]:
    """Flatten one machine record into the fields the CLI needs.

    ``machine_base_info`` and ``machine_sku_info`` are folded into the result;
    nested objects are not preserved.

    :param entry: One element of the endpoint's ``list`` array.
    :returns: A flat machine mapping.
    :raises autodl_cli.errors.APIError: When a required field is missing or
        has the wrong type.
    """
    if not isinstance(entry, dict):
        raise APIError("AutoDL machine list returned malformed data")

    machine_id = entry.get("machine_id")
    gpu_name = entry.get("gpu_name")
    gpu_number = _integer(entry, "gpu_number")
    gpu_idle_num = _integer(entry, "gpu_idle_num")
    if (
        not isinstance(machine_id, str)
        or not machine_id
        or not isinstance(gpu_name, str)
        or not gpu_name
        or gpu_number is None
        or gpu_idle_num is None
    ):
        raise APIError("AutoDL machine list returned malformed data")

    base = entry.get("machine_base_info")
    base_info = base if isinstance(base, dict) else {}
    prices = _machine_prices(entry)
    mount_net_disk = entry.get("mount_net_disk")
    enable_container_pro = entry.get("enable_container_pro")

    return {
        "machine_id": machine_id,
        "machine_name": _text(entry, "machine_name"),
        "machine_alias": _text(entry, "machine_alias"),
        "region_name": _text(entry, "region_name"),
        "region_sign": _text(entry, "region_sign"),
        "gpu_name": gpu_name,
        "gpu_number": gpu_number,
        "gpu_idle_num": gpu_idle_num,
        "gpu_used": _integer(entry, "gpu_used"),
        "gpu_memory": _integer(entry, "gpu_memory"),
        "chip_corp": _text(entry, "chip_corp"),
        "cpu_arch": _text(entry, "cpu_arch"),
        "cpu_per_gpu": _integer(entry, "cpu_per_gpu"),
        "mem_per_gpu": _integer(entry, "mem_per_gpu"),
        "cpu_num": _integer(base_info, "cpu_num"),
        "memory": _integer(base_info, "memory"),
        "disk_size": _integer(base_info, "disk_size"),
        "max_instance_disk_size": _integer(entry, "max_instance_disk_size"),
        "max_instance_num": _integer(entry, "max_instance_num"),
        "binding_instance_num": _integer(entry, "binding_instance_num"),
        "highest_cuda_version": _text(entry, "highest_cuda_version"),
        "driver_version": _text(entry, "driver_version"),
        "disk_type": _text(entry, "disk_type"),
        "on_line": _integer(entry, "on_line"),
        "health_status": _integer(entry, "health_status"),
        "mount_net_disk": mount_net_disk if isinstance(mount_net_disk, bool) else None,
        "enable_container_pro": enable_container_pro if isinstance(enable_container_pro, bool) else None,
        "machine_tags": _machine_tags(entry),
        "payg_price": prices.get("payg"),
        "daily_price": prices.get("daily"),
        "weekly_price": prices.get("weekly"),
        "monthly_price": prices.get("monthly"),
        "yearly_price": prices.get("yearly"),
        "description": _text(entry, "description"),
        "rent_deadline": _text(entry, "rent_deadline"),
    }


def _fetch_machine_page(
    client: AutoDLClient,
    body: dict[str, object],
    *,
    page_index: int,
) -> dict[str, object]:
    """Fetch and normalise one page of the machine listing.

    :param client: Authenticated API client.
    :param body: Filter body shared by every page.
    :param page_index: One-based page number to request.
    :returns: A mapping with ``machines``, ``page_index``, ``max_page``, and
        ``result_total``.
    :raises autodl_cli.errors.AuthError: When the token is rejected.
    :raises autodl_cli.errors.APIError: When the API reports a failure or
        returns malformed data.
    """
    payload = client.request("POST", MACHINE_LIST_PATH, json={**body, "page_index": page_index})
    data = require_success(payload, action="machine list")

    entries = data.get("list")
    if not isinstance(entries, list):
        raise APIError("AutoDL machine list returned malformed data")
    machines = [_normalize_machine(entry) for entry in entries]

    # A missing max_page means the server did not report how many pages exist;
    # stop after this one rather than risk looping forever.
    max_page = _integer(data, "max_page")
    if max_page is None or max_page < 1:
        max_page = page_index
    result_total = _integer(data, "result_total")
    if result_total is None or result_total < 0:
        result_total = len(machines)

    return {
        "machines": machines,
        "page_index": page_index,
        "max_page": max_page,
        "result_total": result_total,
    }


def list_machines(
    client: AutoDLClient,
    *,
    charge_type: str = "payg",
    region_signs: Iterable[str] = (),
    gpu_types: Iterable[str] = (),
    machine_tags: Iterable[str] = (),
    gpu_idle_num: int = 0,
    mount_net_disk: bool = False,
    cpu_archs: Iterable[str] = (),
    chip_corps: Iterable[str] = (),
    machine_id: str = "",
    date_range: str = "",
    date_from: str = "",
    date_to: str = "",
    sort_field: str | None = None,
    sort_order: str = "asc",
    page_index: int = 1,
    page_size: int = DEFAULT_MACHINE_PAGE_SIZE,
    all_pages: bool = False,
) -> dict[str, object]:
    """Return machine-level GPU availability.

    The body mirrors the web console's ``POST /api/v1/user/machine/list``
    request. The endpoint's ordering fields cannot be trusted: its
    ``pay_price_order`` is ignored, and ``gpu_idle_type`` only orders the
    first page of some region queries before later pages come back unsorted
    (occasionally even violating the ``gpu_idle_num`` filter). A requested
    sort, ``all_pages``, or a positive ``gpu_idle_num`` therefore fetches the
    whole result set at :data:`FULL_FETCH_PAGE_SIZE`, filters and sorts it
    locally, and then applies the requested page.

    :param client: Authenticated API client.
    :param charge_type: Billing mode the machine must support.
    :param region_signs: Region signs to search; empty means every region.
    :param gpu_types: Exact GPU type names to include; empty means no filter.
    :param machine_tags: Machine tag names to include; empty means no filter.
    :param gpu_idle_num: Minimum idle GPUs per machine; ``0`` disables the
        filter. The endpoint lets fully used machines through, so a positive
        minimum is enforced locally over the complete result set.
    :param mount_net_disk: Whether to require network-disk mounting support.
    :param cpu_archs: CPU architectures to include; empty means no filter.
    :param chip_corps: Chip vendors to include; empty means no filter.
    :param machine_id: Only this machine ID; empty means no filter.
    :param date_range: Availability date filter, passed to the API unchanged.
    :param date_from: Start of the availability date range.
    :param date_to: End of the availability date range.
    :param sort_field: ``price``, ``idle``, ``disk``, or ``None`` for the
        server's default order. A non-``None`` value fetches every page.
    :param sort_order: ``asc`` or ``desc``; only used with ``sort_field``.
    :param page_index: One-based page of the result to return; only used when
        ``all_pages`` is false.
    :param page_size: Machines per returned page; 1–100. A full walk fetches
        :data:`FULL_FETCH_PAGE_SIZE` machines per API call.
    :param all_pages: Whether to return every page instead of just one.
    :returns: A mapping with ``machines``, ``page_index``, ``page_size``,
        ``max_page``, ``result_total``, and ``all_pages``.
    :raises ValueError: When ``page_index``, ``page_size``, or a sort option
        is invalid.
    :raises autodl_cli.errors.AuthError: When the token is rejected.
    :raises autodl_cli.errors.APIError: When the API reports a failure or
        returns malformed data.
    """
    if page_index < 1:
        raise ValueError("page_index must be at least 1")
    if not 1 <= page_size <= MAX_MACHINE_PAGE_SIZE:
        raise ValueError(f"page_size must be between 1 and {MAX_MACHINE_PAGE_SIZE}")
    if sort_field is not None and sort_field not in MACHINE_SORT_FIELDS:
        raise ValueError(f"sort_field must be one of {', '.join(MACHINE_SORT_FIELDS)}")
    if sort_order not in ("asc", "desc"):
        raise ValueError("sort_order must be 'asc' or 'desc'")

    # The ordering parameters are still sent for parity with the web console,
    # even though the endpoint currently ignores them.
    sort_body = {
        "instance_disk_size_order": "",
        "pay_price_order": "",
        "gpu_idle_type": "",
    }
    if sort_field is not None:
        sort_body[_MACHINE_SORT_BODY_FIELDS[sort_field]] = sort_order

    local_sort = sort_field is not None
    # A local sort or idle filter needs the complete set to produce exact
    # ordering, counts, and page boundaries.
    fetch_every_page = all_pages or local_sort or gpu_idle_num > 0
    fetch_page_size = FULL_FETCH_PAGE_SIZE if fetch_every_page else page_size
    first_page = 1 if fetch_every_page else page_index

    body: dict[str, object] = {
        "charge_type": charge_type,
        "region_sign": "",
        "gpu_type_name": list(gpu_types),
        "machine_tag_name": list(machine_tags),
        "gpu_idle_num": gpu_idle_num,
        "mount_net_disk": mount_net_disk,
        **sort_body,
        "date_range": date_range,
        "date_from": date_from,
        "date_to": date_to,
        "page_index": first_page,
        "page_size": fetch_page_size,
        "default_order": sort_field is None,
        "region_sign_list": list(region_signs),
        "cpu_arch": list(cpu_archs),
        "chip_corp": list(chip_corps),
        "machine_id": machine_id,
    }

    machines: list[dict[str, object]] = []
    current = first_page
    max_page = first_page
    result_total = 0
    while True:
        page = _fetch_machine_page(client, body, page_index=current)
        page_machines = page["machines"]
        if not isinstance(page_machines, list):
            raise APIError("AutoDL machine list returned malformed data")
        machines.extend(page_machines)
        max_page = int(page["max_page"])
        result_total = int(page["result_total"])
        if not fetch_every_page or not page_machines or current >= max_page:
            break
        current += 1

    machines = [machine for machine in machines if _meets_idle_minimum(machine, gpu_idle_num)]

    if local_sort:
        machines = _sort_machines(machines, sort_field, sort_order)

    if not fetch_every_page:
        return {
            "machines": machines,
            "page_index": page_index,
            "page_size": page_size,
            "max_page": max_page,
            "result_total": result_total,
            "all_pages": all_pages,
        }

    # The walk fetched the complete set, so counts and page boundaries can be
    # recomputed after the local filter.
    result_total = len(machines)
    max_page = max(1, (result_total + page_size - 1) // page_size)
    if all_pages:
        selected = machines
        returned_page = 1
    else:
        start = (page_index - 1) * page_size
        selected = machines[start : start + page_size]
        returned_page = page_index
    return {
        "machines": selected,
        "page_index": returned_page,
        "page_size": page_size,
        "max_page": max_page,
        "result_total": result_total,
        "all_pages": all_pages,
    }


def _meets_idle_minimum(machine: dict[str, object], minimum: int) -> bool:
    """Check a machine against the idle-GPU minimum.

    The endpoint's ``gpu_idle_num`` filter lets fully used machines through
    even when a minimum is set, so the minimum is enforced again locally.

    :param machine: One normalised machine mapping.
    :param minimum: Minimum idle GPUs; ``0`` disables the check.
    :returns: Whether the machine has at least ``minimum`` idle GPUs.
    """
    if minimum <= 0:
        return True
    idle = machine.get("gpu_idle_num")
    return isinstance(idle, int) and not isinstance(idle, bool) and idle >= minimum


def _sort_machines(
    machines: list[dict[str, object]],
    sort_field: str,
    sort_order: str,
) -> list[dict[str, object]]:
    """Sort machines by one field, keeping missing values at the end.

    Python's sort is stable, so machines with equal keys keep the order the
    API returned them in.

    :param machines: Normalised machine mappings.
    :param sort_field: One of :data:`MACHINE_SORT_FIELDS`.
    :param sort_order: ``asc`` or ``desc``.
    :returns: A new list sorted in the requested direction.
    """
    key = _MACHINE_SORT_KEYS[sort_field]
    present: list[dict[str, object]] = []
    missing: list[dict[str, object]] = []
    for machine in machines:
        value = machine.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            present.append(machine)
        else:
            missing.append(machine)
    present.sort(key=lambda machine: int(machine[key]), reverse=sort_order == "desc")
    return present + missing
