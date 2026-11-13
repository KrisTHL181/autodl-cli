"""Image-domain API handlers.

The public base-image catalogue is served by ``POST /api/v1/image/all`` as a
four-level option tree: framework, framework version, Python/OS, and CUDA
version. Only the last level carries a base-image UUID, so :func:`list_images`
flattens the tree into one record per selectable image while keeping the order
the API reports.

The account's own saved images live behind
``POST /api/v1/image/private/list``, a paged endpoint like the instance list.
:func:`list_private_images` walks every page and returns the entries unchanged.
Deleting one uses ``DELETE /api/v1/image/private/delete`` with the numeric
``image_id`` from that list, not the ``image-uuid`` string; it answers with
``"data": null``.

A save is followed through the same list: :func:`wait_for_private_image` polls
until a matching image finishes, comparing against a pre-save snapshot from
:func:`private_image_status_snapshot` so a retry ignores the older entry.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from autodl_cli.errors import APIError
from autodl_cli.handlers import _poll
from autodl_cli.handlers._common import require_success, require_success_any, require_success_list

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence

    from autodl_cli.client import AutoDLClient

#: Path of the public base-image catalogue endpoint.
IMAGE_ALL_PATH = "/api/v1/image/all"

#: Path of the account's private-image list endpoint.
PRIVATE_IMAGE_LIST_PATH = "/api/v1/image/private/list"

#: Path of the private-image delete endpoint.
PRIVATE_IMAGE_DELETE_PATH = "/api/v1/image/private/delete"

#: Number of private images requested per API call when the caller does not choose.
DEFAULT_PRIVATE_PAGE_SIZE = 100

#: Largest page size accepted by the private-image listing.
MAX_PRIVATE_PAGE_SIZE = 100

#: Private-image statuses that mean the save will never finish.
FAILED_IMAGE_STATUSES = frozenset({"failed", "error"})

_MALFORMED = "AutoDL image list returned malformed data"


def _children(entry: object) -> list[object]:
    """Return a tree node's children.

    :param entry: One node of the image option tree.
    :returns: The ``children`` array, or an empty list when the node has none.
    :raises autodl_cli.errors.APIError: When the node or its ``children``
        field is malformed.
    """
    if not isinstance(entry, dict):
        raise APIError(_MALFORMED)
    children = entry.get("children")
    if children is None:
        return []
    if not isinstance(children, list):
        raise APIError(_MALFORMED)
    return children


def _label(entry: object) -> str:
    """Return a tree node's display label.

    :param entry: One node of the image option tree.
    :returns: The non-empty ``label`` string.
    :raises autodl_cli.errors.APIError: When the node or its label is missing
        or malformed.
    """
    if not isinstance(entry, dict):
        raise APIError(_MALFORMED)
    label = entry.get("label")
    if not isinstance(label, str) or not label:
        raise APIError(_MALFORMED)
    return label


def _optional_text(value: object) -> str:
    """Return a string field, or ``""`` when it is missing or not a string.

    :param value: Raw field value.
    :returns: The value, or an empty string.
    """
    return value if isinstance(value, str) else ""


def _leaf_image(
    entry: object, *, framework_name: str, framework_version: str, python_version: str
) -> dict[str, object]:
    """Flatten one CUDA-level leaf into an image record.

    :param entry: The leaf node, whose ``label_name`` is the metadata object.
    :param framework_name: Framework label from the tree's first level.
    :param framework_version: Version label from the tree's second level.
    :param python_version: Python/OS label from the tree's third level.
    :returns: A flat image mapping.
    :raises autodl_cli.errors.APIError: When the leaf or its metadata is
        missing, has the wrong type, or has no image UUID.
    """
    cuda_version = _label(entry)
    metadata = entry.get("label_name")
    if not isinstance(metadata, dict):
        raise APIError(_MALFORMED)
    image_uuid = metadata.get("uuid")
    if not isinstance(image_uuid, str) or not image_uuid:
        raise APIError(_MALFORMED)

    is_desktop = metadata.get("is_desktop")
    return {
        "framework_name": framework_name,
        "framework_version": framework_version,
        "python_version": python_version,
        "cuda_version": cuda_version,
        "image_uuid": image_uuid,
        "chip_corp": _optional_text(metadata.get("chip_corp")),
        "cpu_arch": _optional_text(metadata.get("cpu_arch")),
        "is_desktop": is_desktop if isinstance(is_desktop, bool) else None,
    }


def _flatten_tree(entries: Sequence[object]) -> list[dict[str, object]]:
    """Flatten the four-level image option tree.

    A framework or version with no children contributes no images; an image is
    only selectable at the fourth level, where the UUID lives. The API's order
    is kept.

    :param entries: The endpoint's top-level option array.
    :returns: One flat mapping per selectable image.
    :raises autodl_cli.errors.APIError: When any level is malformed.
    """
    images: list[dict[str, object]] = []
    for framework in entries:
        framework_name = _label(framework)
        for version in _children(framework):
            framework_version = _label(version)
            for python in _children(version):
                python_version = _label(python)
                for leaf in _children(python):
                    images.append(
                        _leaf_image(
                            leaf,
                            framework_name=framework_name,
                            framework_version=framework_version,
                            python_version=python_version,
                        )
                    )
    return images


def _normalise_filter(name: str, values: Iterable[str]) -> tuple[str, ...]:
    """Normalise one filter option into case-insensitive needles.

    :param name: Option name used in the error message.
    :param values: Raw values from the command line.
    :returns: Stripped, case-folded needles.
    :raises ValueError: When a value is empty or whitespace.
    """
    needles: list[str] = []
    for value in values:
        needle = value.strip().casefold()
        if not needle:
            raise ValueError(f"{name} filter must not be empty")
        needles.append(needle)
    return tuple(needles)


def _matches(value: object, needles: tuple[str, ...]) -> bool:
    """Check one field against a set of needles.

    An empty needle list matches every value. Values are matched as
    case-insensitive substrings.

    :param value: Field value from an image mapping.
    :param needles: Normalised needles from :func:`_normalise_filter`.
    :returns: Whether the value matches any needle.
    """
    if not needles:
        return True
    text = str(value).strip().casefold()
    return any(needle in text for needle in needles)


def list_images(
    client: AutoDLClient,
    *,
    frameworks: Iterable[str] = (),
    framework_versions: Iterable[str] = (),
    python_versions: Iterable[str] = (),
    cuda_versions: Iterable[str] = (),
    chip_corps: Iterable[str] = (),
    cpu_archs: Iterable[str] = (),
) -> list[dict[str, object]]:
    """Return the base images available for new instances.

    ``POST /api/v1/image/all`` returns a four-level option tree; this handler
    flattens it into one record per selectable image, in the order the API
    reports. Every filter is matched case-insensitively as a substring;
    repeated values are ORed within one filter and ANDed across filters.

    :param client: Authenticated API client.
    :param frameworks: Framework names or fragments to include.
    :param framework_versions: Framework versions to include.
    :param python_versions: Python/OS labels to include.
    :param cuda_versions: CUDA versions to include.
    :param chip_corps: Chip vendors to include, for example ``nvidia``.
    :param cpu_archs: CPU architectures to include, for example ``x86``.
    :returns: One mapping per image with ``framework_name``,
        ``framework_version``, ``python_version``, ``cuda_version``,
        ``image_uuid``, ``chip_corp``, ``cpu_arch``, and ``is_desktop``.
    :raises ValueError: When a filter value is empty.
    :raises autodl_cli.errors.AuthError: When the token is rejected.
    :raises autodl_cli.errors.APIError: When the API reports a failure or
        returns malformed data.
    """
    wanted_frameworks = _normalise_filter("framework", frameworks)
    wanted_versions = _normalise_filter("framework version", framework_versions)
    wanted_python = _normalise_filter("python", python_versions)
    wanted_cuda = _normalise_filter("cuda", cuda_versions)
    wanted_chips = _normalise_filter("chip", chip_corps)
    wanted_archs = _normalise_filter("arch", cpu_archs)

    payload = client.request("POST", IMAGE_ALL_PATH)
    entries = require_success_list(payload, action="image list")
    images = _flatten_tree(entries)

    return [
        image
        for image in images
        if _matches(image["framework_name"], wanted_frameworks)
        and _matches(image["framework_version"], wanted_versions)
        and _matches(image["python_version"], wanted_python)
        and _matches(image["cuda_version"], wanted_cuda)
        and _matches(image["chip_corp"], wanted_chips)
        and _matches(image["cpu_arch"], wanted_archs)
    ]


def _fetch_private_page(
    client: AutoDLClient,
    *,
    page_index: int,
    page_size: int,
) -> tuple[list[dict[str, object]], int]:
    """Fetch one page of the private-image list.

    :param client: Authenticated API client.
    :param page_index: One-based page number to request.
    :param page_size: Images to request for this page.
    :returns: The page's image mappings and the total number of pages.
    :raises autodl_cli.errors.AuthError: When the token is rejected.
    :raises autodl_cli.errors.APIError: When the API reports a failure or
        returns malformed data.
    """
    body: dict[str, object] = {
        "order_uuid": "",
        "date_from": "",
        "date_to": "",
        "page_index": page_index,
        "page_size": page_size,
    }
    payload = client.request("POST", PRIVATE_IMAGE_LIST_PATH, json=body)
    data = require_success(payload, action="private image list")

    entries = data.get("list")
    if not isinstance(entries, list):
        raise APIError("AutoDL private image list returned malformed data")

    images: list[dict[str, object]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise APIError("AutoDL private image list returned a non-object entry")
        images.append(entry)

    # A missing or non-integer max_page means the server did not say how many
    # pages exist; stop after this one rather than risk looping forever.
    max_page = data.get("max_page")
    if not isinstance(max_page, int) or isinstance(max_page, bool):
        max_page = page_index

    return images, max_page


def list_private_images(
    client: AutoDLClient,
    *,
    page_size: int = DEFAULT_PRIVATE_PAGE_SIZE,
) -> list[dict[str, object]]:
    """Return the images saved from this account's instances.

    Every page is fetched, so the result is not limited by the per-request page
    size. The API's entries are returned unchanged, preserving the save status,
    progress, size, and source-instance metadata for callers.

    :param client: Authenticated API client.
    :param page_size: Images requested per API call; must be positive.
    :returns: One mapping per private image, newest first as the API reports.
    :raises ValueError: When ``page_size`` is not positive.
    :raises autodl_cli.errors.AuthError: When the token is rejected.
    :raises autodl_cli.errors.APIError: When the API reports a failure or
        returns malformed data.
    """
    if page_size < 1:
        raise ValueError("page_size must be at least 1")

    images: list[dict[str, object]] = []
    page_index = 1
    while True:
        entries, max_page = _fetch_private_page(client, page_index=page_index, page_size=page_size)
        images.extend(entries)
        if not entries or page_index >= max_page:
            break
        page_index += 1
    return images


def delete_private_image(client: AutoDLClient, image_id: int) -> dict[str, object]:
    """Delete one private image.

    The console deletes by the numeric ``id`` field of the private-image list,
    not by the ``image-uuid`` string. The endpoint answers with
    ``"data": null`` on success.

    :param client: Authenticated API client.
    :param image_id: Numeric image ID from :func:`list_private_images`.
    :returns: A mapping with ``image_id`` and ``deleted``.
    :raises ValueError: When ``image_id`` is not a positive integer.
    :raises autodl_cli.errors.AuthError: When the token is rejected.
    :raises autodl_cli.errors.APIError: When the API reports a failure.
    """
    if isinstance(image_id, bool) or not isinstance(image_id, int) or image_id <= 0:
        raise ValueError("image_id must be a positive integer")

    payload = client.request("DELETE", PRIVATE_IMAGE_DELETE_PATH, json={"image_id": image_id})
    require_success_any(payload, action="delete private image")

    return {"image_id": image_id, "deleted": True}


def _is_matching_private_image(entry: dict[str, object], instance_uuid: str, image_name: str) -> bool:
    """Return whether an entry is the save of a given instance under a name.

    Both fields must match exactly: the listing is not filtered by the server,
    so a substring match could pick up another image.

    :param entry: One private-image mapping from :func:`list_private_images`.
    :param instance_uuid: Source instance UUID of the save.
    :param image_name: Name the image is being saved under.
    :returns: ``True`` when the entry names the same instance and image.
    """
    return entry.get("instance_uuid") == instance_uuid and entry.get("name") == image_name


def _image_status(entry: dict[str, object]) -> str:
    """Return a private image's status string.

    :param entry: One private-image mapping.
    :returns: The status, or an empty string when it is missing or not a string.
    """
    status = entry.get("status")
    return status if isinstance(status, str) else ""


def _save_error(entry: dict[str, object]) -> str:
    """Return the save error reported inside a private image's progress data.

    :param entry: One private-image mapping.
    :returns: The non-empty ``progress_content.error`` string, or ``""``.
    """
    progress = entry.get("progress_content")
    if not isinstance(progress, dict):
        return ""
    error = progress.get("error")
    return error if isinstance(error, str) and error else ""


def private_image_status_snapshot(
    client: AutoDLClient,
    instance_uuid: str,
    image_name: str,
) -> dict[int, str]:
    """Snapshot the private images already saved for one instance and name.

    A save is identified by the exact pair of source instance UUID and image
    name, which is what :func:`wait_for_private_image` compares against. The
    snapshot lets a retry (``--try-again``) ignore an older finished or failed
    entry and wait for the new save instead.

    :param client: Authenticated API client.
    :param instance_uuid: Source instance UUID of the save.
    :param image_name: Name the image is being saved under.
    :returns: A mapping of positive numeric image ID to status.
    :raises ValueError: When either identifier is blank.
    :raises autodl_cli.errors.AuthError: When the token is rejected.
    :raises autodl_cli.errors.APIError: When the API reports a failure or
        returns malformed data.
    """
    instance = instance_uuid.strip()
    name = image_name.strip()
    if not instance:
        raise ValueError("instance_uuid must not be empty")
    if not name:
        raise ValueError("image_name must not be empty")

    snapshot: dict[int, str] = {}
    for entry in list_private_images(client):
        if not _is_matching_private_image(entry, instance, name):
            continue
        image_id = entry.get("id")
        if isinstance(image_id, bool) or not isinstance(image_id, int) or image_id <= 0:
            continue
        snapshot[image_id] = _image_status(entry)
    return snapshot


def wait_for_private_image(
    client: AutoDLClient,
    *,
    instance_uuid: str,
    image_name: str,
    previous_statuses: Mapping[int, str],
    interval: float = 10.0,
    timeout: float = 0.0,
    retry: int = 0,
    on_event: Callable[[dict[str, object]], None] | None = None,
) -> dict[str, object]:
    """Poll the private-image list until a save finishes.

    Only images whose source instance UUID and name match exactly are
    considered. A save that was already present with the same status in
    ``previous_statuses`` is ignored, which keeps ``--try-again`` from
    returning an older finished image or failing on an older failed one.

    An image succeeds when its status is ``finished`` and it is new or has
    changed status. A new or changed image whose status is ``failed`` or
    ``error``, or whose ``progress_content`` carries a non-empty ``error``,
    raises :class:`~autodl_cli.errors.APIError`.

    When ``timeout`` is ``0`` there is no deadline and the call blocks until
    the save finishes or the process is interrupted.

    :param client: Authenticated API client.
    :param instance_uuid: Source instance UUID of the save.
    :param image_name: Name the image is being saved under.
    :param previous_statuses: Snapshot from
        :func:`private_image_status_snapshot`, taken before the save request.
    :param interval: Seconds between checks; must be positive.
    :param timeout: Maximum seconds to wait; ``0`` waits until interrupted.
    :param retry: Consecutive transient polling errors to retry; ``0`` disables
        retries.
    :param on_event: Optional progress callback. ``image_status`` events are
        emitted whenever a matching image's status changes, followed by
        ``finished`` on success.
    :returns: A mapping with ``image_uuid``, ``image_id``, ``name``,
        ``status``, ``waited_seconds``, and ``image`` (the matching entry).
    :raises ValueError: When an identifier is blank or a numeric option is
        invalid.
    :raises TimeoutError: When ``timeout`` expires before the save finishes.
    :raises autodl_cli.errors.AuthError: When the token is rejected.
    :raises autodl_cli.errors.APIError: When the save reports a failure.
    """
    instance = instance_uuid.strip()
    name = image_name.strip()
    if not instance:
        raise ValueError("instance_uuid must not be empty")
    if not name:
        raise ValueError("image_name must not be empty")
    if isinstance(interval, bool) or not isinstance(interval, (int, float)) or interval <= 0:
        raise ValueError("interval must be a positive number")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout < 0:
        raise ValueError("timeout must not be negative")
    if isinstance(retry, bool) or not isinstance(retry, int) or retry < 0:
        raise ValueError("retry must be an integer of at least 0")

    previous = dict(previous_statuses)
    started = _poll.now()
    deadline = started + timeout if timeout > 0 else None
    last_statuses: dict[int, str] = {}
    last_status: str | None = None

    while True:
        retry_reason = f"waiting for image {name!r} from instance {instance} (last status: {last_status!r})"
        images = _poll.call_with_retry(
            lambda: list_private_images(client),
            retry=retry,
            interval=interval,
            deadline=deadline,
            timeout=timeout,
            on_event=on_event,
            timeout_reason=retry_reason,
        )

        matches: list[tuple[int, dict[str, object]]] = []
        for entry in images:
            if not _is_matching_private_image(entry, instance, name):
                continue
            image_id = entry.get("id")
            if isinstance(image_id, bool) or not isinstance(image_id, int) or image_id <= 0:
                continue
            matches.append((image_id, entry))

        for image_id, entry in matches:
            status = _image_status(entry)
            if last_statuses.get(image_id) != status:
                progress = entry.get("progress_content")
                _poll.emit(
                    on_event,
                    {
                        "event": "image_status",
                        "image_id": image_id,
                        "name": name,
                        "status": status or "unknown",
                        "progress": progress if isinstance(progress, dict) else None,
                    },
                )
                last_statuses[image_id] = status
            last_status = status or "unknown"

            changed = image_id not in previous or previous[image_id] != status
            if not changed:
                continue

            folded = status.casefold()
            error = _save_error(entry)
            if folded in FAILED_IMAGE_STATUSES:
                raise APIError(f"Image {name!r} entered status {status!r} while waiting for it to finish")
            if folded == "finished":
                _poll.emit(
                    on_event,
                    {
                        "event": "finished",
                        "image_uuid": entry.get("image_uuid"),
                        "image_id": image_id,
                        "name": name,
                    },
                )
                return {
                    "image_uuid": entry.get("image_uuid"),
                    "image_id": image_id,
                    "name": name,
                    "status": status,
                    "waited_seconds": round(_poll.now() - started, 1),
                    "image": entry,
                }
            if error:
                raise APIError(f"Image {name!r} failed to save: {error}")

        timeout_reason = f"waiting for image {name!r} from instance {instance} (last status: {last_status!r})"
        _poll.raise_if_timed_out(deadline, timeout=timeout, reason=timeout_reason)
        _poll.sleep(interval)
