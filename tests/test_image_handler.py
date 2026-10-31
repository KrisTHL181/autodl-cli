"""Tests for :mod:`autodl_cli.handlers.image`, all offline."""

from __future__ import annotations

import httpx
import pytest

from autodl_cli.client import AutoDLClient
from autodl_cli.errors import APIError, AuthError
from autodl_cli.handlers import image as image_handler

TOKEN = "fake-token"


def _leaf(label: str, uuid: str, *, chip_corp: str = "nvidia", cpu_arch: str = "x86") -> dict[str, object]:
    """Build one CUDA-level leaf of the image option tree.

    :param label: CUDA version label.
    :param uuid: Base-image UUID.
    :param chip_corp: Chip vendor.
    :param cpu_arch: CPU architecture.
    :returns: A leaf shaped like the real API response.
    """
    return {
        "sort": 1,
        "label": label,
        "label_name": {
            "chip_corp": chip_corp,
            "cpu_arch": cpu_arch,
            "is_desktop": False,
            "uuid": uuid,
            "v": label,
        },
        "image_uuid": "",
    }


def _python(label: str, *leaves: dict[str, object]) -> dict[str, object]:
    """Build one Python/OS-level node.

    :param label: Python/OS label.
    :param leaves: CUDA-level children.
    :returns: A node shaped like the real API response.
    """
    return {"sort": 1, "label": label, "label_name": label, "image_uuid": "", "children": list(leaves)}


def _version(label: str, *pythons: dict[str, object]) -> dict[str, object]:
    """Build one framework-version-level node.

    :param label: Framework version label.
    :param pythons: Python/OS-level children.
    :returns: A node shaped like the real API response.
    """
    return {"sort": 1, "label": label, "label_name": label, "image_uuid": "", "children": list(pythons)}


def _framework(label: str, *versions: dict[str, object]) -> dict[str, object]:
    """Build one framework-level node.

    :param label: Framework name.
    :param versions: Framework-version-level children.
    :returns: A node shaped like the real API response.
    """
    return {"sort": 1, "label": label, "label_name": label, "image_uuid": "", "children": list(versions)}


#: A small tree with two frameworks, including two CUDA leaves under one
#: Python node and a non-NVIDIA image.
IMAGE_TREE = [
    _framework(
        "PyTorch",
        _version(
            "2.8.0",
            _python("3.12(ubuntu22.04)", _leaf("12.8", "base-image-ec1e9vdbd3")),
        ),
        _version(
            "2.12.1",
            _python("3.12(ubuntu22.04)", _leaf("13.0", "base-image-ee43618uo7")),
        ),
        _version(
            "2.11.0",
            _python(
                "3.10(ubuntu22.04)",
                _leaf("5.2.0", "base-image-gc8c4e8ndm", chip_corp="mthreads"),
            ),
        ),
    ),
    _framework(
        "Miniconda",
        _version(
            "conda3",
            _python(
                "3.8(ubuntu18.04)",
                _leaf("10.0", "base-image-1e5uf433g1"),
                _leaf("11.3", "base-image-7bn8iqhkb5"),
            ),
            _python("3.10(ubuntu22.04)", _leaf("11.8", "base-image-8hkyyugih5")),
        ),
    ),
]


def _success(data: object) -> httpx.Response:
    """Build a successful API envelope.

    :param data: The ``data`` value to wrap.
    :returns: A mock HTTP response.
    """
    return httpx.Response(200, json={"code": "Success", "msg": "", "data": data, "request_id": "req-1"})


def _list(tree: object = IMAGE_TREE, **filters: object) -> list[dict[str, object]]:
    """Run :func:`list_images` against a mock transport.

    :param tree: The ``data`` value returned by the endpoint.
    :param filters: Keyword filters forwarded to the handler.
    :returns: The flattened image list.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return _success(tree)

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        return image_handler.list_images(client, **filters)


def test_list_images_posts_to_catalogue_and_flattens_tree() -> None:
    """The handler POSTs to the catalogue endpoint and keeps the API's order."""
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["authorization"] = request.headers.get("authorization")
        seen["body"] = request.content
        return _success(IMAGE_TREE)

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        images = image_handler.list_images(client)

    assert seen == {
        "method": "POST",
        "path": "/api/v1/image/all",
        "authorization": TOKEN,
        "body": b"",
    }
    assert images == [
        {
            "framework_name": "PyTorch",
            "framework_version": "2.8.0",
            "python_version": "3.12(ubuntu22.04)",
            "cuda_version": "12.8",
            "image_uuid": "base-image-ec1e9vdbd3",
            "chip_corp": "nvidia",
            "cpu_arch": "x86",
            "is_desktop": False,
        },
        {
            "framework_name": "PyTorch",
            "framework_version": "2.12.1",
            "python_version": "3.12(ubuntu22.04)",
            "cuda_version": "13.0",
            "image_uuid": "base-image-ee43618uo7",
            "chip_corp": "nvidia",
            "cpu_arch": "x86",
            "is_desktop": False,
        },
        {
            "framework_name": "PyTorch",
            "framework_version": "2.11.0",
            "python_version": "3.10(ubuntu22.04)",
            "cuda_version": "5.2.0",
            "image_uuid": "base-image-gc8c4e8ndm",
            "chip_corp": "mthreads",
            "cpu_arch": "x86",
            "is_desktop": False,
        },
        {
            "framework_name": "Miniconda",
            "framework_version": "conda3",
            "python_version": "3.8(ubuntu18.04)",
            "cuda_version": "10.0",
            "image_uuid": "base-image-1e5uf433g1",
            "chip_corp": "nvidia",
            "cpu_arch": "x86",
            "is_desktop": False,
        },
        {
            "framework_name": "Miniconda",
            "framework_version": "conda3",
            "python_version": "3.8(ubuntu18.04)",
            "cuda_version": "11.3",
            "image_uuid": "base-image-7bn8iqhkb5",
            "chip_corp": "nvidia",
            "cpu_arch": "x86",
            "is_desktop": False,
        },
        {
            "framework_name": "Miniconda",
            "framework_version": "conda3",
            "python_version": "3.10(ubuntu22.04)",
            "cuda_version": "11.8",
            "image_uuid": "base-image-8hkyyugih5",
            "chip_corp": "nvidia",
            "cpu_arch": "x86",
            "is_desktop": False,
        },
    ]


def test_list_images_treats_missing_children_as_empty() -> None:
    """A framework without a ``children`` field contributes no images."""
    tree = [{"sort": 1, "label": "Empty", "label_name": "Empty", "image_uuid": ""}]

    assert _list(tree) == []


def test_list_images_filters_are_case_insensitive_substrings() -> None:
    """Each filter matches a fragment, ignoring case and surrounding space."""
    images = _list(frameworks=[" torch "])

    assert {image["framework_name"] for image in images} == {"PyTorch"}


def test_list_images_filters_combine_with_and() -> None:
    """Repeated values of one filter are ORed; different filters are ANDed."""
    images = _list(
        frameworks=["pytorch"],
        cuda_versions=["12", "13"],
        chip_corps=["NVIDIA"],
    )

    assert [image["image_uuid"] for image in images] == [
        "base-image-ec1e9vdbd3",
        "base-image-ee43618uo7",
    ]


def test_list_images_filters_cover_every_dimension() -> None:
    """Framework version, Python, and CPU architecture are all matched."""
    images = _list(
        framework_versions=["conda"],
        python_versions=["3.10"],
        cpu_archs=["X86"],
    )

    assert [image["image_uuid"] for image in images] == ["base-image-8hkyyugih5"]


def test_list_images_rejects_an_empty_filter() -> None:
    """A blank filter value is a caller error, not a match-everything wildcard."""
    with pytest.raises(ValueError, match="framework filter must not be empty"):
        _list(frameworks=["  "])


@pytest.mark.parametrize(
    "tree",
    [
        pytest.param({"not": "a list"}, id="data-not-a-list"),
        pytest.param([["not", "a", "dict"]], id="framework-not-a-dict"),
        pytest.param([{"label": "", "children": []}], id="empty-framework-label"),
        pytest.param([{"label": "PyTorch", "children": "nope"}], id="children-not-a-list"),
        pytest.param(
            [_framework("PyTorch", _version("2.8.0", _python("3.12", {"label": "12.8"})))],
            id="leaf-label-name-not-a-dict",
        ),
        pytest.param(
            [
                _framework(
                    "PyTorch",
                    _version(
                        "2.8.0",
                        _python(
                            "3.12",
                            {"label": "12.8", "label_name": {"uuid": "", "chip_corp": "nvidia"}},
                        ),
                    ),
                )
            ],
            id="empty-image-uuid",
        ),
    ],
)
def test_list_images_rejects_malformed_data(tree: object) -> None:
    """Malformed nodes raise an API error instead of being skipped silently."""
    with pytest.raises(APIError, match="image list returned malformed data"):
        _list(tree)


def test_list_images_surfaces_an_authentication_failure() -> None:
    """An ``AuthorizeFailed`` envelope becomes an :class:`AuthError`."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": "AuthorizeFailed", "msg": "login timed out", "data": None})

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AuthError, match="login timed out"):
            image_handler.list_images(client)
