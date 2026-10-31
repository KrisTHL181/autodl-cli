"""Rate-limit helpers for API and CLI calls.

TODO: implement jittered backoff and honour a configurable global rate limit.
"""

from __future__ import annotations


def wait(sleep_factor: float = 1.0) -> None:
    """Sleep between requests.

    :param sleep_factor: Base delay multiplier in seconds.
    """
    ...
