"""Tests for :mod:`autodl_cli.handlers.gpu`, all offline."""

from __future__ import annotations

import json

import httpx
import pytest

from autodl_cli.client import AutoDLClient
from autodl_cli.errors import APIError, AuthError
from autodl_cli.handlers import gpu as gpu_handler

TOKEN = "fake-token"

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

#: Stock with several matching models, including one with no idle capacity.
FIND_DATA = [
    {"RTX 4090": {"total_gpu_num": 10, "idle_gpu_num": 2, "chip_corp": "nvidia", "cpu_arch": "x86"}},
    {"RTX 3090": {"total_gpu_num": 20, "idle_gpu_num": 6, "chip_corp": "nvidia", "cpu_arch": "x86"}},
    {"RTX 3090 Ti": {"total_gpu_num": 5, "idle_gpu_num": 6, "chip_corp": "nvidia", "cpu_arch": "x86"}},
    {"RTX 3080": {"total_gpu_num": 5, "idle_gpu_num": 0, "chip_corp": "nvidia", "cpu_arch": "x86"}},
    {"A100": {"total_gpu_num": 80, "idle_gpu_num": 3, "chip_corp": "nvidia", "cpu_arch": "x86"}},
]


def _success(data: object) -> httpx.Response:
    """Build a successful API envelope.

    :param data: The ``data`` value to wrap.
    :returns: A mock HTTP response.
    """
    return httpx.Response(200, json={"code": "Success", "msg": "", "data": data, "request_id": "req-1"})


def _regions() -> list[dict[str, object]]:
    """Return the grouped regions built from :data:`REGION_LIST`.

    :returns: The mappings produced by
        :func:`autodl_cli.handlers.gpu.list_regions`.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return _success({"region_list": REGION_LIST})

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        return gpu_handler.list_regions(client)


def test_list_regions_groups_by_data_center_in_first_seen_order() -> None:
    """Region signs are grouped per data center, preserving the API's order."""
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        return _success({"region_list": REGION_LIST})

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        regions = gpu_handler.list_regions(client)

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
        regions = gpu_handler.list_regions(client)

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
            gpu_handler.list_regions(client)


def test_list_regions_auth_failure_raises_auth_error() -> None:
    """An ``AuthorizeFailed`` envelope becomes an :class:`AuthError` with context."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"code": "AuthorizeFailed", "msg": "login timed out", "data": None, "request_id": "req-9"},
        )

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AuthError) as excinfo:
            gpu_handler.list_regions(client)

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
    selected = gpu_handler.select_regions(_regions(), [identifier])

    assert [region["data_center"] for region in selected] == [data_center]


def test_select_regions_dedupes_and_preserves_first_seen_order() -> None:
    """Repeated identifiers resolving to one data center are returned once."""
    selected = gpu_handler.select_regions(
        _regions(),
        ["foshan-A", "west-B", "westDC3", "西北B区", "west-C"],
    )

    assert [region["data_center"] for region in selected] == ["foshanDC1", "westDC3"]


@pytest.mark.parametrize("identifier", ["nowhere", "   "])
def test_select_regions_unknown_identifier_lists_known_regions(identifier: str) -> None:
    """An unknown or empty identifier fails with every known region listed."""
    with pytest.raises(ValueError) as excinfo:
        gpu_handler.select_regions(_regions(), [identifier])

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
        gpus = gpu_handler.get_region_gpu(client, region)

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
            gpu_handler.get_region_gpu(client, _regions()[0])


def test_get_region_gpu_non_list_data_raises_api_error() -> None:
    """A successful envelope with object-valued ``data`` is malformed."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _success({"RTX 4090": {}})

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(APIError, match="GPU availability returned malformed data"):
            gpu_handler.get_region_gpu(client, _regions()[0])


def test_get_region_gpu_auth_failure_raises_auth_error() -> None:
    """An auth failure from the GPU endpoint keeps its context."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"code": "TokenExpired", "msg": "please log in", "data": [], "request_id": "req-7"},
        )

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AuthError) as excinfo:
            gpu_handler.get_region_gpu(client, _regions()[0])

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
        availability = gpu_handler.list_gpu_availability(client, regions, available_only=True)

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
        availability = gpu_handler.list_gpu_availability(client, [region])

    assert availability == [
        {
            "data_center": "westDC3",
            "region_name": "西北B区",
            "region_signs": ["west-B", "west-C", "west-D", "west-E"],
            "gpus": [],
        }
    ]


def test_find_gpu_queries_every_region_and_sorts_by_idle_desc() -> None:
    """Each region is queried once and the flat result is globally sorted."""
    bodies: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return _success(GPU_DATA)

    regions = _regions()[:2]
    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        matches = gpu_handler.find_gpu(client, regions, "RtX")

    assert bodies == [
        {"region_sign_list": ["west-B", "west-C", "west-D", "west-E"]},
        {"region_sign_list": ["bj-B1", "bj-B2", "bj-B3"]},
    ]
    assert [gpu["gpu_type"] for gpu in matches] == ["RTX 3090", "RTX 3090", "RTX 4090", "RTX 4090"]
    assert [gpu["idle_gpu_num"] for gpu in matches] == [5, 5, 1, 1]
    assert [gpu["region_name"] for gpu in matches] == ["北京B区", "西北B区", "北京B区", "西北B区"]


def test_find_gpu_matches_case_insensitively_and_filters_idle() -> None:
    """Whitespace is stripped and ``available_only`` drops zero-idle types."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _success(FIND_DATA)

    region = _regions()[0]
    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        all_matches = gpu_handler.find_gpu(client, [region], "  rtx  ")
        available = gpu_handler.find_gpu(client, [region], "RTX", available_only=True)

    assert [gpu["gpu_type"] for gpu in all_matches] == ["RTX 3090", "RTX 3090 Ti", "RTX 4090", "RTX 3080"]
    assert [gpu["gpu_type"] for gpu in available] == ["RTX 3090", "RTX 3090 Ti", "RTX 4090"]


@pytest.mark.parametrize("model", ["", "   "])
def test_find_gpu_rejects_empty_model_without_a_request(model: str) -> None:
    """An empty or whitespace model fails before any stock request is sent."""
    regions = _regions()[:1]

    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("no stock request must be sent for an empty model")

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match="model"):
            gpu_handler.find_gpu(client, regions, model)
