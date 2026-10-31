"""Jittered sleep helper for API and CLI calls.

Every deliberate delay should go through :func:`wait`, so the throttling
behaviour can be adjusted in one place.
"""

from __future__ import annotations

import math
import random
import time


def _generate_lognormal(mean_value: float, sigma: float = 1.0) -> float:
    """Draw a positive sample whose arithmetic mean is ``mean_value``.

    :param mean_value: Arithmetic mean of the distribution.
    :param sigma: Standard deviation of the underlying normal distribution.
    :returns: A positive random variate.
    """
    mu = math.log(mean_value) - (sigma**2) / 2
    return random.lognormvariate(mu, sigma)


def wait(sleep_factor: float = 1.0) -> None:
    """Sleep for a jittered multiple of ``sleep_factor`` seconds.

    The delay is drawn from a log-normal distribution with the given mean and
    capped at three times ``sleep_factor``, so repeated calls spread out without
    producing long outliers.

    :param sleep_factor: Base delay multiplier in seconds.
    """
    time.sleep(min(_generate_lognormal(sleep_factor, 0.5), 3 * sleep_factor))
