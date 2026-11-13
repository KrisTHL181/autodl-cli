"""Shared polling primitives for handler wait loops.

These helpers keep retry, timeout, and progress reporting identical across
handlers. They import no handler module and never write to the terminal, so
they can be used from any handler without creating an import cycle.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from autodl_cli.errors import AuthError, AutoDLError
from autodl_cli.utils.wait import wait

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import TypeVar

    T = TypeVar("T")


def now() -> float:
    """Return a monotonic timestamp.

    Isolated in a module-level function so tests can replace the clock.

    :returns: Seconds from an arbitrary monotonic origin.
    """
    return time.monotonic()


def sleep(interval: float) -> None:
    """Wait between polls through the shared jittered delay helper.

    Isolated in a module-level function so tests can replace the sleep.

    :param interval: Base delay in seconds.
    """
    wait(interval)


def emit(on_event: Callable[[dict[str, object]], None] | None, event: dict[str, object]) -> None:
    """Send one progress event when a callback is configured.

    :param on_event: Optional callback supplied by the command layer.
    :param event: Event mapping to deliver.
    """
    if on_event is not None:
        on_event(event)


def raise_if_timed_out(deadline: float | None, *, timeout: float, reason: str) -> None:
    """Raise :class:`TimeoutError` once the deadline has passed.

    :param deadline: Monotonic deadline, or ``None`` when no timeout is set.
    :param timeout: Configured timeout in seconds, used in the message.
    :param reason: Text appended after the elapsed-time prefix.
    :raises TimeoutError: When the current time is at or past ``deadline``.
    """
    if deadline is not None and now() >= deadline:
        raise TimeoutError(f"Timed out after {timeout:g}s {reason}")


def call_with_retry(
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
            emit(
                on_event,
                {
                    "event": "poll_failed",
                    "error": str(exc),
                    "retries": failures,
                    "limit": retry,
                },
            )
            raise_if_timed_out(deadline, timeout=timeout, reason=timeout_reason)
            sleep(interval)
