"""Helpers for AutoDL's money unit.

AutoDL's web-console API reports every monetary value as an integer number of
thousandths of a yuan (milliyuan). Handlers convert those raw values to yuan
floats, so the CLI and the public library expose one unit everywhere.
"""

from __future__ import annotations

#: Thousandths of a yuan in one yuan.
MILLIYUAN_PER_YUAN = 1000

#: Wallet fields that AutoDL reports in thousandths of a yuan.
BALANCE_MONEY_FIELDS: frozenset[str] = frozenset(
    {
        "assets",
        "blocked_asset",
        "voucher_balance",
        "certain_conditions_voucher_balance",
        "accumulate",
        "total_recharge_asset",
    }
)

#: Instance and machine fields that AutoDL reports in thousandths of a yuan.
PRICE_FIELDS: tuple[str, ...] = (
    "payg_price",
    "daily_price",
    "weekly_price",
    "monthly_price",
    "yearly_price",
    "origin_pay_price",
)


def to_yuan(value: object) -> float | None:
    """Convert a raw thousandths-of-a-yuan value to yuan.

    :param value: Raw value from the API. Booleans are rejected even though
        they are technically integers.
    :returns: ``value`` divided by :data:`MILLIYUAN_PER_YUAN`, or ``None`` when
        ``value`` is not an integer.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value / MILLIYUAN_PER_YUAN
