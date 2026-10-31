"""Terminal output layer.

All Rich rendering and ``--json`` output is centralised here; command modules
call these helpers instead of printing themselves. Handlers never write to the
terminal. The ``--json`` path deliberately bypasses Rich so scripts receive
plain UTF-8 JSON with no ANSI escapes.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from rich.console import Console
from rich.table import Table

if TYPE_CHECKING:
    from collections.abc import Sequence

#: Shared console; Rich disables colour automatically when stdout is not a TTY.
console = Console()


def render_json(payload: object) -> None:
    """Print ``payload`` as JSON on stdout.

    :param payload: JSON-serialisable data.
    """
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def render_table(rows: Sequence[dict[str, object]], columns: Sequence[str]) -> None:
    """Render ``rows`` as a Rich table.

    :param rows: Row mappings.
    :param columns: Column keys, in display order.
    """
    table = Table()
    for column in columns:
        table.add_column(column)
    for row in rows:
        table.add_row(*(str(row.get(column, "")) for column in columns))
    console.print(table)


#: Display labels for the wallet fields, in display order.
_BALANCE_LABELS: tuple[tuple[str, str], ...] = (
    ("assets", "Available"),
    ("blocked_asset", "Blocked"),
    ("voucher_balance", "Voucher balance"),
    ("certain_conditions_voucher_balance", "Conditional voucher balance"),
    ("accumulate", "Accumulated spend"),
    ("total_recharge_asset", "Total recharge"),
    ("available_coupon_num", "Available coupons"),
    ("to_expire_voucher_num", "Expiring vouchers"),
)

#: Balance fields expressed in thousandths of a yuan.
_BALANCE_MONEY_FIELDS = frozenset(
    {
        "assets",
        "blocked_asset",
        "voucher_balance",
        "certain_conditions_voucher_balance",
        "accumulate",
        "total_recharge_asset",
    }
)


def _format_yuan(value: object) -> str:
    """Format a thousandths-of-a-yuan integer as a yuan amount.

    :param value: Raw value from the wallet response.
    :returns: A ``¥`` prefixed amount, or ``"-"`` when the value is not numeric.
    """
    if isinstance(value, bool):
        return "-"
    if isinstance(value, int):
        sign = "-" if value < 0 else ""
        return f"{sign}¥{abs(value) // 1000}.{abs(value) % 1000:03d}"
    if isinstance(value, float):
        return f"¥{value / 1000:.3f}"
    return "-"


def _format_value(value: object) -> str:
    """Format a non-monetary value for display.

    :param value: Raw value from the wallet response.
    :returns: A display string, with ``"-"`` for missing or empty values.
    """
    if value is None:
        return "-"
    if isinstance(value, str) and not value:
        return "-"
    return str(value)


def render_balance(balance: dict[str, object], *, charge_type: str | None = None) -> None:
    """Render a wallet balance as a Rich table.

    Money fields are shown in yuan; ``--json`` callers receive the raw response
    instead, so no information is lost.

    :param balance: The wallet mapping returned by the API handler.
    :param charge_type: Billing mode included in the table title, when known.
    """
    title = "Account balance" if charge_type is None else f"Account balance ({charge_type})"
    table = Table(title=title)
    table.add_column("Item")
    table.add_column("Value", justify="right")

    rows_added = False
    for key, label in _BALANCE_LABELS:
        if key not in balance:
            continue
        value = balance[key]
        rendered = _format_yuan(value) if key in _BALANCE_MONEY_FIELDS else _format_value(value)
        table.add_row(label, rendered)
        rows_added = True

    if not rows_added:
        console.print(f"{title}: no data returned.")
        return
    console.print(table)


def success(message: str) -> None:
    """Print a success message.

    :param message: Text to display.
    """
    console.print(message, style="green", markup=False)


def info(message: str) -> None:
    """Print an informational message.

    :param message: Text to display.
    """
    console.print(message, markup=False)


def warning(message: str) -> None:
    """Print a warning message.

    :param message: Text to display.
    """
    console.print(message, style="yellow", markup=False)


def error(message: str) -> None:
    """Print an error message on stderr.

    :param message: Text to display.
    """
    console.print(message, style="red", stderr=True, markup=False)
