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


def _machine(machine_id: str = "m1", **overrides: object) -> dict[str, object]:
    """Build a machine record shaped like the user machine list response.

    :param machine_id: Identifier of the machine.
    :param overrides: Fields to replace.
    :returns: A machine record.
    """
    record: dict[str, object] = {
        "machine_id": machine_id,
        "machine_name": "a***1",
        "machine_alias": "A03机",
        "region_name": "北京B区",
        "region_sign": "bj-B1",
        "gpu_name": "vGPU-32GB",
        "gpu_number": 8,
        "gpu_idle_num": 1,
        "gpu_used": 7,
        "gpu_memory": 34359738368,
        "chip_corp": "nvidia",
        "cpu_arch": "x86",
        "cpu_per_gpu": 12,
        "mem_per_gpu": 66571993088,
        "max_instance_disk_size": 53687091200,
        "max_instance_num": 180,
        "binding_instance_num": 96,
        "highest_cuda_version": "13.0",
        "driver_version": "580.105.08",
        "disk_type": "SSD",
        "description": "",
        "rent_deadline": "2027-10-01T00:00:00+08:00",
        "on_line": 2,
        "health_status": 0,
        "mount_net_disk": False,
        "enable_container_pro": True,
        "machine_tag_info": [],
        "machine_base_info": {
            "cpu_num": 96,
            "memory": 540642230272,
            "disk_size": 15360594018304,
        },
        "payg_price": 1660,
        "machine_sku_info": [
            {"type": "payg", "current_price": 1660},
            {"type": "daily", "current_price": 38650},
            {"type": "weekly", "current_price": 262000},
            {"type": "monthly", "current_price": 867000},
            {"type": "yearly", "current_price": 0},
        ],
    }
    record.update(overrides)
    return record


NORMALIZED_MACHINE = {
    "machine_id": "m1",
    "machine_name": "a***1",
    "machine_alias": "A03机",
    "region_name": "北京B区",
    "region_sign": "bj-B1",
    "gpu_name": "vGPU-32GB",
    "gpu_number": 8,
    "gpu_idle_num": 1,
    "gpu_used": 7,
    "gpu_memory": 34359738368,
    "chip_corp": "nvidia",
    "cpu_arch": "x86",
    "cpu_per_gpu": 12,
    "mem_per_gpu": 66571993088,
    "cpu_num": 96,
    "memory": 540642230272,
    "disk_size": 15360594018304,
    "max_instance_disk_size": 53687091200,
    "max_instance_num": 180,
    "binding_instance_num": 96,
    "highest_cuda_version": "13.0",
    "driver_version": "580.105.08",
    "disk_type": "SSD",
    "on_line": 2,
    "health_status": 0,
    "mount_net_disk": False,
    "enable_container_pro": True,
    "machine_tags": [],
    "payg_price": 1.66,
    "daily_price": 38.65,
    "weekly_price": 262.0,
    "monthly_price": 867.0,
    "yearly_price": 0.0,
    "description": "",
    "rent_deadline": "2027-10-01T00:00:00+08:00",
}


def test_list_machines_sends_full_body_and_normalizes() -> None:
    """Every filter reaches the request body and the record is flattened."""
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return _success(
            {
                "list": [_machine()],
                "page_index": 2,
                "page_size": 5,
                "max_page": 7,
                "result_total": 34,
            }
        )

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        page = gpu_handler.list_machines(
            client,
            charge_type="daily",
            region_signs=["bj-B1", "bj-B2"],
            gpu_types=["RTX 4090"],
            machine_tags=["tag-a"],
            gpu_idle_num=0,
            mount_net_disk=True,
            cpu_archs=["x86"],
            chip_corps=["nvidia"],
            machine_id="m1",
            date_range="custom",
            date_from="2026-11-01",
            date_to="2026-11-02",
            page_index=2,
            page_size=5,
        )

    assert seen == {
        "method": "POST",
        "path": "/api/v1/user/machine/list",
        "body": {
            "charge_type": "daily",
            "region_sign": "",
            "gpu_type_name": ["RTX 4090"],
            "machine_tag_name": ["tag-a"],
            "gpu_idle_num": 0,
            "mount_net_disk": True,
            "instance_disk_size_order": "",
            "pay_price_order": "",
            "gpu_idle_type": "",
            "date_range": "custom",
            "date_from": "2026-11-01",
            "date_to": "2026-11-02",
            "page_index": 2,
            "page_size": 5,
            "default_order": True,
            "region_sign_list": ["bj-B1", "bj-B2"],
            "cpu_arch": ["x86"],
            "chip_corp": ["nvidia"],
            "machine_id": "m1",
        },
    }
    assert page == {
        "machines": [NORMALIZED_MACHINE],
        "page_index": 2,
        "page_size": 5,
        "max_page": 7,
        "result_total": 34,
        "all_pages": False,
    }


@pytest.mark.parametrize(
    ("sort_field", "body_key"),
    [
        ("price", "pay_price_order"),
        ("idle", "gpu_idle_type"),
        ("disk", "instance_disk_size_order"),
    ],
)
def test_list_machines_maps_sort_field(sort_field: str, body_key: str) -> None:
    """Each sort field fills its own body key and clears the others."""
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return _success({"list": [], "max_page": 1, "result_total": 0})

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        gpu_handler.list_machines(client, sort_field=sort_field, sort_order="desc")

    body = seen["body"]
    assert isinstance(body, dict)
    sort_keys = ("pay_price_order", "gpu_idle_type", "instance_disk_size_order")
    assert {key: body[key] for key in sort_keys if key != body_key} == {key: "" for key in sort_keys if key != body_key}
    assert body[body_key] == "desc"
    assert body["default_order"] is False


def test_list_machines_sorts_price_locally_across_every_page() -> None:
    """A sort fetches every page and orders the complete result set."""
    requested: list[dict[str, object]] = []
    paged = {
        1: [_machine("m1", payg_price=300), _machine("m2", payg_price=100)],
        2: [_machine("m3", payg_price=200), _machine("m4", payg_price=50)],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requested.append(body)
        return _success({"list": paged[body["page_index"]], "max_page": 2, "result_total": 4})

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        page = gpu_handler.list_machines(client, sort_field="price", sort_order="asc")

    assert [body["page_index"] for body in requested] == [1, 2]
    assert all(body["page_size"] == gpu_handler.FULL_FETCH_PAGE_SIZE for body in requested)
    assert [machine["payg_price"] for machine in page["machines"]] == [0.05, 0.1, 0.2, 0.3]
    assert page["page_index"] == 1
    assert page["page_size"] == gpu_handler.DEFAULT_MACHINE_PAGE_SIZE
    assert page["max_page"] == 1
    assert page["result_total"] == 4


def test_list_machines_sorted_page_is_sliced_locally() -> None:
    """``page_index`` selects a page of the sorted result, not of the API's."""
    requested: list[int] = []
    paged = {
        1: [_machine("m1", payg_price=300), _machine("m2", payg_price=100)],
        2: [_machine("m3", payg_price=200), _machine("m4", payg_price=50)],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        page_index = json.loads(request.content)["page_index"]
        requested.append(page_index)
        return _success({"list": paged[page_index], "max_page": 2, "result_total": 4})

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        page = gpu_handler.list_machines(
            client,
            sort_field="price",
            sort_order="desc",
            page_index=2,
            page_size=2,
        )

    assert requested == [1, 2]
    assert [machine["payg_price"] for machine in page["machines"]] == [0.1, 0.05]
    assert page["page_index"] == 2
    assert page["page_size"] == 2
    assert page["max_page"] == 2
    assert page["result_total"] == 4


def test_list_machines_sorts_disk_locally() -> None:
    """Disk sorting is applied locally because the server ignores it."""
    requested: list[dict[str, object]] = []
    records = [
        _machine("m0", max_instance_disk_size=30),
        _machine("m1", max_instance_disk_size=10),
        _machine("m2", max_instance_disk_size=20),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(json.loads(request.content))
        return _success({"list": records, "max_page": 1, "result_total": 3})

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        page = gpu_handler.list_machines(client, sort_field="disk")

    assert [machine["max_instance_disk_size"] for machine in page["machines"]] == [10, 20, 30]
    assert requested[0]["page_size"] == gpu_handler.FULL_FETCH_PAGE_SIZE


@pytest.mark.parametrize("sort_field", [None, "idle"])
def test_list_machines_enforces_idle_minimum_locally(sort_field: str | None) -> None:
    """Fully used machines are dropped even though the server returns them."""
    records = [
        _machine("m0", gpu_idle_num=0),
        _machine("m1", gpu_idle_num=1),
        _machine("m2", gpu_idle_num=3),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return _success({"list": records, "max_page": 1, "result_total": 3})

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        page = gpu_handler.list_machines(client, gpu_idle_num=2, sort_field=sort_field)

    assert [machine["machine_id"] for machine in page["machines"]] == ["m2"]
    assert page["result_total"] == 1


def test_list_machines_sorts_idle_locally_across_every_page() -> None:
    """Idle sorting is local because the server order breaks after page one."""
    requested: list[dict[str, object]] = []
    paged = {
        1: [_machine("m1", gpu_idle_num=3), _machine("m2", gpu_idle_num=1)],
        2: [_machine("m3", gpu_idle_num=4), _machine("m4", gpu_idle_num=2)],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requested.append(body)
        return _success({"list": paged[body["page_index"]], "max_page": 2, "result_total": 4})

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        page = gpu_handler.list_machines(
            client,
            sort_field="idle",
            sort_order="desc",
            page_index=2,
            page_size=2,
        )

    assert [body["page_index"] for body in requested] == [1, 2]
    assert all(body["page_size"] == gpu_handler.FULL_FETCH_PAGE_SIZE for body in requested)
    assert [machine["gpu_idle_num"] for machine in page["machines"]] == [2, 1]
    assert page["page_index"] == 2
    assert page["page_size"] == 2
    assert page["max_page"] == 2
    assert page["result_total"] == 4


def test_list_machines_sorted_page_beyond_last_is_empty() -> None:
    """A page past the end of a locally sorted result is empty."""
    records = [_machine("m1", gpu_idle_num=2), _machine("m2", gpu_idle_num=1)]

    def handler(request: httpx.Request) -> httpx.Response:
        return _success({"list": records, "max_page": 1, "result_total": 2})

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        page = gpu_handler.list_machines(
            client,
            sort_field="idle",
            page_index=5,
            page_size=20,
        )

    assert page["machines"] == []
    assert page["max_page"] == 1
    assert page["result_total"] == 2


def test_list_machines_idle_sort_all_pages_sorts_locally() -> None:
    """``all_pages`` returns every machine of the locally sorted result."""
    requested: list[dict[str, object]] = []
    records = [
        _machine("m0", gpu_idle_num=3),
        _machine("m1", gpu_idle_num=1),
        _machine("m2", gpu_idle_num=2),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(json.loads(request.content))
        return _success({"list": records, "max_page": 1, "result_total": 3})

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        page = gpu_handler.list_machines(client, sort_field="idle", all_pages=True)

    assert [machine["gpu_idle_num"] for machine in page["machines"]] == [1, 2, 3]
    assert requested[0]["page_size"] == gpu_handler.FULL_FETCH_PAGE_SIZE


@pytest.mark.parametrize(
    ("sort_order", "expected"),
    [
        ("asc", [0.1, 0.2, None]),
        ("desc", [0.2, 0.1, None]),
    ],
)
def test_list_machines_sort_keeps_missing_values_last(
    sort_order: str,
    expected: list[float | None],
) -> None:
    """Machines without the sort field stay at the end in both directions."""
    records = [
        _machine("m1", payg_price=None, machine_sku_info=[]),
        _machine("m2", payg_price=100),
        _machine("m3", payg_price=200),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return _success({"list": records, "max_page": 1, "result_total": 3})

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        page = gpu_handler.list_machines(client, sort_field="price", sort_order=sort_order)

    assert [machine["payg_price"] for machine in page["machines"]] == expected


def test_list_machines_sorted_all_pages_returns_every_machine() -> None:
    """``all_pages`` with a sort returns the whole sorted set."""
    records = [_machine("m1", payg_price=300), _machine("m2", payg_price=100)]

    def handler(request: httpx.Request) -> httpx.Response:
        return _success({"list": records, "max_page": 1, "result_total": 2})

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        page = gpu_handler.list_machines(
            client,
            sort_field="price",
            page_size=1,
            all_pages=True,
        )

    assert [machine["payg_price"] for machine in page["machines"]] == [0.1, 0.3]
    assert page["page_index"] == 1
    assert page["page_size"] == 1
    assert page["max_page"] == 2
    assert page["result_total"] == 2
    assert page["all_pages"] is True


def test_list_machines_uses_default_order_without_sort() -> None:
    """No sort field leaves every ordering key empty and default order on."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _success({"list": [], "max_page": 1, "result_total": 0})

    seen: dict[str, object] = {}

    def recording_handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return handler(request)

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(recording_handler)) as client:
        gpu_handler.list_machines(client)

    body = seen["body"]
    assert isinstance(body, dict)
    assert body["default_order"] is True
    assert body["pay_price_order"] == ""
    assert body["gpu_idle_type"] == ""
    assert body["instance_disk_size_order"] == ""


def test_list_machines_fetches_every_page_when_asked() -> None:
    """``all_pages`` walks until ``max_page`` and concatenates the results."""
    requested: list[int] = []
    pages = {
        1: [_machine("m1")],
        2: [_machine("m2")],
        3: [_machine("m3")],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        page_index = json.loads(request.content)["page_index"]
        requested.append(page_index)
        return _success({"list": pages[page_index], "max_page": 3, "result_total": 3})

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        page = gpu_handler.list_machines(client, page_size=1, all_pages=True)

    assert requested == [1, 2, 3]
    assert [machine["machine_id"] for machine in page["machines"]] == ["m1", "m2", "m3"]
    assert page["page_index"] == 1
    assert page["page_size"] == 1
    assert page["max_page"] == 3
    assert page["result_total"] == 3
    assert page["all_pages"] is True


def test_list_machines_single_page_requests_only_that_page() -> None:
    """Without ``all_pages`` only the requested page is fetched."""
    requested: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(json.loads(request.content)["page_index"])
        return _success({"list": [_machine()], "max_page": 7, "result_total": 34})

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        page = gpu_handler.list_machines(client, page_index=2, page_size=5)

    assert requested == [2]
    assert page["page_index"] == 2
    assert page["max_page"] == 7
    assert page["all_pages"] is False


def test_list_machines_stops_on_empty_page_even_before_max_page() -> None:
    """An empty page ends the walk and the fetched count is reported."""
    requested: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page_index = json.loads(request.content)["page_index"]
        requested.append(page_index)
        entries = [_machine()] if page_index == 1 else []
        return _success({"list": entries, "max_page": 5, "result_total": 9})

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        page = gpu_handler.list_machines(client, all_pages=True)

    assert requested == [1, 2]
    assert len(page["machines"]) == 1
    assert page["max_page"] == 1
    assert page["result_total"] == 1


def test_list_machines_missing_max_page_stops_after_one_page() -> None:
    """Without a usable ``max_page`` the walk never loops forever."""
    requested: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(json.loads(request.content)["page_index"])
        return _success({"list": [_machine()], "result_total": 1})

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        page = gpu_handler.list_machines(client, all_pages=True)

    assert requested == [1]
    assert page["max_page"] == 1


@pytest.mark.parametrize(
    "entry",
    [
        "not-an-object",
        _machine(machine_id=""),
        _machine(machine_id=7),
        _machine(gpu_name=""),
        _machine(gpu_name=None),
        _machine(gpu_number="8"),
        _machine(gpu_number=True),
        _machine(gpu_idle_num=None),
        _machine(gpu_idle_num=False),
    ],
)
def test_list_machines_malformed_entry_raises_api_error(entry: object) -> None:
    """A missing or mistyped required field is rejected with a clear message."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _success({"list": [entry], "max_page": 1, "result_total": 1})

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(APIError, match="machine list returned malformed data"):
            gpu_handler.list_machines(client)


@pytest.mark.parametrize("data", [{"list": None}, {"list": "not-a-list"}, {"list": {}}])
def test_list_machines_malformed_list_raises_api_error(data: dict[str, object]) -> None:
    """A successful envelope without a list-valued ``list`` is malformed."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _success(data)

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(APIError, match="machine list returned malformed data"):
            gpu_handler.list_machines(client)


def test_list_machines_auth_failure_raises_auth_error() -> None:
    """An auth failure from the machine endpoint keeps its context."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"code": "TokenExpired", "msg": "please log in", "data": [], "request_id": "req-3"},
        )

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AuthError) as excinfo:
            gpu_handler.list_machines(client)

    assert "please log in" in str(excinfo.value)
    assert "req-3" in str(excinfo.value)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"page_index": 0},
        {"page_size": 0},
        {"page_size": gpu_handler.MAX_MACHINE_PAGE_SIZE + 1},
        {"sort_field": "name"},
        {"sort_order": "sideways"},
    ],
)
def test_list_machines_rejects_invalid_options_without_a_request(kwargs: dict[str, object]) -> None:
    """Invalid paging or sort options fail before any request is sent."""

    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("no request must be sent for invalid options")

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError):
            gpu_handler.list_machines(client, **kwargs)


def test_normalize_machine_collects_tags_and_sku_prices() -> None:
    """Tags are de-duplicated and SKU prices are flattened by billing mode."""
    machine = gpu_handler._normalize_machine(
        _machine(
            payg_price=None,
            machine_tag_info=["高配", {"name": "直连"}, {"tag_name": "高配"}, 7],
            machine_sku_info=[{"type": "payg", "current_price": 1234}, {"type": 3, "current_price": 1}],
        )
    )

    assert machine["machine_tags"] == ["高配", "直连"]
    assert machine["payg_price"] == 1.234
    assert machine["daily_price"] is None
