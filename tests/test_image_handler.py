"""Tests for :mod:`autodl_cli.handlers.image`, all offline."""

from __future__ import annotations

import json

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


#: Two sanitised private-image entries: one finished and one still saving.
PRIVATE_IMAGES = [
    {
        "id": 842525,
        "created_at": "2026-11-01T02:46:47+08:00",
        "updated_at": "2026-11-01T02:46:47+08:00",
        "image_uuid": "image-40c7c7115c",
        "instance_uuid": "mamykqv3ku-87936de3",
        "name": "save-image-test",
        "image_size": 1021552640,
        "progress_content": {"oss_file_size": 373865271, "progress": 100, "error": ""},
        "status": "finished",
        "chip_corp": "nvidia",
        "cpu_arch": "x86",
        "framework": "PyTorch:2.12.1",
        "python_v": "3.12(ubuntu22.04)",
        "cuda_v": "13.0",
        "is_desktop": False,
        "image_source": "private",
    },
    {
        "id": 842524,
        "created_at": "2026-11-01T02:45:00+08:00",
        "updated_at": "2026-11-01T02:45:00+08:00",
        "image_uuid": "image-11aa22bb33",
        "instance_uuid": "wn8vt448yq-473b14de",
        "name": "trainer-snapshot",
        "image_size": 0,
        "progress_content": {"oss_file_size": 157286400, "progress": 42, "error": ""},
        "status": "saving",
        "chip_corp": "nvidia",
        "cpu_arch": "x86",
        "framework": "TensorFlow:2.9.0",
        "python_v": "3.8(ubuntu20.04)",
        "cuda_v": "11.2",
        "is_desktop": False,
        "image_source": "private",
    },
]


def _private_page(
    entries: list[dict[str, object]],
    *,
    page_index: int = 1,
    max_page: int = 1,
) -> dict[str, object]:
    """Build the ``data`` object of a private-image list response.

    :param entries: Images on this page.
    :param page_index: One-based page number.
    :param max_page: Total number of pages reported by the server.
    :returns: A page mapping shaped like the real API response.
    """
    return {
        "list": entries,
        "page_index": page_index,
        "page_size": len(entries),
        "offset": 0,
        "max_page": max_page,
        "result_total": len(entries),
        "page": page_index,
    }


def test_list_private_images_posts_expected_body_and_returns_entries() -> None:
    """The handler sends the console's body and returns the entries unchanged."""
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["authorization"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return _success(_private_page(PRIVATE_IMAGES))

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        images = image_handler.list_private_images(client, page_size=20)

    assert seen == {
        "method": "POST",
        "path": "/api/v1/image/private/list",
        "authorization": TOKEN,
        "body": {
            "order_uuid": "",
            "date_from": "",
            "date_to": "",
            "page_index": 1,
            "page_size": 20,
        },
    }
    assert images == PRIVATE_IMAGES


def test_list_private_images_walks_all_pages() -> None:
    """Every page up to ``max_page`` is fetched and concatenated in order."""
    requested: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page_index = json.loads(request.content)["page_index"]
        requested.append(page_index)
        entry = dict(PRIVATE_IMAGES[0], image_uuid=f"image-page-{page_index}")
        return _success(_private_page([entry], page_index=page_index, max_page=2))

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        images = image_handler.list_private_images(client)

    assert requested == [1, 2]
    assert [image["image_uuid"] for image in images] == ["image-page-1", "image-page-2"]


def test_list_private_images_rejects_a_non_positive_page_size() -> None:
    """A zero or negative page size is rejected before any request."""
    with pytest.raises(ValueError, match="page_size must be at least 1"):
        with AutoDLClient(TOKEN, transport=httpx.MockTransport(lambda request: pytest.fail("no request"))) as client:
            image_handler.list_private_images(client, page_size=0)


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(None, id="data-not-an-object"),
        pytest.param({"list": "nope"}, id="list-not-an-array"),
        pytest.param({"list": [["not", "a", "dict"]]}, id="entry-not-a-dict"),
    ],
)
def test_list_private_images_rejects_malformed_data(data: object) -> None:
    """Malformed pages raise an API error instead of being skipped silently."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _success(data)

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(APIError, match="private image list"):
            image_handler.list_private_images(client)


def test_list_private_images_surfaces_an_authentication_failure() -> None:
    """An ``AuthorizeFailed`` envelope becomes an :class:`AuthError`."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": "AuthorizeFailed", "msg": "login timed out", "data": None})

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AuthError, match="login timed out"):
            image_handler.list_private_images(client)
