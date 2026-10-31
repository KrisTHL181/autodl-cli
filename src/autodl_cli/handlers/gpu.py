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


def _region_signs(region: dict[str, object]) -> list[str]:
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
    return any(sign.strip().casefold() == identifier for sign in _region_signs(region))


def _region_label(region: dict[str, object]) -> str:
    """Format a region for the unknown-identifier error message.

    :param region: One mapping returned by :func:`list_regions`.
    :returns: ``"西北B区 (west-B, west-C, west-D, west-E)"``.
    """
    name = region.get("region_name")
    if not isinstance(name, str) or not name:
        name = str(region.get("data_center", ""))
    return f"{name} ({', '.join(_region_signs(region))})"


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
    signs = _region_signs(region)
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
                "region_signs": _region_signs(region),
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
