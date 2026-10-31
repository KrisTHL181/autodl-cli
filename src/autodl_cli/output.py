"""Terminal output layer.

All Rich rendering and ``--json`` output is centralised here; command modules
call these helpers instead of printing themselves. Handlers never write to the
terminal. The ``--json`` path deliberately bypasses Rich so scripts receive
plain UTF-8 JSON with no ANSI escapes.
"""

from __future__ import annotations

import json
from datetime import datetime
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

    :param value: Raw value from an API response.
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


def _format_timestamp(value: object) -> str:
    """Format an ISO 8601 timestamp for display.

    The wall-clock time and the offset returned by AutoDL are kept as-is; no
    conversion to the local time zone happens.

    :param value: Raw timestamp from the account response.
    :returns: ``YYYY-MM-DD HH:MM:SS``, the untouched string when it does not
        parse, or ``"-"`` when the value is missing.
    """
    if not isinstance(value, str) or not value:
        return "-"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value
    return parsed.strftime("%Y-%m-%d %H:%M:%S")


def _format_phone(account: dict[str, object]) -> str:
    """Join the phone area prefix and number.

    :param account: The account mapping returned by the API handler.
    :returns: ``"<area> <number>"``, or ``"-"`` when no number is present.
    """
    phone = account.get("phone")
    if not isinstance(phone, str) or not phone:
        return "-"
    area = account.get("phone_area")
    if isinstance(area, str) and area:
        return f"{area} {phone}"
    return phone


def render_account(account: dict[str, object]) -> None:
    """Render an account profile as a Rich table.

    :param account: The account mapping returned by :func:`autodl_cli.handlers.account.get_me`.
    """
    table = Table(title="Account")
    table.add_column("Field")
    table.add_column("Value")

    email = account.get("email")
    if account.get("email_confirmed") is False and isinstance(email, str) and email:
        email = f"{email} (unconfirmed)"

    admin_role: str | None = None
    if account.get("is_super_admin"):
        admin_role = "super admin"
    elif account.get("is_admin"):
        admin_role = "admin"

    fields: tuple[tuple[str, object], ...] = (
        ("Username", account.get("username")),
        ("Nickname", account.get("nickname")),
        ("User ID", account.get("id")),
        ("Email", email),
        ("Phone", _format_phone(account)),
        ("Status", account.get("status")),
        ("Role", admin_role),
        ("Registered", _format_timestamp(account.get("created_at"))),
        ("Last login", _format_timestamp(account.get("logged_in_at"))),
        ("Max instances", account.get("max_instance_num")),
        ("Sub-users", account.get("sub_user_num")),
        ("Private images", account.get("private_image_num")),
    )

    for label, value in fields:
        if value is None or (isinstance(value, str) and not value):
            continue
        table.add_row(label, _format_value(value))

    console.print(table)


def _format_instance_gpu(instance: dict[str, object]) -> str:
    """Describe an instance's GPU allocation.

    :param instance: One instance mapping returned by the API handler.
    :returns: The GPU alias with a count when more than one is requested,
        ``"CPU"`` for a CPU-only instance, or ``"-"``.
    """
    name = instance.get("user_define_gpu_name") or instance.get("snapshot_gpu_alias_name")
    if not isinstance(name, str) or not name:
        return "CPU" if instance.get("start_mode") == "non_gpu" else "-"
    amount = instance.get("req_gpu_amount")
    if isinstance(amount, int) and not isinstance(amount, bool) and amount > 1:
        return f"{name} ×{amount}"
    return name


def _format_instance_status(instance: dict[str, object]) -> str:
    """Combine an instance's status with its sub-status.

    :param instance: One instance mapping returned by the API handler.
    :returns: ``"status (sub_status)"``, or just the status when no sub-status
        is present.
    """
    status = _format_value(instance.get("status"))
    sub_status = instance.get("sub_status")
    if isinstance(sub_status, str) and sub_status:
        return f"{status} ({sub_status})"
    return status


def _format_instance_price(instance: dict[str, object]) -> str:
    """Format an instance's hourly or daily price.

    :param instance: One instance mapping returned by the API handler.
    :returns: A ``¥…/h`` or ``¥…/day`` string, or ``"-"`` when no price is
        reported.
    """
    payg_price = instance.get("payg_price")
    if isinstance(payg_price, int) and not isinstance(payg_price, bool) and payg_price > 0:
        return f"{_format_yuan(payg_price)}/h"
    daily_price = instance.get("daily_price")
    if isinstance(daily_price, int) and not isinstance(daily_price, bool) and daily_price > 0:
        return f"{_format_yuan(daily_price)}/day"
    return "-"


def _first_text(instance: dict[str, object], *keys: str) -> str:
    """Return the first non-empty string among ``keys``.

    :param instance: One instance mapping returned by the API handler.
    :param keys: Candidate field names, in preference order.
    :returns: The first non-empty value, or ``"-"``.
    """
    for key in keys:
        value = instance.get(key)
        if isinstance(value, str) and value:
            return value
    return "-"


def _format_instance_summary(instance: dict[str, object]) -> str:
    """Join the status, billing, GPU, region, and price into one line.

    :param instance: One instance mapping returned by the API handler.
    :returns: Dot-separated fields, skipping missing values.
    """
    parts = (
        _format_instance_status(instance),
        _format_value(instance.get("charge_type")),
        _format_instance_gpu(instance),
        _first_text(instance, "region_name", "region_sign"),
        _format_instance_price(instance),
    )
    return " · ".join(part for part in parts if part != "-") or "-"


def render_instances(instances: Sequence[dict[str, object]]) -> None:
    """Render a list of instances as a two-column Rich table.

    Long connection strings would squeeze an eight-column table below a
    readable width on an 80-column terminal, so each instance keeps its ID in
    the first column and stacks the name, summary, and SSH command in the
    second.

    :param instances: Mappings returned by
        :func:`autodl_cli.handlers.instance.list_instances`.
    """
    if not instances:
        console.print("No instances found.")
        return

    table = Table(title=f"Instances ({len(instances)})")
    table.add_column("ID", no_wrap=True)
    table.add_column("Instance")

    for instance in instances:
        lines: list[str] = []
        name = instance.get("name")
        if isinstance(name, str) and name:
            lines.append(name)
        lines.append(_format_instance_summary(instance))
        ssh_command = instance.get("ssh_command")
        if isinstance(ssh_command, str) and ssh_command:
            lines.append(ssh_command)
        table.add_row(_format_value(instance.get("uuid")), "\n".join(lines))

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
