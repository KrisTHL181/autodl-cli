"""Image-domain API handlers.

The public base-image catalogue is served by ``POST /api/v1/image/all`` as a
four-level option tree: framework, framework version, Python/OS, and CUDA
version. Only the last level carries a base-image UUID, so :func:`list_images`
flattens the tree into one record per selectable image while keeping the order
the API reports.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from autodl_cli.errors import APIError
from autodl_cli.handlers._common import require_success_list

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from autodl_cli.client import AutoDLClient

#: Path of the public base-image catalogue endpoint.
IMAGE_ALL_PATH = "/api/v1/image/all"

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


def get_create_options(client: AutoDLClient) -> dict[str, object]:
    """Return the options accepted when creating an instance.

    :param client: Authenticated API client.
    :returns: The create-options mapping.
    """
    ...
