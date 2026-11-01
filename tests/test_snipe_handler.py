"""Tests for :mod:`autodl_cli.handlers.snipe`, all offline."""

from __future__ import annotations

import json

import httpx
import pytest

from autodl_cli.client import AutoDLClient
from autodl_cli.errors import APIError, AuthError
from autodl_cli.handlers import snipe as snipe_module

TOKEN = "fake-token"
BASE_IMAGE = "base-image-ee43618uo7"
PRIVATE_IMAGE = "image-abcd1234"
INSTANCE_UUID = "snipe-instance-1"
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

    assert result == {
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
    """A rejected order emits ``order_failed`` and the next poll tries again."""
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
        "found",
        "ordered",
        "instance_status",
        "running",
    ]
    assert events[2]["machine_id"] == "m-1"
    assert "no capacity" in str(events[2]["error"])
    assert len(create_calls) == 2
    assert result["attempts"] == 2
    assert result["status"] == "running"


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
