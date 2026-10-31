"""Tests for :mod:`autodl_cli.utils.wait`."""

from __future__ import annotations

import pytest

from autodl_cli.utils import wait as wait_module


def test_wait_sleeps_for_the_sampled_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    """The sampled variate is passed to ``sleep`` unchanged."""
    delays: list[float] = []
    monkeypatch.setattr(wait_module, "_generate_lognormal", lambda mean, sigma: 0.5)
    monkeypatch.setattr(wait_module.time, "sleep", delays.append)

    wait_module.wait(2.0)

    assert delays == [0.5]


def test_wait_caps_the_delay_at_three_times_the_factor(monkeypatch: pytest.MonkeyPatch) -> None:
    """A long sample is clipped to ``3 * sleep_factor``."""
    delays: list[float] = []
    monkeypatch.setattr(wait_module, "_generate_lognormal", lambda mean, sigma: 100.0)
    monkeypatch.setattr(wait_module.time, "sleep", delays.append)

    wait_module.wait(2.0)

    assert delays == [6.0]
