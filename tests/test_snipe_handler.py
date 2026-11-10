"""Tests for :mod:`autodl_cli.handlers.snipe`, all offline."""

from __future__ import annotations

import json
import threading

import httpx
import pytest

from autodl_cli.client import AutoDLClient
from autodl_cli.errors import APIError, AuthError
from autodl_cli.handlers import snipe as snipe_module

TOKEN = "fake-token"
BASE_IMAGE = "base-image-ee43618uo7"
PRIVATE_IMAGE = "image-abcd1234"
INSTANCE_UUID = "snipe-instance-1"
CLONE_SOURCE_UUID = "clone-source-1"
CLONE_NEW_UUID = "clone-instance-1"
REGION_LIST = [
    {
        "data_center": "westDC3",
        "region_sign": "west-B",
        "region_name": "西北B区",
        "visible": True,
        "used_for": "gpu",
    },
    {
        "data_center": "westDC3",
        "region_sign": "west-C",
        "region_name": "西北B区",
        "visible": True,
        "used_for": "gpu",
    },
]


def _success(data: object) -> httpx.Response:
    """Build a successful API envelope.

    :param data: The ``data`` value to wrap.
    :returns: A mock HTTP response.
    """
    return httpx.Response(200, json={"code": "Success", "msg": "", "data": data, "request_id": "req-1"})


def _failure(message: str) -> httpx.Response:
    """Build a non-success API envelope.

    :param message: Server error message.
    :returns: A mock HTTP response.
    """
    return httpx.Response(
        200,
        json={"code": "MachineNotEnoughGpu", "msg": message, "data": None, "request_id": "req-2"},
    )


def _machine(
    machine_id: str,
    *,
    gpu_name: str = "RTX 3090",
    idle: int = 2,
    price: int | None = 1480,
    alias: str = "worker",
) -> dict[str, object]:
    """Build a raw machine record the normaliser accepts.

    :param machine_id: Machine identifier.
    :param gpu_name: GPU model name.
    :param idle: Idle GPU count.
    :param price: Hourly price in thousandths of a yuan, or ``None``.
    :param alias: Display alias.
    :returns: A machine-record mapping.
    """
    record: dict[str, object] = {
        "machine_id": machine_id,
        "machine_name": machine_id,
        "machine_alias": alias,
        "region_name": "西北B区",
        "region_sign": "west-B",
        "gpu_name": gpu_name,
        "gpu_number": 8,
        "gpu_idle_num": idle,
    }
    if price is not None:
        record["payg_price"] = price
    return record


def _machine_page(machines: list[dict[str, object]]) -> dict[str, object]:
    """Build the ``data`` object of a machine-list response.

    :param machines: Machines on the page.
    :returns: A page mapping shaped like the real API response.
    """
    return {"list": machines, "page_index": 1, "max_page": 1, "result_total": len(machines)}


def _instance_page(entries: list[dict[str, object]]) -> dict[str, object]:
    """Build the ``data`` object of an instance-list response.

    :param entries: Instances on the page.
    :returns: A page mapping shaped like the real API response.
    """
    return {"list": entries, "page_index": 1, "max_page": 1, "result_total": len(entries)}


class _FakeClock:
    """Monotonic clock that advances only when a fake wait is recorded."""

    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        """Return the current fake time.

        :returns: Seconds since the fake origin.
        """
        return self.value

    def advance(self, seconds: float) -> None:
        """Move the clock forward.

        :param seconds: Delay to add.
        """
        self.value += seconds


@pytest.fixture
def fake_wait(monkeypatch) -> tuple[_FakeClock, list[float]]:
    """Replace sleeping and the clock so snipe tests run instantly.

    :param monkeypatch: pytest's monkeypatch fixture.
    :returns: The fake clock and the recorded wait arguments.
    """
    clock = _FakeClock()
    delays: list[float] = []

    def record(seconds: float) -> None:
        delays.append(seconds)
        clock.advance(seconds)

    monkeypatch.setattr(snipe_module, "_now", clock)
    monkeypatch.setattr(snipe_module, "wait", record)
    return clock, delays


def _select_all(machines: list[dict[str, object]], *, strategy: str) -> list[str]:
    """Repeatedly select from a shrinking list to reveal the full ranking.

    :param machines: Candidate machine mappings.
    :param strategy: Ordering strategy.
    :returns: Machine IDs in selection order.
    """
    remaining = list(machines)
    order: list[str] = []
    while True:
        chosen = snipe_module.select_machine(remaining, strategy=strategy)
        if chosen is None:
            return order
        order.append(str(chosen["machine_id"]))
        remaining = [machine for machine in remaining if machine is not chosen]


def test_select_machine_requires_enough_idle_cards() -> None:
    """Machines with fewer idle GPUs than requested are dropped."""
    machines = [
        {"machine_id": "m-1", "gpu_name": "RTX 3090", "gpu_idle_num": 1, "payg_price": 1.0},
        {"machine_id": "m-2", "gpu_name": "RTX 3090", "gpu_idle_num": 2, "payg_price": 1.0},
    ]

    assert snipe_module.select_machine(machines, gpu_amount=2) == machines[1]


def test_select_machine_matches_gpu_name_exactly_and_case_insensitively() -> None:
    """GPU names are stripped and case-folded, but never substring-matched."""
    machines = [
        {"machine_id": "m-exact", "gpu_name": "RTX 3090", "gpu_idle_num": 8, "payg_price": 1.0},
        {"machine_id": "m-ti", "gpu_name": "RTX 3090 Ti", "gpu_idle_num": 8, "payg_price": 1.0},
    ]

    chosen = snipe_module.select_machine(machines, gpu_types=(" rtx 3090 ",))
    assert chosen is not None
    assert chosen["machine_id"] == "m-exact"
    assert snipe_module.select_machine(machines[1:], gpu_types=("RTX 3090",)) is None


def test_select_machine_applies_max_price_and_excludes_missing_prices() -> None:
    """A price limit drops expensive machines and machines without a price."""
    machines = [
        {"machine_id": "m-cheap", "gpu_name": "RTX 3090", "gpu_idle_num": 8, "payg_price": 1.4},
        {"machine_id": "m-pricey", "gpu_name": "RTX 3090", "gpu_idle_num": 8, "payg_price": 1.6},
        {"machine_id": "m-unknown", "gpu_name": "RTX 3090", "gpu_idle_num": 8},
    ]

    assert snipe_module.select_machine(machines, max_price=1.5) == machines[0]


def test_select_machine_price_strategy_ordering() -> None:
    """``price`` sorts by price, then idle GPUs descending, then machine ID."""
    machines = [
        {"machine_id": "m-slow", "gpu_name": "RTX 3090", "gpu_idle_num": 8, "payg_price": 2.0},
        {"machine_id": "m-cheap", "gpu_name": "RTX 3090", "gpu_idle_num": 2, "payg_price": 1.0},
        {"machine_id": "m-cheap2", "gpu_name": "RTX 3090", "gpu_idle_num": 4, "payg_price": 1.0},
        {"machine_id": "m-aaa", "gpu_name": "RTX 3090", "gpu_idle_num": 4, "payg_price": 1.0},
        {"machine_id": "m-none", "gpu_name": "RTX 3090", "gpu_idle_num": 8},
    ]

    assert _select_all(machines, strategy="price") == [
        "m-aaa",
        "m-cheap2",
        "m-cheap",
        "m-slow",
        "m-none",
    ]


def test_select_machine_idle_strategy_ordering() -> None:
    """``idle`` sorts by idle GPUs descending, then price ascending, then ID."""
    machines = [
        {"machine_id": "m-a", "gpu_name": "RTX 3090", "gpu_idle_num": 4, "payg_price": 3.0},
        {"machine_id": "m-b", "gpu_name": "RTX 3090", "gpu_idle_num": 4, "payg_price": 1.0},
        {"machine_id": "m-aa", "gpu_name": "RTX 3090", "gpu_idle_num": 4, "payg_price": 1.0},
        {"machine_id": "m-c", "gpu_name": "RTX 3090", "gpu_idle_num": 8},
        {"machine_id": "m-d", "gpu_name": "RTX 3090", "gpu_idle_num": 8, "payg_price": 2.0},
    ]

    assert _select_all(machines, strategy="idle") == ["m-d", "m-c", "m-aa", "m-b", "m-a"]


def test_select_machine_first_strategy_keeps_input_order() -> None:
    """``first`` returns the first candidate without reordering."""
    machines = [
        {"machine_id": "m-expensive", "gpu_name": "RTX 3090", "gpu_idle_num": 2, "payg_price": 3.0},
        {"machine_id": "m-cheap", "gpu_name": "RTX 3090", "gpu_idle_num": 8, "payg_price": 1.0},
    ]

    assert _select_all(machines, strategy="first") == ["m-expensive", "m-cheap"]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"gpu_amount": 0}, "gpu_amount"),
        ({"gpu_amount": -1}, "gpu_amount"),
        ({"gpu_amount": True}, "gpu_amount"),
        ({"strategy": "cheapest"}, "strategy"),
        ({"max_price": -1}, "max_price"),
        ({"max_price": True}, "max_price"),
    ],
)
def test_select_machine_rejects_invalid_options(kwargs: dict[str, object], message: str) -> None:
    """Invalid ranking options raise before any machine is inspected."""
    with pytest.raises(ValueError, match=message):
        snipe_module.select_machine([], **kwargs)


def test_snipe_orders_after_an_empty_poll_and_waits_for_running(fake_wait) -> None:
    """An empty first poll waits, the next match is ordered, and running ends it."""
    _, delays = fake_wait
    machine_bodies: list[dict[str, object]] = []
    create_bodies: list[dict[str, object]] = []
    instance_bodies: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/v1/user/machine/list":
            machine_bodies.append(json.loads(request.content))
            machines = [] if len(machine_bodies) == 1 else [_machine("m-1")]
            return _success(_machine_page(machines))
        if path == "/api/v1/order/instance/create/payg":
            create_bodies.append(json.loads(request.content))
            return _success(INSTANCE_UUID)
        if path == "/api/v1/instance":
            instance_bodies.append(json.loads(request.content))
            status = "creating" if len(instance_bodies) == 1 else "running"
            return _success(_instance_page([{"uuid": INSTANCE_UUID, "status": status}]))
        pytest.fail(f"unexpected request {request.method} {path}")

    events: list[dict[str, object]] = []
    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        result = snipe_module.snipe(
            client,
            gpu_types=("RTX 3090",),
            base_image_uuid=BASE_IMAGE,
            instance_name="trainer",
            expand_data_disk=50,
            interval=5.0,
            on_event=events.append,
        )

    flat = {
        "instance_uuid": INSTANCE_UUID,
        "machine_id": "m-1",
        "machine_alias": "worker",
        "region_name": "西北B区",
        "region_sign": "west-B",
        "gpu_name": "RTX 3090",
        "gpu_idle_num": 2,
        "payg_price": 1.48,
        "gpu_amount": 1,
        "charge_type": "payg",
        "base_image_uuid": BASE_IMAGE,
        "private_image_uuid": "",
        "instance_name": "trainer",
        "expand_data_disk": 50,
        "status": "running",
    }
    assert result == {
        **flat,
        "instances": [flat],
        "released_instances": [],
        "release_failures": [],
        "count": 1,
        "parallel": 1,
        "attempts": 2,
        "elapsed_seconds": 10.0,
    }
    assert [event["event"] for event in events] == [
        "poll",
        "poll",
        "found",
        "ordered",
        "instance_status",
        "instance_status",
        "running",
    ]
    assert events[0]["matches"] == 0
    assert events[1]["matches"] == 1
    assert events[2]["machine"]["machine_id"] == "m-1"
    assert events[3]["instance_uuid"] == INSTANCE_UUID
    assert events[4]["status"] == "creating"
    assert events[5]["status"] == "running"
    assert delays == [5.0, 5.0]

    assert len(create_bodies) == 1
    info = create_bodies[0]["instance_info"]
    assert info["machine_id"] == "m-1"
    assert info["req_gpu_amount"] == 1
    assert info["base_image_uuid"] == BASE_IMAGE
    assert info["private_image_uuid"] == ""
    assert info["instance_name"] == "trainer"
    assert info["expand_data_disk"] == 50

    assert machine_bodies[0]["gpu_type_name"] == ["RTX 3090"]
    assert machine_bodies[0]["gpu_idle_num"] == 1
    assert machine_bodies[0]["charge_type"] == "payg"
    assert machine_bodies[0]["region_sign_list"] == []


def test_snipe_max_price_waits_for_a_cheaper_machine(fake_wait) -> None:
    """A machine above the price limit is ignored until a cheaper one appears."""
    machine_calls = 0
    created_machine_ids: list[object] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal machine_calls
        path = request.url.path
        if path == "/api/v1/user/machine/list":
            machine_calls += 1
            if machine_calls == 1:
                machines = [_machine("m-pricey", price=2000)]
            else:
                machines = [_machine("m-pricey", price=2000), _machine("m-cheap", price=1200)]
            return _success(_machine_page(machines))
        if path == "/api/v1/order/instance/create/payg":
            created_machine_ids.append(json.loads(request.content)["instance_info"]["machine_id"])
            return _success(INSTANCE_UUID)
        if path == "/api/v1/instance":
            return _success(_instance_page([{"uuid": INSTANCE_UUID, "status": "running"}]))
        pytest.fail(f"unexpected request {request.method} {path}")

    events: list[dict[str, object]] = []
    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        result = snipe_module.snipe(
            client,
            gpu_types=("RTX 3090",),
            max_price=1.5,
            base_image_uuid=BASE_IMAGE,
            interval=5.0,
            on_event=events.append,
        )

    assert result["machine_id"] == "m-cheap"
    assert result["payg_price"] == 1.2
    assert result["attempts"] == 2
    assert created_machine_ids == ["m-cheap"]
    assert [event["matches"] for event in events if event["event"] == "poll"] == [0, 1]


def test_snipe_retries_after_a_failed_order(fake_wait) -> None:
    """A rejected order cools the machine down, then the next poll retries it."""
    create_calls: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/v1/user/machine/list":
            return _success(_machine_page([_machine("m-1")]))
        if path == "/api/v1/order/instance/create/payg":
            create_calls.append(json.loads(request.content))
            if len(create_calls) == 1:
                return _failure("no capacity")
            return _success(INSTANCE_UUID)
        if path == "/api/v1/instance":
            return _success(_instance_page([{"uuid": INSTANCE_UUID, "status": "running"}]))
        pytest.fail(f"unexpected request {request.method} {path}")

    events: list[dict[str, object]] = []
    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        result = snipe_module.snipe(
            client,
            gpu_types=("RTX 3090",),
            base_image_uuid=BASE_IMAGE,
            interval=5.0,
            on_event=events.append,
        )

    assert [event["event"] for event in events] == [
        "poll",
        "found",
        "order_failed",
        "poll",
        "poll",
        "found",
        "ordered",
        "instance_status",
        "running",
    ]
    assert events[2]["machine_id"] == "m-1"
    assert events[2]["failures"] == 1
    assert events[2]["backoff"] == 5.0
    assert "no capacity" in str(events[2]["error"])
    assert events[3]["matches"] == 0
    assert events[3]["cooling"] == 1
    assert len(create_calls) == 2
    assert result["attempts"] == 3
    assert result["status"] == "running"


def test_snipe_tries_another_machine_while_the_failed_one_cools_down(fake_wait) -> None:
    """A rejected machine is skipped, so the next best candidate is ordered."""
    _, delays = fake_wait
    created_machine_ids: list[object] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/v1/user/machine/list":
            machines = [_machine("m-cheap", price=1000), _machine("m-other", price=2000)]
            return _success(_machine_page(machines))
        if path == "/api/v1/order/instance/create/payg":
            machine_id = json.loads(request.content)["instance_info"]["machine_id"]
            created_machine_ids.append(machine_id)
            if machine_id == "m-cheap":
                return _failure("当前主机存储库存已满")
            return _success(INSTANCE_UUID)
        if path == "/api/v1/instance":
            return _success(_instance_page([{"uuid": INSTANCE_UUID, "status": "running"}]))
        pytest.fail(f"unexpected request {request.method} {path}")

    events: list[dict[str, object]] = []
    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        result = snipe_module.snipe(
            client,
            gpu_types=("RTX 3090",),
            base_image_uuid=BASE_IMAGE,
            interval=5.0,
            on_event=events.append,
        )

    assert created_machine_ids == ["m-cheap", "m-other"]
    assert result["machine_id"] == "m-other"
    assert result["attempts"] == 2
    assert result["status"] == "running"
    polls = [event for event in events if event["event"] == "poll"]
    assert [poll["matches"] for poll in polls] == [2, 1]
    assert [poll["cooling"] for poll in polls] == [0, 1]
    assert delays == []


def test_snipe_backs_off_exponentially_for_a_machine_that_keeps_failing(fake_wait) -> None:
    """Consecutive rejections double the cooldown before the machine is retried."""
    _, delays = fake_wait
    create_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal create_calls
        path = request.url.path
        if path == "/api/v1/user/machine/list":
            return _success(_machine_page([_machine("m-1")]))
        if path == "/api/v1/order/instance/create/payg":
            create_calls += 1
            if create_calls <= 2:
                return _failure("no capacity")
            return _success(INSTANCE_UUID)
        if path == "/api/v1/instance":
            return _success(_instance_page([{"uuid": INSTANCE_UUID, "status": "running"}]))
        pytest.fail(f"unexpected request {request.method} {path}")

    events: list[dict[str, object]] = []
    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        result = snipe_module.snipe(
            client,
            gpu_types=("RTX 3090",),
            base_image_uuid=BASE_IMAGE,
            interval=5.0,
            on_event=events.append,
        )

    failed = [event for event in events if event["event"] == "order_failed"]
    assert [event["failures"] for event in failed] == [1, 2]
    assert [event["backoff"] for event in failed] == [5.0, 10.0]
    assert create_calls == 3
    assert result["attempts"] == 6
    assert result["status"] == "running"
    assert delays == [5.0, 5.0, 5.0]


@pytest.mark.parametrize(
    ("failures", "expected"),
    [(1, 5.0), (2, 10.0), (3, 20.0), (4, 40.0), (5, 40.0), (100, 40.0)],
)
def test_order_backoff_doubles_up_to_the_cap(failures: int, expected: float) -> None:
    """The cooldown starts at one interval, doubles, and stops at eight intervals."""
    assert snipe_module._order_backoff(5.0, failures) == expected


def test_snipe_times_out_before_ordering(fake_wait) -> None:
    """An empty stock list raises :class:`TimeoutError` once the deadline passes."""
    _, delays = fake_wait

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/user/machine/list":
            return _success(_machine_page([]))
        pytest.fail(f"unexpected request {request.method} {request.url.path}")

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(TimeoutError, match="Timed out after 5s without ordering an instance"):
            snipe_module.snipe(
                client,
                gpu_types=("RTX 3090",),
                base_image_uuid=BASE_IMAGE,
                interval=2.0,
                timeout=5.0,
            )

    assert delays == [2.0, 2.0, 2.0]


def test_snipe_times_out_while_waiting_for_running(fake_wait) -> None:
    """An instance that never starts raises a timeout mentioning its last status."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/v1/user/machine/list":
            return _success(_machine_page([_machine("m-1")]))
        if path == "/api/v1/order/instance/create/payg":
            return _success(INSTANCE_UUID)
        if path == "/api/v1/instance":
            return _success(_instance_page([{"uuid": INSTANCE_UUID, "status": "creating"}]))
        pytest.fail(f"unexpected request {request.method} {path}")

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(TimeoutError, match="last status") as excinfo:
            snipe_module.snipe(
                client,
                gpu_types=("RTX 3090",),
                base_image_uuid=BASE_IMAGE,
                interval=2.0,
                timeout=5.0,
            )

    assert "creating" in str(excinfo.value)


def test_snipe_raises_when_the_instance_fails(fake_wait) -> None:
    """A failed instance status becomes an :class:`APIError`."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/v1/user/machine/list":
            return _success(_machine_page([_machine("m-1")]))
        if path == "/api/v1/order/instance/create/payg":
            return _success(INSTANCE_UUID)
        if path == "/api/v1/instance":
            return _success(_instance_page([{"uuid": INSTANCE_UUID, "status": "failed"}]))
        pytest.fail(f"unexpected request {request.method} {path}")

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(APIError, match="entered status 'failed'"):
            snipe_module.snipe(
                client,
                gpu_types=("RTX 3090",),
                base_image_uuid=BASE_IMAGE,
            )


def test_snipe_resolves_a_region_once_and_forwards_its_signs(fake_wait) -> None:
    """The region catalogue is read once and every poll carries its signs."""
    common_calls: list[str] = []
    machine_bodies: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/v1/common":
            common_calls.append(path)
            return _success({"region_list": REGION_LIST})
        if path == "/api/v1/user/machine/list":
            machine_bodies.append(json.loads(request.content))
            machines = [] if len(machine_bodies) == 1 else [_machine("m-1")]
            return _success(_machine_page(machines))
        if path == "/api/v1/order/instance/create/payg":
            return _success(INSTANCE_UUID)
        if path == "/api/v1/instance":
            return _success(_instance_page([{"uuid": INSTANCE_UUID, "status": "running"}]))
        pytest.fail(f"unexpected request {request.method} {path}")

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        result = snipe_module.snipe(
            client,
            regions=(" 西北B区 ",),
            base_image_uuid=BASE_IMAGE,
            interval=5.0,
        )

    assert result["machine_id"] == "m-1"
    assert common_calls == ["/api/v1/common"]
    assert [body["region_sign_list"] for body in machine_bodies] == [
        ["west-B", "west-C"],
        ["west-B", "west-C"],
    ]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"max_price": 1.5, "base_image_uuid": BASE_IMAGE}, "at least one of region and gpu"),
        ({"gpu_amount": 2, "base_image_uuid": BASE_IMAGE}, "at least one of region and gpu"),
        (
            {"gpu_types": ("RTX 3090",), "base_image_uuid": BASE_IMAGE, "private_image_uuid": PRIVATE_IMAGE},
            "exactly one",
        ),
        ({"gpu_types": ("RTX 3090",)}, "exactly one"),
        ({"gpu_types": ("RTX 3090",), "base_image_uuid": BASE_IMAGE, "interval": 0}, "interval"),
        (
            {"gpu_types": ("RTX 3090",), "base_image_uuid": BASE_IMAGE, "timeout": -1},
            "timeout",
        ),
        ({"regions": ("  ",), "base_image_uuid": BASE_IMAGE}, "regions"),
        ({"gpu_types": ("  ",), "base_image_uuid": BASE_IMAGE}, "gpu_types"),
        ({"gpu_types": ("RTX 3090",), "base_image_uuid": BASE_IMAGE, "strategy": "cheapest"}, "strategy"),
        ({"gpu_types": ("RTX 3090",), "base_image_uuid": BASE_IMAGE, "retry": -1}, "retry"),
        ({"gpu_types": ("RTX 3090",), "base_image_uuid": BASE_IMAGE, "retry": True}, "retry"),
        ({"gpu_types": ("RTX 3090",), "base_image_uuid": BASE_IMAGE, "parallel": 0}, "parallel"),
        ({"gpu_types": ("RTX 3090",), "base_image_uuid": BASE_IMAGE, "parallel": True}, "parallel"),
        ({"gpu_types": ("RTX 3090",), "base_image_uuid": BASE_IMAGE, "count": 0}, "count"),
        ({"gpu_types": ("RTX 3090",), "base_image_uuid": BASE_IMAGE, "count": True}, "count"),
    ],
)
def test_snipe_rejects_invalid_options_before_any_request(
    kwargs: dict[str, object],
    message: str,
) -> None:
    """Invalid arguments fail before the client sends a request."""

    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("no request must be sent for invalid options")

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match=message):
            snipe_module.snipe(client, **kwargs)


def test_snipe_retries_a_transient_machine_list_error(fake_wait) -> None:
    """A 429 on the stock poll is retried and the run still succeeds."""
    _, delays = fake_wait
    machine_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal machine_calls
        path = request.url.path
        if path == "/api/v1/user/machine/list":
            machine_calls += 1
            if machine_calls == 1:
                return httpx.Response(429, json={"msg": "slow down"})
            return _success(_machine_page([_machine("m-1")]))
        if path == "/api/v1/order/instance/create/payg":
            return _success(INSTANCE_UUID)
        if path == "/api/v1/instance":
            return _success(_instance_page([{"uuid": INSTANCE_UUID, "status": "running"}]))
        pytest.fail(f"unexpected request {request.method} {path}")

    events: list[dict[str, object]] = []
    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        result = snipe_module.snipe(
            client,
            gpu_types=("RTX 3090",),
            base_image_uuid=BASE_IMAGE,
            interval=2.0,
            retry=1,
            on_event=events.append,
        )

    assert result["instance_uuid"] == INSTANCE_UUID
    assert machine_calls == 2
    assert events[0]["event"] == "poll_failed"
    assert events[0]["retries"] == 1
    assert events[0]["limit"] == 1
    assert "429" in str(events[0]["error"])
    assert [event["event"] for event in events[1:]] == [
        "poll",
        "found",
        "ordered",
        "instance_status",
        "running",
    ]
    assert delays == [2.0]


def test_snipe_zero_retries_propagates_the_first_polling_error(fake_wait) -> None:
    """``retry=0`` keeps the original fail-fast behaviour."""
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/user/machine/list":
            calls.append(1)
            return httpx.Response(500, json={"msg": "boom"})
        pytest.fail(f"unexpected request {request.method} {request.url.path}")

    events: list[dict[str, object]] = []
    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(APIError, match="boom"):
            snipe_module.snipe(
                client,
                gpu_types=("RTX 3090",),
                base_image_uuid=BASE_IMAGE,
                interval=2.0,
                retry=0,
                on_event=events.append,
            )

    assert calls == [1]
    assert events == []


def test_snipe_reraises_after_consecutive_retries_are_exhausted(fake_wait) -> None:
    """Two consecutive failures with ``retry=1`` re-raise without a second event."""
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/user/machine/list":
            calls.append(1)
            return httpx.Response(500, json={"msg": "boom"})
        pytest.fail(f"unexpected request {request.method} {request.url.path}")

    events: list[dict[str, object]] = []
    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(APIError, match="boom"):
            snipe_module.snipe(
                client,
                gpu_types=("RTX 3090",),
                base_image_uuid=BASE_IMAGE,
                interval=2.0,
                retry=1,
                on_event=events.append,
            )

    assert len(calls) == 2
    failures = [event for event in events if event["event"] == "poll_failed"]
    assert len(failures) == 1
    assert failures[0]["retries"] == 1


def test_snipe_retries_a_transient_instance_list_error(fake_wait) -> None:
    """A failure while waiting for running is retried and the run succeeds."""
    _, delays = fake_wait
    instance_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal instance_calls
        path = request.url.path
        if path == "/api/v1/user/machine/list":
            return _success(_machine_page([_machine("m-1")]))
        if path == "/api/v1/order/instance/create/payg":
            return _success(INSTANCE_UUID)
        if path == "/api/v1/instance":
            instance_calls += 1
            if instance_calls == 1:
                return httpx.Response(500, json={"msg": "temporary"})
            return _success(_instance_page([{"uuid": INSTANCE_UUID, "status": "running"}]))
        pytest.fail(f"unexpected request {request.method} {path}")

    events: list[dict[str, object]] = []
    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        result = snipe_module.snipe(
            client,
            gpu_types=("RTX 3090",),
            base_image_uuid=BASE_IMAGE,
            interval=3.0,
            retry=1,
            on_event=events.append,
        )

    assert result["status"] == "running"
    assert instance_calls == 2
    assert any(event["event"] == "poll_failed" and event["limit"] == 1 for event in events)
    assert [event["event"] for event in events] == [
        "poll",
        "found",
        "ordered",
        "poll_failed",
        "instance_status",
        "running",
    ]
    assert delays == [3.0]


def test_snipe_never_retries_auth_errors(fake_wait) -> None:
    """A 401 propagates immediately even when retries are enabled."""
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/user/machine/list":
            calls.append(1)
            return httpx.Response(401, json={"msg": "bad token"})
        pytest.fail(f"unexpected request {request.method} {request.url.path}")

    events: list[dict[str, object]] = []
    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AuthError, match="bad token"):
            snipe_module.snipe(
                client,
                gpu_types=("RTX 3090",),
                base_image_uuid=BASE_IMAGE,
                interval=2.0,
                retry=3,
                on_event=events.append,
            )

    assert calls == [1]
    assert events == []


def _instance_entries(*machine_ids: str) -> list[dict[str, object]]:
    """Build running instance-list entries for the given machine IDs.

    :param machine_ids: Machine identifiers whose orders succeeded.
    :returns: One running entry per machine.
    """
    return [{"uuid": f"inst-{machine_id}", "status": "running"} for machine_id in machine_ids]


def test_snipe_parallel_keeps_the_best_and_releases_extras(fake_wait) -> None:
    """``parallel=3`` with one needed instance keeps the top rank and releases two extras."""
    lock = threading.Lock()
    lifecycle_calls: list[tuple[str, str]] = []
    machines = [
        _machine("m-a", price=1000),
        _machine("m-b", price=2000),
        _machine("m-c", price=3000),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/v1/user/machine/list":
            return _success(_machine_page(machines))
        if path == "/api/v1/order/instance/create/payg":
            machine_id = json.loads(request.content)["instance_info"]["machine_id"]
            return _success(f"inst-{machine_id}")
        if path == "/api/v1/instance/power_off":
            instance_uuid = json.loads(request.content)["instance_uuid"]
            with lock:
                lifecycle_calls.append(("power_off", instance_uuid))
            return _success(None)
        if path == "/api/v1/instance/release":
            instance_uuid = json.loads(request.content)["instance_uuid"]
            with lock:
                lifecycle_calls.append(("release", instance_uuid))
            return _success(None)
        if path == "/api/v1/instance":
            return _success(_instance_page(_instance_entries("m-a")))
        pytest.fail(f"unexpected request {request.method} {path}")

    events: list[dict[str, object]] = []
    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        result = snipe_module.snipe(
            client,
            gpu_types=("RTX 3090",),
            base_image_uuid=BASE_IMAGE,
            parallel=3,
            interval=5.0,
            on_event=events.append,
        )

    assert result["attempts"] == 1
    assert [record["instance_uuid"] for record in result["instances"]] == ["inst-m-a"]
    assert [record["instance_uuid"] for record in result["released_instances"]] == ["inst-m-b", "inst-m-c"]
    assert [record["status"] for record in result["released_instances"]] == ["released", "released"]
    assert result["release_failures"] == []
    assert lifecycle_calls == [
        ("power_off", "inst-m-b"),
        ("release", "inst-m-b"),
        ("power_off", "inst-m-c"),
        ("release", "inst-m-c"),
    ]

    kept_events = [event for event in events if event["event"] == "ordered" and not event.get("extra")]
    assert [event["instance_uuid"] for event in kept_events] == ["inst-m-a"]
    extra_events = [event for event in events if event["event"] == "ordered" and event.get("extra")]
    assert [event["instance_uuid"] for event in extra_events] == ["inst-m-b", "inst-m-c"]
    assert [(event["event"], event["instance_uuid"]) for event in events if event["event"] == "releasing_extra"] == [
        ("releasing_extra", "inst-m-b"),
        ("releasing_extra", "inst-m-c"),
    ]
    assert [event["instance_uuid"] for event in events if event["event"] == "extra_released"] == [
        "inst-m-b",
        "inst-m-c",
    ]


def test_snipe_parallel_keeps_count_instances_and_releases_one_extra(fake_wait) -> None:
    """``count=2`` keeps two ranked successes, releases the third, and waits for both."""
    lock = threading.Lock()
    lifecycle_calls: list[tuple[str, str]] = []
    machines = [
        _machine("m-a", price=1000),
        _machine("m-b", price=2000),
        _machine("m-c", price=3000),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/v1/user/machine/list":
            return _success(_machine_page(machines))
        if path == "/api/v1/order/instance/create/payg":
            machine_id = json.loads(request.content)["instance_info"]["machine_id"]
            return _success(f"inst-{machine_id}")
        if path == "/api/v1/instance/power_off":
            with lock:
                lifecycle_calls.append(("power_off", json.loads(request.content)["instance_uuid"]))
            return _success(None)
        if path == "/api/v1/instance/release":
            with lock:
                lifecycle_calls.append(("release", json.loads(request.content)["instance_uuid"]))
            return _success(None)
        if path == "/api/v1/instance":
            return _success(_instance_page(_instance_entries("m-a", "m-b", "m-c")))
        pytest.fail(f"unexpected request {request.method} {path}")

    events: list[dict[str, object]] = []
    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        result = snipe_module.snipe(
            client,
            gpu_types=("RTX 3090",),
            base_image_uuid=BASE_IMAGE,
            parallel=3,
            count=2,
            interval=5.0,
            on_event=events.append,
        )

    assert result["count"] == 2
    assert [record["instance_uuid"] for record in result["instances"]] == ["inst-m-a", "inst-m-b"]
    assert [record["instance_uuid"] for record in result["released_instances"]] == ["inst-m-c"]
    assert lifecycle_calls == [("power_off", "inst-m-c"), ("release", "inst-m-c")]
    assert [event["instance_uuid"] for event in events if event["event"] == "running"] == [
        "inst-m-a",
        "inst-m-b",
    ]


def test_snipe_parallel_keeps_a_success_when_a_sibling_order_fails(fake_wait) -> None:
    """A rejected machine cools down while the successful sibling order is kept."""
    machines = [_machine("m-cheap", price=1000), _machine("m-other", price=2000)]

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/v1/user/machine/list":
            return _success(_machine_page(machines))
        if path == "/api/v1/order/instance/create/payg":
            machine_id = json.loads(request.content)["instance_info"]["machine_id"]
            if machine_id == "m-cheap":
                return _failure("no capacity")
            return _success("inst-m-other")
        if path == "/api/v1/instance":
            return _success(_instance_page(_instance_entries("m-other")))
        if path == "/api/v1/instance/power_off" or path == "/api/v1/instance/release":
            pytest.fail("no surplus orders were placed")
        pytest.fail(f"unexpected request {request.method} {path}")

    events: list[dict[str, object]] = []
    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        result = snipe_module.snipe(
            client,
            gpu_types=("RTX 3090",),
            base_image_uuid=BASE_IMAGE,
            parallel=2,
            interval=5.0,
            on_event=events.append,
        )

    assert result["attempts"] == 1
    assert result["instance_uuid"] == "inst-m-other"
    failed = [event for event in events if event["event"] == "order_failed"]
    assert len(failed) == 1
    assert failed[0]["machine_id"] == "m-cheap"
    assert failed[0]["failures"] == 1
    assert failed[0]["backoff"] == 5.0
    assert not any(event["event"] == "releasing_extra" for event in events)


def test_snipe_parallel_retries_after_a_fully_failed_round(fake_wait) -> None:
    """When every order in a round fails, the cooldowns expire and the next round succeeds."""
    _, delays = fake_wait
    lock = threading.Lock()
    create_calls = 0
    machines = [_machine("m-1", price=1000), _machine("m-2", price=2000)]

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal create_calls
        path = request.url.path
        if path == "/api/v1/user/machine/list":
            return _success(_machine_page(machines))
        if path == "/api/v1/order/instance/create/payg":
            machine_id = json.loads(request.content)["instance_info"]["machine_id"]
            with lock:
                create_calls += 1
                attempt = create_calls
            if attempt <= 2:
                return _failure("no capacity")
            return _success(f"inst-{machine_id}")
        if path == "/api/v1/instance":
            return _success(_instance_page(_instance_entries("m-1", "m-2")))
        pytest.fail(f"unexpected request {request.method} {path}")

    events: list[dict[str, object]] = []
    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        result = snipe_module.snipe(
            client,
            gpu_types=("RTX 3090",),
            base_image_uuid=BASE_IMAGE,
            parallel=2,
            count=2,
            interval=5.0,
            on_event=events.append,
        )

    assert create_calls == 4
    assert result["attempts"] == 3
    assert [record["instance_uuid"] for record in result["instances"]] == ["inst-m-1", "inst-m-2"]
    failed = [event for event in events if event["event"] == "order_failed"]
    assert sorted((event["machine_id"], event["failures"], event["backoff"]) for event in failed) == [
        ("m-1", 1, 5.0),
        ("m-2", 1, 5.0),
    ]
    polls = [event for event in events if event["event"] == "poll"]
    assert [poll["cooling"] for poll in polls] == [0, 2, 0]
    assert delays == [5.0]


def test_snipe_releases_an_extra_even_when_power_off_fails(fake_wait) -> None:
    """A failed power-off is reported, but the surplus instance is still released."""
    lock = threading.Lock()
    released: list[str] = []
    machines = [_machine("m-a", price=1000), _machine("m-b", price=2000)]

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/v1/user/machine/list":
            return _success(_machine_page(machines))
        if path == "/api/v1/order/instance/create/payg":
            machine_id = json.loads(request.content)["instance_info"]["machine_id"]
            return _success(f"inst-{machine_id}")
        if path == "/api/v1/instance/power_off":
            return _failure("power off refused")
        if path == "/api/v1/instance/release":
            with lock:
                released.append(json.loads(request.content)["instance_uuid"])
            return _success(None)
        if path == "/api/v1/instance":
            return _success(_instance_page(_instance_entries("m-a")))
        pytest.fail(f"unexpected request {request.method} {path}")

    events: list[dict[str, object]] = []
    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        result = snipe_module.snipe(
            client,
            gpu_types=("RTX 3090",),
            base_image_uuid=BASE_IMAGE,
            parallel=2,
            interval=5.0,
            on_event=events.append,
        )

    power_off_failures = [event for event in events if event["event"] == "extra_power_off_failed"]
    assert len(power_off_failures) == 1
    assert power_off_failures[0]["instance_uuid"] == "inst-m-b"
    assert "power off refused" in str(power_off_failures[0]["error"])
    assert released == ["inst-m-b"]
    assert [record["instance_uuid"] for record in result["released_instances"]] == ["inst-m-b"]
    assert result["release_failures"] == []


def test_snipe_retries_a_failed_extra_release_and_reports_it(fake_wait) -> None:
    """A surplus release is retried, then reported without aborting the run."""
    _, delays = fake_wait
    lock = threading.Lock()
    release_calls = 0
    machines = [_machine("m-a", price=1000), _machine("m-b", price=2000)]

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal release_calls
        path = request.url.path
        if path == "/api/v1/user/machine/list":
            return _success(_machine_page(machines))
        if path == "/api/v1/order/instance/create/payg":
            machine_id = json.loads(request.content)["instance_info"]["machine_id"]
            return _success(f"inst-{machine_id}")
        if path == "/api/v1/instance/power_off":
            return _success(None)
        if path == "/api/v1/instance/release":
            with lock:
                release_calls += 1
            return _failure("release denied")
        if path == "/api/v1/instance":
            return _success(_instance_page(_instance_entries("m-a")))
        pytest.fail(f"unexpected request {request.method} {path}")

    events: list[dict[str, object]] = []
    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        result = snipe_module.snipe(
            client,
            gpu_types=("RTX 3090",),
            base_image_uuid=BASE_IMAGE,
            parallel=2,
            interval=5.0,
            on_event=events.append,
        )

    assert release_calls == snipe_module.EXTRA_RELEASE_ATTEMPTS
    assert result["released_instances"] == []
    assert len(result["release_failures"]) == 1
    assert result["release_failures"][0]["instance_uuid"] == "inst-m-b"
    assert "release denied" in str(result["release_failures"][0]["error"])
    failed = [event for event in events if event["event"] == "extra_release_failed"]
    assert len(failed) == 1
    assert failed[0]["instance_uuid"] == "inst-m-b"
    assert result["status"] == "running"
    assert delays == [5.0, 5.0]


def test_snipe_parallel_order_auth_error_propagates(fake_wait) -> None:
    """An authentication failure from a concurrent order aborts the run."""
    machines = [_machine("m-1", price=1000), _machine("m-2", price=2000)]

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/v1/user/machine/list":
            return _success(_machine_page(machines))
        if path == "/api/v1/order/instance/create/payg":
            return httpx.Response(401, json={"msg": "bad token"})
        pytest.fail(f"unexpected request {request.method} {path}")

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AuthError, match="bad token"):
            snipe_module.snipe(
                client,
                gpu_types=("RTX 3090",),
                base_image_uuid=BASE_IMAGE,
                parallel=2,
                interval=5.0,
            )


def _clone_snapshot(base_image_uuid: str = BASE_IMAGE, image_type: str = "public") -> dict[str, object]:
    """Build a source-instance snapshot for clone resolution.

    :param base_image_uuid: Image UUID stored on the source instance.
    :param image_type: Image type reported by AutoDL.
    :returns: A snapshot mapping shaped like the real API response.
    """
    return {"image": {"base_image_uuid": base_image_uuid, "image_type": image_type}}


def test_snipe_clone_inherits_the_image_and_skips_the_instance_list(fake_wait) -> None:
    """Clone mode resolves the source image and orders clones without listing instances."""
    requests: list[tuple[str, str]] = []
    clone_bodies: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        requests.append((request.method, path))
        if path == "/api/v1/instance/snapshot":
            return _success(_clone_snapshot())
        if path == "/api/v1/user/machine/list":
            return _success(_machine_page([_machine("m-1")]))
        if path == "/api/v1/order/instance/clone/payg":
            clone_bodies.append(json.loads(request.content))
            return _success(CLONE_NEW_UUID)
        if path == "/api/v1/instance":
            return _success(_instance_page([{"uuid": CLONE_NEW_UUID, "status": "running"}]))
        pytest.fail(f"unexpected request {request.method} {path}")

    events: list[dict[str, object]] = []
    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        result = snipe_module.snipe(
            client,
            gpu_types=("RTX 3090",),
            clone_instance_uuid=f" {CLONE_SOURCE_UUID} ",
            instance_name="clone-name",
            expand_data_disk=20,
            interval=5.0,
            on_event=events.append,
        )

    assert len(clone_bodies) == 1
    body = clone_bodies[0]
    assert body["instance_uuid"] == CLONE_SOURCE_UUID
    info = body["instance_info"]
    assert info["machine_id"] == "m-1"
    assert info["base_image_uuid"] == BASE_IMAGE
    assert info["private_image_uuid"] == ""
    assert info["req_gpu_amount"] == 1
    assert info["instance_name"] == "clone-name"
    assert info["expand_data_disk"] == 20
    assert info["copy_data_disk_after_clone"] is True
    assert info["keep_src_user_service_address_after_clone"] is False

    # Clone resolution reads the snapshot, never the instance list: the only
    # instance-list POST is the status poll after the clone order.
    clone_index = next(
        index
        for index, (method, path) in enumerate(requests)
        if method == "POST" and path == "/api/v1/order/instance/clone/payg"
    )
    snapshot_index = next(
        index
        for index, (method, path) in enumerate(requests)
        if method == "GET" and path == "/api/v1/instance/snapshot"
    )
    instance_posts = [
        index for index, (method, path) in enumerate(requests) if method == "POST" and path == "/api/v1/instance"
    ]
    assert snapshot_index < clone_index
    assert instance_posts == [clone_index + 1]

    found = [event for event in events if event["event"] == "found"]
    assert len(found) == 1
    assert found[0]["clone"] is True

    assert result["instance_uuid"] == CLONE_NEW_UUID
    assert result["source_instance_uuid"] == CLONE_SOURCE_UUID
    assert result["gpu_amount"] == 1
    assert result["base_image_uuid"] == BASE_IMAGE
    assert result["instances"][0]["source_instance_uuid"] == CLONE_SOURCE_UUID


def test_snipe_clone_forwards_gpu_and_copy_flags(fake_wait) -> None:
    """Clone mode forwards its own GPU count, flags, name, and disk size."""
    clone_bodies: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/v1/instance/snapshot":
            return _success(_clone_snapshot())
        if path == "/api/v1/user/machine/list":
            return _success(_machine_page([_machine("m-1")]))
        if path == "/api/v1/order/instance/clone/payg":
            clone_bodies.append(json.loads(request.content))
            return _success(CLONE_NEW_UUID)
        if path == "/api/v1/instance":
            return _success(_instance_page([{"uuid": CLONE_NEW_UUID, "status": "running"}]))
        pytest.fail(f"unexpected request {request.method} {path}")

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        result = snipe_module.snipe(
            client,
            gpu_types=("RTX 3090",),
            clone_instance_uuid=CLONE_SOURCE_UUID,
            gpu_amount=2,
            instance_name=" copy ",
            expand_data_disk=30,
            copy_data_disk=False,
            keep_src_user_service_address=True,
            interval=5.0,
        )

    info = clone_bodies[0]["instance_info"]
    assert info["req_gpu_amount"] == 2
    assert info["instance_name"] == "copy"
    assert info["expand_data_disk"] == 30
    assert info["copy_data_disk_after_clone"] is False
    assert info["keep_src_user_service_address_after_clone"] is True
    assert result["gpu_amount"] == 2
    assert result["source_instance_uuid"] == CLONE_SOURCE_UUID


def test_snipe_clone_private_image_sends_private_uuid(fake_wait) -> None:
    """A private source image is sent as ``private_image_uuid`` with a blank base image."""
    clone_bodies: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/v1/instance/snapshot":
            return _success(_clone_snapshot(PRIVATE_IMAGE, "private"))
        if path == "/api/v1/user/machine/list":
            return _success(_machine_page([_machine("m-1")]))
        if path == "/api/v1/order/instance/clone/payg":
            clone_bodies.append(json.loads(request.content))
            return _success(CLONE_NEW_UUID)
        if path == "/api/v1/instance":
            return _success(_instance_page([{"uuid": CLONE_NEW_UUID, "status": "running"}]))
        pytest.fail(f"unexpected request {request.method} {path}")

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        snipe_module.snipe(
            client,
            gpu_types=("RTX 3090",),
            clone_instance_uuid=CLONE_SOURCE_UUID,
            interval=5.0,
        )

    info = clone_bodies[0]["instance_info"]
    assert info["base_image_uuid"] == ""
    assert info["private_image_uuid"] == PRIVATE_IMAGE


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        (
            {"gpu_types": ("RTX 3090",), "clone_instance_uuid": CLONE_SOURCE_UUID, "base_image_uuid": BASE_IMAGE},
            "cannot be combined",
        ),
        (
            {"gpu_types": ("RTX 3090",), "clone_instance_uuid": CLONE_SOURCE_UUID, "private_image_uuid": PRIVATE_IMAGE},
            "cannot be combined",
        ),
        ({"gpu_types": ("RTX 3090",)}, "exactly one"),
    ],
)
def test_snipe_clone_rejects_conflicting_or_missing_images(kwargs: dict[str, object], message: str) -> None:
    """Clone mode and image UUIDs are mutually exclusive, and an image is still required otherwise."""

    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("no request must be sent for invalid options")

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match=message):
            snipe_module.snipe(client, **kwargs)


def test_snipe_clone_propagates_a_snapshot_auth_error(fake_wait) -> None:
    """Authentication failures from clone resolution propagate before polling starts."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/api/v1/instance/snapshot":
            return httpx.Response(401, json={"msg": "bad token"})
        pytest.fail(f"unexpected request {request.method} {request.url.path}")

    events: list[dict[str, object]] = []
    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AuthError, match="bad token"):
            snipe_module.snipe(
                client,
                gpu_types=("RTX 3090",),
                clone_instance_uuid=CLONE_SOURCE_UUID,
                interval=2.0,
                retry=3,
                on_event=events.append,
            )

    assert calls == ["/api/v1/instance/snapshot"]
    assert events == []
