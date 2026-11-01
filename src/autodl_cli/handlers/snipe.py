"""GPU-sniping handler: watch machine stock and order the first match.

:func:`select_machine` is a pure ranking function over the normalised machine
records returned by :func:`autodl_cli.handlers.gpu.list_machines`.
:func:`snipe` polls that listing, orders a candidate through
:func:`autodl_cli.handlers.instance.create_instance`, and waits for the new
instance to report ``running``. Progress is reported through an optional
``on_event`` callback; handlers never write to the terminal.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from autodl_cli.errors import APIError, AuthError, AutoDLError
from autodl_cli.handlers import gpu as gpu_handler
from autodl_cli.handlers import instance as instance_handler
from autodl_cli.utils.wait import wait

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from typing import TypeVar

    from autodl_cli.client import AutoDLClient

    T = TypeVar("T")

#: Default number of seconds between stock checks.
DEFAULT_INTERVAL = 10.0

#: Ordering strategies accepted by :func:`select_machine` and :func:`snipe`.
SNIPE_STRATEGIES = ("price", "idle", "first")

#: Multiplier applied to the polling interval after each consecutive order
#: failure on the same machine.
ORDER_BACKOFF_FACTOR = 2.0

#: Ceiling for a machine's order-failure cooldown, as a multiple of the
#: polling interval.
MAX_ORDER_BACKOFF_MULTIPLE = 8.0

#: Instance statuses that mean the newly ordered instance will never start.
FAILED_INSTANCE_STATUSES = frozenset({"failed", "error", "exception", "released"})


def _now() -> float:
    """Return a monotonic timestamp.

    Isolated in a module-level function so tests can replace the clock.

    :returns: Seconds from an arbitrary monotonic origin.
    """
    return time.monotonic()


def _validate_max_price(max_price: float | None) -> None:
    """Validate an optional hourly price limit.

    :param max_price: Price limit in yuan per hour, or ``None``.
    :raises ValueError: When the limit is a boolean, not a number, or negative.
    """
    if max_price is None:
        return
    if isinstance(max_price, bool) or not isinstance(max_price, (int, float)):
        raise ValueError("max_price must be a non-negative number")
    if max_price < 0:
        raise ValueError("max_price must not be negative")


def _idle_count(machine: dict[str, object]) -> int:
    """Return a machine's idle-GPU count, or ``0`` when it is not an integer.

    :param machine: One normalised machine mapping.
    :returns: The idle count, ignoring booleans.
    """
    value = machine.get("gpu_idle_num")
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return 0


def _price_key(machine: dict[str, object]) -> tuple[bool, float]:
    """Build the price sort key, placing machines without a price last.

    :param machine: One normalised machine mapping; prices are yuan floats.
    :returns: ``(missing, price)`` for ascending price ordering.
    """
    value = machine.get("payg_price")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return (False, float(value))
    return (True, 0.0)


def _machine_id_key(machine: dict[str, object]) -> str:
    """Return the machine ID used as the final sort tie-breaker.

    :param machine: One normalised machine mapping.
    :returns: The machine ID, or an empty string when it is not a string.
    """
    value = machine.get("machine_id")
    return value if isinstance(value, str) else ""


def _order_backoff(interval: float, failures: int) -> float:
    """Return how long a machine stays out of the candidate set after a rejection.

    The cooldown starts at one polling interval and doubles with every
    consecutive failure, capped at :data:`MAX_ORDER_BACKOFF_MULTIPLE` intervals.

    :param interval: Polling interval in seconds.
    :param failures: Consecutive order failures for the machine; at least 1.
    :returns: Cooldown in seconds.
    """
    return min(interval * ORDER_BACKOFF_FACTOR ** (failures - 1), interval * MAX_ORDER_BACKOFF_MULTIPLE)


def _filter_and_sort(
    machines: Iterable[dict[str, object]],
    *,
    gpu_types: Iterable[str] = (),
    gpu_amount: int = 1,
    max_price: float | None = None,
    strategy: str = "price",
) -> list[dict[str, object]]:
    """Filter machines by the snipe criteria and rank the survivors.

    :param machines: Normalised machine mappings; prices are yuan floats.
    :param gpu_types: Exact GPU names to keep, matched case-insensitively after
        stripping; empty means every model.
    :param gpu_amount: Minimum number of idle GPUs per machine.
    :param max_price: Maximum pay-as-you-go price in yuan per hour; ``None``
        disables the limit.
    :param strategy: ``price``, ``idle``, or ``first``.
    :returns: The matching machines in strategy order.
    :raises ValueError: When ``gpu_amount``, ``max_price``, or ``strategy`` is
        invalid.
    """
    if isinstance(gpu_amount, bool) or not isinstance(gpu_amount, int) or gpu_amount < 1:
        raise ValueError("gpu_amount must be an integer of at least 1")
    _validate_max_price(max_price)
    if strategy not in SNIPE_STRATEGIES:
        raise ValueError(f"strategy must be one of {', '.join(SNIPE_STRATEGIES)}")

    wanted = {name.strip().casefold() for name in gpu_types if name.strip()}

    candidates: list[dict[str, object]] = []
    for machine in machines:
        if not isinstance(machine, dict):
            continue
        if _idle_count(machine) < gpu_amount:
            continue
        if wanted:
            gpu_name = machine.get("gpu_name")
            if not isinstance(gpu_name, str) or gpu_name.strip().casefold() not in wanted:
                continue
        if max_price is not None:
            price = machine.get("payg_price")
            if isinstance(price, bool) or not isinstance(price, (int, float)) or price > max_price:
                continue
        candidates.append(machine)

    if strategy == "price":
        candidates.sort(key=lambda machine: (*_price_key(machine), -_idle_count(machine), _machine_id_key(machine)))
    elif strategy == "idle":
        candidates.sort(key=lambda machine: (-_idle_count(machine), *_price_key(machine), _machine_id_key(machine)))
    return candidates


def select_machine(
    machines: Iterable[dict[str, object]],
    *,
    gpu_types: Iterable[str] = (),
    gpu_amount: int = 1,
    max_price: float | None = None,
    strategy: str = "price",
) -> dict[str, object] | None:
    """Choose the best matching machine from a listing.

    A non-empty ``gpu_types`` requires an exact, case-insensitive GPU-name
    match after stripping whitespace; it is not a substring match. Machine
    ``payg_price`` values are yuan floats, and machines without a numeric price
    are excluded when ``max_price`` is set.

    ``price`` orders by hourly price ascending (missing prices last), then by
    idle GPUs descending, then machine ID. ``idle`` orders by idle GPUs
    descending, then price ascending (missing last), then machine ID. ``first``
    keeps the input order.

    :param machines: Normalised machine mappings from
        :func:`autodl_cli.handlers.gpu.list_machines`.
    :param gpu_types: Exact GPU names to require; empty means every model.
    :param gpu_amount: Required number of idle GPUs; must be at least 1.
    :param max_price: Maximum pay-as-you-go price in yuan per hour.
    :param strategy: ``price``, ``idle``, or ``first``.
    :returns: The first ranked candidate, or ``None`` when nothing matches.
    :raises ValueError: When ``gpu_amount``, ``max_price``, or ``strategy`` is
        invalid.
    """
    candidates = _filter_and_sort(
        machines,
        gpu_types=gpu_types,
        gpu_amount=gpu_amount,
        max_price=max_price,
        strategy=strategy,
    )
    return candidates[0] if candidates else None


def _emit(on_event: Callable[[dict[str, object]], None] | None, event: dict[str, object]) -> None:
    """Send one progress event when a callback is configured.

    :param on_event: Optional callback supplied by the command layer.
    :param event: Event mapping to deliver.
    """
    if on_event is not None:
        on_event(event)


def _raise_if_timed_out(deadline: float | None, *, timeout: float, reason: str) -> None:
    """Raise :class:`TimeoutError` once the deadline has passed.

    :param deadline: Monotonic deadline, or ``None`` when no timeout is set.
    :param timeout: Configured timeout in seconds, used in the message.
    :param reason: Text appended after the elapsed-time prefix.
    :raises TimeoutError: When the current time is at or past ``deadline``.
    """
    if deadline is not None and _now() >= deadline:
        raise TimeoutError(f"Timed out after {timeout:g}s {reason}")


def _instance_status(entry: dict[str, object] | None) -> str:
    """Return a list entry's status, or ``"not found"`` when it is missing.

    :param entry: The matching instance-list entry, or ``None``.
    :returns: The status string, with missing or empty values mapped to
        ``"not found"``.
    """
    if entry is None:
        return "not found"
    status = entry.get("status")
    return str(status) if status else "not found"


def _call_with_retry(
    call: Callable[[], T],
    *,
    retry: int,
    interval: float,
    deadline: float | None,
    timeout: float,
    on_event: Callable[[dict[str, object]], None] | None,
    timeout_reason: str,
) -> T:
    """Run one polling call, retrying consecutive transient API errors.

    :class:`~autodl_cli.errors.AuthError` is never retried. Every other
    :class:`~autodl_cli.errors.AutoDLError` counts towards ``retry``; a
    ``poll_failed`` event is emitted only while another attempt will follow.

    :param call: Zero-argument callable that performs the poll.
    :param retry: Maximum number of consecutive transient failures to retry.
    :param interval: Seconds to wait before each retry.
    :param deadline: Monotonic deadline, or ``None`` when no timeout is set.
    :param timeout: Configured timeout in seconds, used in timeout messages.
    :param on_event: Optional progress callback.
    :param timeout_reason: Text appended to the timeout message.
    :returns: The call's result.
    :raises autodl_cli.errors.AuthError: Immediately, without retrying.
    :raises autodl_cli.errors.AutoDLError: When failures exceed ``retry``.
    :raises TimeoutError: When the deadline passes before a retry.
    """
    failures = 0
    while True:
        try:
            return call()
        except AuthError:
            raise
        except AutoDLError as exc:
            failures += 1
            if failures > retry:
                raise
            _emit(
                on_event,
                {
                    "event": "poll_failed",
                    "error": str(exc),
                    "retries": failures,
                    "limit": retry,
                },
            )
            _raise_if_timed_out(deadline, timeout=timeout, reason=timeout_reason)
            wait(interval)


def snipe(
    client: AutoDLClient,
    *,
    regions: Iterable[str] = (),
    gpu_types: Iterable[str] = (),
    gpu_amount: int = 1,
    max_price: float | None = None,
    strategy: str = "price",
    base_image_uuid: str = "",
    private_image_uuid: str = "",
    instance_name: str = "",
    expand_data_disk: int = 0,
    interval: float = DEFAULT_INTERVAL,
    timeout: float = 0.0,
    retry: int = 0,
    on_event: Callable[[dict[str, object]], None] | None = None,
) -> dict[str, object]:
    """Poll GPU stock until a machine matches, order it, and wait until running.

    The call blocks until the instance reports ``running``, the timeout expires,
    or the order is rejected in a way that must not be retried. Progress is
    delivered through ``on_event``; handlers themselves never print.

    Region identifiers are resolved through :func:`autodl_cli.handlers.gpu.list_regions`
    and :func:`autodl_cli.handlers.gpu.select_regions` once, before polling. At
    least one of ``regions`` or ``gpu_types`` is required; an empty region list
    searches every region. ``max_price`` and a larger ``gpu_amount`` only
    narrow the search. ``retry`` limits consecutive transient API errors while
    polling; authentication errors are never retried. Failed orders (except
    :class:`~autodl_cli.errors.AuthError`) are retried indefinitely, but each
    rejected machine is excluded for a cooldown that starts at one ``interval``
    and doubles per consecutive failure on that machine (see
    :func:`_order_backoff`), so another matching machine is tried next and a
    persistently broken machine is not hammered every poll.

    Events are mappings whose ``event`` key is ``poll``, ``poll_failed``,
    ``found``, ``order_failed``, ``ordered``, ``instance_status``, or
    ``running``. ``poll`` reports how many candidates are selectable
    (``matches``) and how many are cooling down after a rejected order
    (``cooling``); ``order_failed`` reports the machine's consecutive failure
    count (``failures``) and the cooldown in seconds (``backoff``).

    :param client: Authenticated API client.
    :param regions: Region signs, data centers, or display names to search.
    :param gpu_types: Exact GPU names to require; empty means every model.
    :param gpu_amount: Number of idle GPUs to request; must be at least 1.
    :param max_price: Maximum pay-as-you-go price in yuan per hour.
    :param strategy: Machine ordering: ``price``, ``idle``, or ``first``.
    :param base_image_uuid: Base-image UUID; mutually exclusive with
        ``private_image_uuid``.
    :param private_image_uuid: Private-image UUID; mutually exclusive with
        ``base_image_uuid``.
    :param instance_name: Optional name for the new instance.
    :param expand_data_disk: Extra data-disk size in GB.
    :param interval: Seconds between checks; must be positive.
    :param timeout: Maximum seconds to wait; ``0`` waits until interrupted.
    :param retry: Consecutive transient polling errors to retry; ``0`` disables
        retries.
    :param on_event: Optional progress callback.
    :returns: A flat mapping describing the ordered instance and the machine it
        runs on.
    :raises ValueError: When an argument is invalid or neither ``regions`` nor
        ``gpu_types`` is supplied, before any request is sent.
    :raises TimeoutError: When ``timeout`` expires without ordering or starting
        an instance.
    :raises autodl_cli.errors.AuthError: When the token is rejected.
    :raises autodl_cli.errors.APIError: When the new instance enters a failed
        status.
    """
    if isinstance(gpu_amount, bool) or not isinstance(gpu_amount, int) or gpu_amount < 1:
        raise ValueError("gpu_amount must be an integer of at least 1")
    _validate_max_price(max_price)
    if strategy not in SNIPE_STRATEGIES:
        raise ValueError(f"strategy must be one of {', '.join(SNIPE_STRATEGIES)}")
    if isinstance(interval, bool) or not isinstance(interval, (int, float)) or interval <= 0:
        raise ValueError("interval must be a positive number")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout < 0:
        raise ValueError("timeout must not be negative")
    if isinstance(retry, bool) or not isinstance(retry, int) or retry < 0:
        raise ValueError("retry must be an integer of at least 0")

    base_image = base_image_uuid.strip()
    private_image = private_image_uuid.strip()
    if bool(base_image) == bool(private_image):
        raise ValueError("exactly one of base_image_uuid and private_image_uuid must be set")

    region_texts = tuple(region.strip() for region in regions)
    if any(not region for region in region_texts):
        raise ValueError("regions must not contain empty values")
    gpu_type_texts = tuple(name.strip() for name in gpu_types)
    if any(not name for name in gpu_type_texts):
        raise ValueError("gpu_types must not contain empty values")

    if not region_texts and not gpu_type_texts:
        raise ValueError("pass at least one of region and gpu")

    started = _now()
    deadline = started + timeout if timeout > 0 else None

    region_sign_list: list[str] = []
    if region_texts:
        known_regions = gpu_handler.list_regions(client)
        for region in gpu_handler.select_regions(known_regions, region_texts):
            region_sign_list.extend(gpu_handler.region_signs(region))

    attempt = 0
    machine: dict[str, object] | None = None
    order: dict[str, object] | None = None
    instance_uuid = ""
    order_failures: dict[str, int] = {}
    cooldowns: dict[str, float] = {}

    while True:
        attempt += 1
        _raise_if_timed_out(deadline, timeout=timeout, reason="without ordering an instance")

        page = _call_with_retry(
            lambda: gpu_handler.list_machines(
                client,
                charge_type="payg",
                region_signs=region_sign_list,
                gpu_types=gpu_type_texts,
                gpu_idle_num=gpu_amount,
                all_pages=True,
            ),
            retry=retry,
            interval=interval,
            deadline=deadline,
            timeout=timeout,
            on_event=on_event,
            timeout_reason="without ordering an instance",
        )
        entries = page.get("machines")
        candidates = _filter_and_sort(
            entries if isinstance(entries, list) else [],
            gpu_types=gpu_type_texts,
            gpu_amount=gpu_amount,
            max_price=max_price,
            strategy=strategy,
        )
        now = _now()
        ready = [candidate for candidate in candidates if cooldowns.get(_machine_id_key(candidate), 0.0) <= now]
        _emit(
            on_event,
            {
                "event": "poll",
                "attempt": attempt,
                "matches": len(ready),
                "cooling": len(candidates) - len(ready),
            },
        )

        if not ready:
            _raise_if_timed_out(deadline, timeout=timeout, reason="without ordering an instance")
            wait(interval)
            continue

        machine = ready[0]
        _emit(on_event, {"event": "found", "machine": machine})
        try:
            order = instance_handler.create_instance(
                client,
                machine_id=str(machine["machine_id"]),
                base_image_uuid=base_image,
                private_image_uuid=private_image,
                gpu_amount=gpu_amount,
                instance_name=instance_name,
                expand_data_disk=expand_data_disk,
            )
        except AuthError:
            raise
        except AutoDLError as exc:
            machine_key = _machine_id_key(machine)
            failures = order_failures.get(machine_key, 0) + 1
            order_failures[machine_key] = failures
            backoff = _order_backoff(interval, failures)
            cooldowns[machine_key] = _now() + backoff
            _emit(
                on_event,
                {
                    "event": "order_failed",
                    "machine_id": machine.get("machine_id"),
                    "error": str(exc),
                    "failures": failures,
                    "backoff": round(backoff, 1),
                },
            )
            _raise_if_timed_out(deadline, timeout=timeout, reason="without ordering an instance")
            continue

        instance_uuid = str(order["instance_uuid"])
        _emit(
            on_event,
            {
                "event": "ordered",
                "instance_uuid": instance_uuid,
                "machine": machine,
            },
        )
        break

    if machine is None or order is None:  # Pragmatic guard; the loop cannot reach this.
        raise APIError("AutoDL snipe finished without ordering an instance")

    last_status: str | None = None
    while True:
        last_label = last_status if last_status is not None else "not found"
        timeout_reason = f"waiting for instance {instance_uuid} to start (last status: {last_label!r})"
        listed = _call_with_retry(
            lambda: instance_handler.list_instances(client, query=instance_uuid),
            retry=retry,
            interval=interval,
            deadline=deadline,
            timeout=timeout,
            on_event=on_event,
            timeout_reason=timeout_reason,
        )
        entry = next(
            (
                candidate
                for candidate in listed
                if isinstance(candidate, dict) and candidate.get("uuid") == instance_uuid
            ),
            None,
        )
        status = _instance_status(entry)
        if status != last_status:
            _emit(
                on_event,
                {
                    "event": "instance_status",
                    "instance_uuid": instance_uuid,
                    "status": status,
                },
            )
            last_status = status

        if status.casefold() == "running":
            _emit(on_event, {"event": "running", "instance_uuid": instance_uuid})
            break
        if status.casefold() in FAILED_INSTANCE_STATUSES:
            raise APIError(f"Instance {instance_uuid} entered status {status!r} while starting")

        _raise_if_timed_out(
            deadline,
            timeout=timeout,
            reason=f"waiting for instance {instance_uuid} to start (last status: {status!r})",
        )
        wait(interval)

    return {
        "instance_uuid": instance_uuid,
        "machine_id": machine.get("machine_id"),
        "machine_alias": machine.get("machine_alias"),
        "region_name": machine.get("region_name"),
        "region_sign": machine.get("region_sign"),
        "gpu_name": machine.get("gpu_name"),
        "gpu_idle_num": machine.get("gpu_idle_num"),
        "payg_price": machine.get("payg_price"),
        "gpu_amount": order.get("gpu_amount", gpu_amount),
        "charge_type": order.get("charge_type", "payg"),
        "base_image_uuid": order.get("base_image_uuid", base_image),
        "private_image_uuid": order.get("private_image_uuid", private_image),
        "instance_name": order.get("instance_name", instance_name),
        "expand_data_disk": order.get("expand_data_disk", expand_data_disk),
        "status": "running",
        "attempts": attempt,
        "elapsed_seconds": round(_now() - started, 1),
    }
