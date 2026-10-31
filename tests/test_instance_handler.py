"""Tests for :mod:`autodl_cli.handlers.instance`, all offline."""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from autodl_cli.client import APP_VERSION, AutoDLClient
from autodl_cli.errors import APIError, AuthError
from autodl_cli.handlers import instance as instance_handler

TOKEN = "fake-token"
INSTANCES = [
    {
        "uuid": "cs1a2b3c4d5e6f7g8h",
        "name": "",
        "status": "running",
        "region_name": "内蒙B区",
        "snapshot_gpu_alias_name": "RTX 3090",
    },
    {
        "uuid": "cs9z8y7x6w5v4u3t2s",
        "name": "trainer",
        "status": "shutdown",
        "region_name": "西北B区",
        "snapshot_gpu_alias_name": "RTX 3080 Ti",
    },
]

#: Real ``region_list`` entries captured from ``GET /api/v1/common``, one per
#: region sign, in the order the API reports them.
REGION_LIST = [
    {
        "data_center": "westDC3",
        "region_sign": "west-B",
        "region_name": "西北B区",
        "used_for": "all",
        "visible": "all",
    },
    {
        "data_center": "westDC3",
        "region_sign": "west-C",
        "region_name": "西北B区",
        "used_for": "all",
        "visible": "all",
    },
    {
        "data_center": "westDC3",
        "region_sign": "west-D",
        "region_name": "西北B区",
        "used_for": "all",
        "visible": "all",
    },
    {
        "data_center": "westDC3",
        "region_sign": "west-E",
        "region_name": "西北B区",
        "used_for": "all",
        "visible": "all",
    },
    {
        "data_center": "beijingDC2",
        "region_sign": "bj-B1",
        "region_name": "北京B区",
        "used_for": "all",
        "visible": "all",
    },
    {
        "data_center": "beijingDC2",
        "region_sign": "bj-B2",
        "region_name": "北京B区",
        "used_for": "all",
        "visible": "all",
    },
    {
        "data_center": "beijingDC2",
        "region_sign": "bj-B3",
        "region_name": "北京B区",
        "used_for": "all",
        "visible": "all",
    },
    {
        "data_center": "chongqingDC1",
        "region_sign": "cq-A1",
        "region_name": "重庆A区",
        "used_for": "all",
        "visible": "all",
    },
    {
        "data_center": "neimengDC3",
        "region_sign": "nm-B1",
        "region_name": "内蒙B区",
        "used_for": "all",
        "visible": "all",
    },
    {
        "data_center": "neimengDC3",
        "region_sign": "nm-B2",
        "region_name": "内蒙B区",
        "used_for": "all",
        "visible": "all",
    },
    {
        "data_center": "beijingDC1",
        "region_sign": "beijing-A",
        "region_name": "北京A区",
        "used_for": "all",
        "visible": "all",
    },
    {
        "data_center": "beijingDC1",
        "region_sign": "beijing-B",
        "region_name": "北京A区",
        "used_for": "all",
        "visible": "all",
    },
    {
        "data_center": "beijingDC1",
        "region_sign": "beijing-D",
        "region_name": "北京A区",
        "used_for": "all",
        "visible": "all",
    },
    {
        "data_center": "beijingDC1",
        "region_sign": "beijing-E",
        "region_name": "北京A区",
        "used_for": "all",
        "visible": "all",
    },
    {
        "data_center": "foshanDC1",
        "region_sign": "foshan-A",
        "region_name": "佛山区",
        "used_for": "all",
        "visible": "all",
    },
    {
        "data_center": "beijingDC3",
        "region_sign": "beijing-C",
        "region_name": "V100专区",
        "used_for": "all",
        "visible": "all",
    },
    {
        "data_center": "neimengDC2",
        "region_sign": "nm-A1",
        "region_name": "A800专区",
        "used_for": "all",
        "visible": "all",
    },
    {
        "data_center": "shanghaiDC1",
        "region_sign": "sh-A1",
        "region_name": "摩尔线程专区",
        "used_for": "all",
        "visible": "all",
    },
    {
        "data_center": "westDC2",
        "region_sign": "west-X",
        "region_name": "西北企业区",
        "used_for": "all",
        "visible": "enterprise",
    },
]

#: Real per-GPU stock captured from the region ``gpu_type`` endpoint.
GPU_DATA = [
    {"RTX 4090": {"total_gpu_num": 735, "idle_gpu_num": 1, "chip_corp": "nvidia", "cpu_arch": "x86"}},
    {"RTX 3090": {"total_gpu_num": 120, "idle_gpu_num": 5, "chip_corp": "nvidia", "cpu_arch": "x86"}},
    {"A100": {"total_gpu_num": 80, "idle_gpu_num": 5, "chip_corp": "nvidia", "cpu_arch": "x86"}},
    {"CPU": {"total_gpu_num": 40, "idle_gpu_num": 0, "chip_corp": "intel", "cpu_arch": "x86"}},
]

Handler = Callable[[httpx.Request], httpx.Response]


def _page(
    entries: list[dict[str, object]],
    *,
    page_index: int = 1,
    max_page: int = 1,
) -> dict[str, object]:
    """Build the ``data`` object of an instance-list response.

    :param entries: Instances on this page.
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


def _success(data: object) -> httpx.Response:
    """Build a successful API envelope.

    :param data: The ``data`` value to wrap.
    :returns: A mock HTTP response.
    """
    return httpx.Response(200, json={"code": "Success", "msg": "", "data": data, "request_id": "req-1"})


def _regions() -> list[dict[str, object]]:
    """Return the grouped regions built from :data:`REGION_LIST`.

    :returns: The mappings produced by
        :func:`autodl_cli.handlers.instance.list_regions`.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return _success({"region_list": REGION_LIST})

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        return instance_handler.list_regions(client)


def test_list_instances_posts_expected_body() -> None:
    """The handler sends an authenticated POST with the default filter body."""
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["authorization"] = request.headers.get("Authorization")
        seen["app_version"] = request.headers.get("AppVersion")
        seen["body"] = json.loads(request.content)
        return _success(_page(INSTANCES))

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        assert instance_handler.list_instances(client) == INSTANCES

    assert seen == {
        "method": "POST",
        "path": "/api/v1/instance",
        "authorization": TOKEN,
        "app_version": APP_VERSION,
        "body": {
            "page_index": 1,
            "page_size": 100,
            "status": [],
            "charge_type": [],
            "sub_name": "",
            "unbind_sub_user": False,
        },
    }


def test_list_instances_walks_all_pages() -> None:
    """Every page up to ``max_page`` is fetched and concatenated in order."""
    seen: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page_index = json.loads(request.content)["page_index"]
        seen.append(page_index)
        if page_index == 1:
            return _success(_page(INSTANCES[:1], page_index=1, max_page=2))
        return _success(_page(INSTANCES[1:], page_index=2, max_page=2))

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        assert instance_handler.list_instances(client, page_size=1) == INSTANCES

    assert seen == [1, 2]


def test_list_instances_stops_when_server_clamps_page_index() -> None:
    """A server that clamps every page index to page 1 must not loop forever."""
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content)["page_index"])
        return _success(_page(INSTANCES, page_index=1, max_page=1))

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        assert instance_handler.list_instances(client) == INSTANCES

    assert calls == [1]


def test_list_instances_forwards_filters_on_every_page() -> None:
    """Filters reach every request, including when the caller passes iterators."""
    bodies: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        page_index = body["page_index"]
        entries = INSTANCES[:1] if page_index == 1 else INSTANCES[1:]
        return _success(_page(entries, page_index=page_index, max_page=2))

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        result = instance_handler.list_instances(
            client,
            page_size=25,
            statuses=iter(["running"]),
            charge_types=iter(["payg"]),
            sub_name="alice",
            unbind_sub_user=True,
        )

    assert result == INSTANCES
    assert [body["page_index"] for body in bodies] == [1, 2]
    for body in bodies:
        assert body["page_size"] == 25
        assert body["status"] == ["running"]
        assert body["charge_type"] == ["payg"]
        assert body["sub_name"] == "alice"
        assert body["unbind_sub_user"] is True


def test_list_instances_empty_result() -> None:
    """An empty list is returned instead of an error."""
    seen: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content)["page_index"])
        return _success(_page([], max_page=0))

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        assert instance_handler.list_instances(client) == []

    assert seen == [1]


def test_list_instances_rejects_non_positive_page_size() -> None:
    """A non-positive page size fails before any request is sent."""

    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("no request must be sent for an invalid page size")

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match="page_size"):
            instance_handler.list_instances(client, page_size=0)


def test_list_instances_auth_failure_raises_auth_error() -> None:
    """An ``AuthorizeFailed`` envelope becomes an :class:`AuthError` with context."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"code": "AuthorizeFailed", "msg": "login timed out", "data": None, "request_id": "req-9"},
        )

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AuthError) as excinfo:
            instance_handler.list_instances(client)

    assert "login timed out" in str(excinfo.value)
    assert "req-9" in str(excinfo.value)


@pytest.mark.parametrize("list_value", [None, "not-a-list", {"uuid": "x"}])
def test_list_instances_malformed_list_raises_api_error(list_value: object) -> None:
    """A successful envelope without a ``list`` array is malformed."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _success({"list": list_value, "max_page": 1})

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(APIError, match="malformed data"):
            instance_handler.list_instances(client)


def test_list_instances_non_object_entry_raises_api_error() -> None:
    """A ``list`` containing something other than an object is malformed."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _success({"list": ["not-an-instance"], "max_page": 1})

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(APIError, match="non-object entry"):
            instance_handler.list_instances(client)


def test_list_instances_missing_max_page_stops_after_one_page() -> None:
    """Without a usable ``max_page`` the handler returns the first page only."""
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content)["page_index"])
        return _success({"list": INSTANCES})

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        assert instance_handler.list_instances(client) == INSTANCES

    assert calls == [1]


def test_list_regions_groups_by_data_center_in_first_seen_order() -> None:
    """Region signs are grouped per data center, preserving the API's order."""
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        return _success({"region_list": REGION_LIST})

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        regions = instance_handler.list_regions(client)

    assert seen == {"method": "GET", "path": "/api/v1/common"}
    assert [region["data_center"] for region in regions] == [
        "westDC3",
        "beijingDC2",
        "chongqingDC1",
        "neimengDC3",
        "beijingDC1",
        "foshanDC1",
        "beijingDC3",
        "neimengDC2",
        "shanghaiDC1",
        "westDC2",
    ]
    assert regions[0] == {
        "data_center": "westDC3",
        "region_name": "西北B区",
        "region_signs": ["west-B", "west-C", "west-D", "west-E"],
        "visible": "all",
        "used_for": "all",
    }
    assert regions[1]["region_signs"] == ["bj-B1", "bj-B2", "bj-B3"]
    assert regions[-1]["visible"] == "enterprise"


def test_list_regions_dedupes_signs_and_falls_back_to_data_center() -> None:
    """Duplicate signs collapse and a missing name falls back to the data center."""
    entries = [
        {"data_center": "westDC3", "region_sign": "west-B"},
        {"data_center": "westDC3", "region_sign": "west-B"},
        {"data_center": "westDC3", "region_sign": "west-C", "region_name": "西北B区"},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return _success({"region_list": entries})

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        regions = instance_handler.list_regions(client)

    assert regions == [
        {
            "data_center": "westDC3",
            "region_name": "westDC3",
            "region_signs": ["west-B", "west-C"],
            "visible": None,
            "used_for": None,
        }
    ]


@pytest.mark.parametrize(
    "payload",
    [
        {"region_list": None},
        {"region_list": "not-a-list"},
        {"region_list": {}},
        {"region_list": ["not-an-object"]},
        {"region_list": [{"region_sign": "west-B"}]},
        {"region_list": [{"data_center": "westDC3"}]},
        {"region_list": [{"data_center": "", "region_sign": "west-B"}]},
        {"region_list": [{"data_center": "westDC3", "region_sign": ""}]},
        {"region_list": [{"data_center": 7, "region_sign": "west-B"}]},
    ],
)
def test_list_regions_malformed_raises_api_error(payload: dict[str, object]) -> None:
    """A malformed ``region_list`` or entry is rejected with a clear message."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _success(payload)

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(APIError, match="region list returned malformed data"):
            instance_handler.list_regions(client)


def test_list_regions_auth_failure_raises_auth_error() -> None:
    """An ``AuthorizeFailed`` envelope becomes an :class:`AuthError` with context."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"code": "AuthorizeFailed", "msg": "login timed out", "data": None, "request_id": "req-9"},
        )

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AuthError) as excinfo:
            instance_handler.list_regions(client)

    assert "login timed out" in str(excinfo.value)
    assert "req-9" in str(excinfo.value)


@pytest.mark.parametrize(
    ("identifier", "data_center"),
    [
        ("west-B", "westDC3"),
        ("westdc3", "westDC3"),
        ("WEST-D", "westDC3"),
        ("  西北B区  ", "westDC3"),
        ("bj-b2", "beijingDC2"),
        ("北京A区", "beijingDC1"),
        ("foshan-A", "foshanDC1"),
        ("beijing-C", "beijingDC3"),
        ("nm-A1", "neimengDC2"),
        ("sh-A1", "shanghaiDC1"),
        ("west-X", "westDC2"),
    ],
)
def test_select_regions_matches_sign_data_center_and_name(identifier: str, data_center: str) -> None:
    """Identifiers match a sign, a data center, or a name, case-insensitively."""
    selected = instance_handler.select_regions(_regions(), [identifier])

    assert [region["data_center"] for region in selected] == [data_center]


def test_select_regions_dedupes_and_preserves_first_seen_order() -> None:
    """Repeated identifiers resolving to one data center are returned once."""
    selected = instance_handler.select_regions(
        _regions(),
        ["foshan-A", "west-B", "westDC3", "西北B区", "west-C"],
    )

    assert [region["data_center"] for region in selected] == ["foshanDC1", "westDC3"]


@pytest.mark.parametrize("identifier", ["nowhere", "   "])
def test_select_regions_unknown_identifier_lists_known_regions(identifier: str) -> None:
    """An unknown or empty identifier fails with every known region listed."""
    with pytest.raises(ValueError) as excinfo:
        instance_handler.select_regions(_regions(), [identifier])

    message = str(excinfo.value)
    assert "西北B区 (west-B, west-C, west-D, west-E)" in message
    assert "; " in message


def test_get_region_gpu_posts_signs_and_flattens_sorted_gpus() -> None:
    """The endpoint receives the region signs and returns sorted flat mappings."""
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return _success(GPU_DATA)

    region = _regions()[0]
    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        gpus = instance_handler.get_region_gpu(client, region)

    assert seen == {
        "method": "POST",
        "path": "/api/v1/machine/region/gpu_type",
        "body": {"region_sign_list": ["west-B", "west-C", "west-D", "west-E"]},
    }
    assert [gpu["gpu_type"] for gpu in gpus] == ["A100", "RTX 3090", "RTX 4090", "CPU"]
    assert gpus[0] == {
        "region_name": "西北B区",
        "data_center": "westDC3",
        "region_signs": ["west-B", "west-C", "west-D", "west-E"],
        "gpu_type": "A100",
        "total_gpu_num": 80,
        "idle_gpu_num": 5,
        "chip_corp": "nvidia",
        "cpu_arch": "x86",
    }


@pytest.mark.parametrize(
    "entry",
    [
        "not-an-object",
        {"A": {}, "B": {}},
        {"RTX 4090": "not-an-object"},
        {"RTX 4090": {"total_gpu_num": "735", "idle_gpu_num": 1}},
        {"RTX 4090": {"total_gpu_num": True, "idle_gpu_num": 1}},
        {"RTX 4090": {"total_gpu_num": 735, "idle_gpu_num": False}},
        {"RTX 4090": {"total_gpu_num": 735}},
        {"RTX 4090": {"idle_gpu_num": 1}},
    ],
)
def test_get_region_gpu_malformed_entry_raises_api_error(entry: object) -> None:
    """Every malformed GPU entry is rejected with the documented message."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _success([entry])

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(APIError, match="GPU availability returned malformed data"):
            instance_handler.get_region_gpu(client, _regions()[0])


def test_get_region_gpu_non_list_data_raises_api_error() -> None:
    """A successful envelope with object-valued ``data`` is malformed."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _success({"RTX 4090": {}})

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(APIError, match="GPU availability returned malformed data"):
            instance_handler.get_region_gpu(client, _regions()[0])


def test_get_region_gpu_auth_failure_raises_auth_error() -> None:
    """An auth failure from the GPU endpoint keeps its context."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"code": "TokenExpired", "msg": "please log in", "data": [], "request_id": "req-7"},
        )

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AuthError) as excinfo:
            instance_handler.get_region_gpu(client, _regions()[0])

    assert "please log in" in str(excinfo.value)
    assert "req-7" in str(excinfo.value)


def test_list_gpu_availability_filters_zero_idle_gpus() -> None:
    """``available_only`` drops zero-idle types while keeping every region."""
    bodies: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return _success(GPU_DATA)

    regions = _regions()[:2]
    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        availability = instance_handler.list_gpu_availability(client, regions, available_only=True)

    assert [item["data_center"] for item in availability] == ["westDC3", "beijingDC2"]
    assert [gpu["gpu_type"] for gpu in availability[0]["gpus"]] == ["A100", "RTX 3090", "RTX 4090"]
    assert all(gpu["idle_gpu_num"] > 0 for item in availability for gpu in item["gpus"])
    assert bodies == [
        {"region_sign_list": ["west-B", "west-C", "west-D", "west-E"]},
        {"region_sign_list": ["bj-B1", "bj-B2", "bj-B3"]},
    ]


def test_list_gpu_availability_keeps_region_without_gpus() -> None:
    """A region with no GPU types is preserved with an empty ``gpus`` list."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _success([])

    region = _regions()[0]
    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        availability = instance_handler.list_gpu_availability(client, [region])

    assert availability == [
        {
            "data_center": "westDC3",
            "region_name": "西北B区",
            "region_signs": ["west-B", "west-C", "west-D", "west-E"],
            "gpus": [],
        }
    ]
