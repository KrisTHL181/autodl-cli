"""Terminal output layer.

All Rich rendering and ``--json`` output is centralised here; command modules
call these helpers instead of printing themselves. Handlers never write to the
terminal. The ``--json`` path deliberately bypasses Rich so scripts receive
plain UTF-8 JSON with no ANSI escapes.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from rich import box
from rich.cells import cell_len
from rich.console import Console
from rich.table import Table
from rich.text import Text

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

#: Shared console; Rich disables colour automatically when stdout is not a TTY.
#: Automatic highlighting is off so the explicit palette below is the only
#: source of colour.
console = Console(highlight=False)

# Colour palette, mirroring the zhihu-cli conventions: cyan for titles and
# structure, green for success, yellow for warnings, magenta for numbers,
# red for errors, dim for secondary metadata, and bold for key labels.
_STYLE_TITLE = "bold cyan"
_STYLE_HEADER = "bold cyan"
_STYLE_COLUMN = "cyan"
_STYLE_LABEL = "bold"
_STYLE_NUM = "magenta"
_STYLE_MONEY = "bold magenta"
_STYLE_META = "dim"
_STYLE_OK = "bold green"
_STYLE_WARN = "yellow"
_STYLE_ERR = "bold red"
_STYLE_LINK = "blue dim"


def _table(title: str | None = None) -> Table:
    """Build a table with the shared border and header styling.

    :param title: Optional table title.
    :returns: A Rich table using the rounded box and cyan headers.
    """
    return Table(title=title, box=box.ROUNDED, title_style=_STYLE_TITLE, header_style=_STYLE_HEADER)


def _styled(value: object, style: str | None = None) -> Text:
    """Wrap a value in a rich :class:`Text` cell.

    :param value: Cell content.
    :param style: Optional style name.
    :returns: The styled text cell.
    """
    return Text(str(value), style=style)


def _status_style(value: object) -> str:
    """Pick a colour for a status-like string.

    :param value: Status string from the API.
    :returns: A style name: green for healthy, yellow for transitional, red
        for failures, and cyan otherwise.
    """
    text = str(value).lower()
    if text.startswith(("normal", "healthy", "ok", "running")):
        return _STYLE_OK
    if text.startswith(("shutdown", "stopped", "starting", "stopping", "pending")):
        return _STYLE_WARN
    if text.startswith(("error", "failed", "released", "due", "exception", "oom")):
        return _STYLE_ERR
    return _STYLE_COLUMN


def render_json(payload: object) -> None:
    """Print ``payload`` as JSON on stdout.

    :param payload: JSON-serialisable data.
    """
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def render_curl(command: str) -> None:
    """Print a generated curl command verbatim.

    Plain ``print`` is used instead of Rich so the command is neither wrapped
    nor interpreted as markup.

    :param command: Shell command to display.
    """
    print(command)


def render_http_response(
    *,
    status: int,
    reason: str,
    headers: Mapping[str, str],
    body: str,
    json_body: object,
    is_json: bool,
    include_headers: bool,
) -> None:
    """Print a raw HTTP response.

    Plain ``print`` is used instead of Rich so debug output is neither wrapped
    nor interpreted as markup. When ``include_headers`` is set, the status line
    and response headers precede the body, separated by a blank line.

    :param status: HTTP status code.
    :param reason: HTTP reason phrase.
    :param headers: Response headers.
    :param body: Raw response text.
    :param json_body: Parsed response body when ``is_json`` is set.
    :param is_json: Whether the response body parsed as JSON.
    :param include_headers: Whether to print the status line and headers.
    """
    if include_headers:
        print(f"HTTP {status} {reason}")
        for key, value in headers.items():
            print(f"{key}: {value}")
        print()
    if is_json:
        print(json.dumps(json_body, ensure_ascii=False, indent=2))
    else:
        print(body)


def render_table(rows: Sequence[dict[str, object]], columns: Sequence[str]) -> None:
    """Render ``rows`` as a Rich table.

    :param rows: Row mappings.
    :param columns: Column keys, in display order.
    """
    table = _table()
    for column in columns:
        table.add_column(column, style=_STYLE_COLUMN)
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


def _value_cell(value: object, style: str | None = None) -> Text:
    """Format a value as a styled table cell.

    :param value: Raw value from an API response.
    :param style: Style for real values; ``"-"`` placeholders stay dim.
    :returns: The formatted, styled cell.
    """
    text = _format_value(value)
    return Text(text, style=_STYLE_META if text == "-" else style)


def _count_cell(value: object, *, alert_zero: bool = False) -> Text:
    """Format a numeric stock cell.

    :param value: Raw count.
    :param alert_zero: Whether a zero should be flagged in red.
    :returns: The count in magenta, in red when zero and ``alert_zero`` is set.
    """
    text = _format_value(value)
    if text == "-":
        return Text(text, style=_STYLE_META)
    if alert_zero and text == "0":
        return Text(text, style=_STYLE_ERR)
    return Text(text, style=_STYLE_NUM)


def render_balance(balance: dict[str, object], *, charge_type: str | None = None) -> None:
    """Render a wallet balance as a Rich table.

    Money fields are shown in yuan; ``--json`` callers receive the raw response
    instead, so no information is lost.

    :param balance: The wallet mapping returned by the API handler.
    :param charge_type: Billing mode included in the table title, when known.
    """
    title = "Account balance" if charge_type is None else f"Account balance ({charge_type})"
    table = _table(title)
    table.add_column("Item")
    table.add_column("Value", justify="right")

    rows_added = False
    for key, label in _BALANCE_LABELS:
        if key not in balance:
            continue
        value = balance[key]
        if key in _BALANCE_MONEY_FIELDS:
            rendered = _styled(_format_yuan(value), _STYLE_MONEY)
        else:
            rendered = _styled(_format_value(value), _STYLE_NUM)
        table.add_row(_styled(label, _STYLE_LABEL), rendered)
        rows_added = True

    if not rows_added:
        console.print(f"{title}: no data returned.", style=_STYLE_META)
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


def _account_value_style(label: str, text: str) -> str:
    """Pick a colour for one account field value.

    :param label: Field label.
    :param text: Already-formatted value.
    :returns: A style name.
    """
    if label in ("Username", "Nickname"):
        return _STYLE_OK
    if label == "Status":
        return _status_style(text)
    if label in ("Registered", "Last login"):
        return _STYLE_META
    if label == "Role":
        return _STYLE_WARN
    return _STYLE_COLUMN


def render_account(account: dict[str, object]) -> None:
    """Render an account profile as a Rich table.

    :param account: The account mapping returned by :func:`autodl_cli.handlers.account.get_me`.
    """
    table = _table("Account")
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
        text = _format_value(value)
        table.add_row(_styled(label, _STYLE_LABEL), _styled(text, _account_value_style(label, text)))

    console.print(table)


def _format_instance_location(instance: dict[str, object]) -> str:
    """Return ``region / machine`` for an instance.

    :param instance: One instance mapping returned by the API handler.
    :returns: The region and machine alias, or whichever one is present.
    """
    region = _first_text(instance, "region_name", "region_sign")
    machine = instance.get("machine_alias")
    if isinstance(machine, str) and machine and region != "-":
        return f"{region} / {machine}"
    return region


def _format_instance_title(instance: dict[str, object]) -> Text:
    """Build the multi-line identifier cell of the wide table.

    :param instance: One instance mapping returned by the API handler.
    :returns: Location, UUID, and name (when set), one per line; the location
        is dimmed, the UUID is cyan, and the name is bold.
    """
    text = Text()
    text.append(_format_instance_location(instance), style=_STYLE_META)
    text.append("\n")
    text.append(_format_value(instance.get("uuid")), style=_STYLE_COLUMN)
    name = instance.get("name")
    if isinstance(name, str) and name:
        text.append("\n")
        text.append(name, style=_STYLE_LABEL)
    return text


def _format_instance_status(instance: dict[str, object]) -> str:
    """Combine an instance's status with its sub-status and OOM state.

    :param instance: One instance mapping returned by the API handler.
    :returns: ``"status (sub_status)"``, or just the status when no sub-status
        is present, with ``" (OOM)"`` appended when the last run was killed for
        running out of memory.
    """
    status = _format_value(instance.get("status"))
    sub_status = instance.get("sub_status")
    if isinstance(sub_status, str) and sub_status:
        status = f"{status} ({sub_status})"
    if instance.get("oom_killed") is True:
        status = f"{status} (OOM)"
    return status


def _instance_status_cell(instance: dict[str, object]) -> Text:
    """Build the colour-coded status cell.

    :param instance: One instance mapping returned by the API handler.
    :returns: The status coloured by health, with the sub-status dimmed and
        an OOM marker in red.
    """
    text = Text()
    text.append(_format_value(instance.get("status")), style=_status_style(instance.get("status")))
    sub_status = instance.get("sub_status")
    if isinstance(sub_status, str) and sub_status:
        text.append(f" ({sub_status})", style=_STYLE_META)
    if instance.get("oom_killed") is True:
        text.append(" (OOM)", style=_STYLE_ERR)
    return text


def _format_instance_spec(instance: dict[str, object]) -> str:
    """Describe the GPU allocation as the web console does.

    ``start_mode`` wins over the snapshot GPU name: an instance started in
    ``non_gpu`` mode runs without its cards even though the response still
    carries the GPU alias the snapshot was built for.

    :param instance: One instance mapping returned by the API handler.
    :returns: The GPU alias and requested count (``"RTX 3090 ×1"``), ``"CPU"``
        for a CPU-only instance, or ``"-"``.
    """
    if instance.get("start_mode") == "non_gpu":
        return "CPU"
    name = instance.get("user_define_gpu_name") or instance.get("snapshot_gpu_alias_name")
    if not isinstance(name, str) or not name:
        return "-"
    amount = instance.get("req_gpu_amount")
    if isinstance(amount, int) and not isinstance(amount, bool) and amount > 0:
        return f"{name} ×{amount}"
    return name


def _format_instance_cards(instance: dict[str, object]) -> str:
    """Describe how many cards are free on the instance's machine.

    The list endpoint reports machine-level availability, not the instance's
    own allocation. It answers whether a stopped instance could be started
    with its cards, and explains why an instance fell back to CPU mode.

    :param instance: One instance mapping returned by the API handler.
    :returns: ``"Cards <idle>/<total>"``, or an empty string when the machine
        does not report card counts.
    """
    idle = instance.get("gpu_idle_num")
    total = instance.get("gpu_all_num")
    if (
        isinstance(total, int)
        and not isinstance(total, bool)
        and total > 0
        and isinstance(idle, int)
        and not isinstance(idle, bool)
    ):
        return f"Cards {idle}/{total}"
    return ""


def _instance_cards_cell(instance: dict[str, object]) -> Text | None:
    """Build the card-availability cell.

    :param instance: One instance mapping returned by the API handler.
    :returns: ``Cards <idle>/<total>`` in magenta, or red when no card is
        idle, or ``None`` when the machine does not report card counts.
    """
    cards = _format_instance_cards(instance)
    if not cards:
        return None
    idle = instance.get("gpu_idle_num")
    style = _STYLE_ERR if idle == 0 else _STYLE_NUM
    return Text(cards, style=style)


def _format_instance_spec_cell(instance: dict[str, object]) -> Text:
    """Build the Spec cell: the GPU allocation plus card availability.

    :param instance: One instance mapping returned by the API handler.
    :returns: The spec in cyan (yellow for CPU mode), with the card line
        appended when reported.
    """
    spec = _format_instance_spec(instance)
    text = Text()
    text.append(spec, style=_STYLE_WARN if spec == "CPU" else _STYLE_COLUMN)
    cards = _instance_cards_cell(instance)
    if cards is not None:
        text.append("\n")
        text.append_text(cards)
    return text


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


def _instance_billing_cell(instance: dict[str, object]) -> Text:
    """Build the billing cell: charge type plus price.

    :param instance: One instance mapping returned by the API handler.
    :returns: The charge type in dim text and the price in magenta, one per
        line.
    """
    text = Text()
    text.append(_format_value(instance.get("charge_type")), style=_STYLE_META)
    price = _format_instance_price(instance)
    if price != "-":
        text.append("\n")
        text.append(price, style=_STYLE_MONEY)
    return text


def _disk_percentages(instance: dict[str, object]) -> tuple[float | None, float | None]:
    """Return the system- and data-disk usage percentages.

    The data-disk figures only exist inside ``usage_info``; the system-disk
    rate is reported directly on the instance.

    :param instance: One instance mapping returned by the API handler.
    :returns: A ``(system, data)`` pair, with ``None`` for a missing value.
    """
    system_rate = instance.get("root_fs_used_rate")
    system = system_rate * 100 if isinstance(system_rate, (int, float)) and not isinstance(system_rate, bool) else None

    data: float | None = None
    usage = instance.get("usage_info")
    if isinstance(usage, dict):
        used = usage.get("data_disk_used_size")
        total = usage.get("data_disk_total_size")
        if isinstance(used, int) and isinstance(total, int) and total > 0:
            data = used / total * 100
    return system, data


def _disk_style(percent: float) -> str:
    """Pick a colour for a disk usage percentage.

    :param percent: Usage percentage.
    :returns: Red at or above 90%, yellow from 75%, green otherwise.
    """
    if percent >= 90:
        return _STYLE_ERR
    if percent >= 75:
        return _STYLE_WARN
    return _STYLE_OK


def _instance_disk_cell(instance: dict[str, object], *, separator: str = "\n") -> Text:
    """Build a colour-coded disk usage cell.

    :param instance: One instance mapping returned by the API handler.
    :param separator: Text placed between the system and data figures.
    :returns: The labels dimmed and each percentage coloured by severity.
    """
    system, data = _disk_percentages(instance)
    text = Text()
    for index, (label, percent) in enumerate((("Sys", system), ("Data", data))):
        if index:
            text.append(separator, style=_STYLE_META)
        text.append(f"{label} ", style=_STYLE_META)
        if percent is None:
            text.append("-", style=_STYLE_META)
        else:
            text.append(f"{percent:.2f}%", style=_disk_style(percent))
    return text


def _format_date(value: object) -> str:
    """Format an ISO 8601 timestamp as a date.

    :param value: Raw timestamp from the instance response.
    :returns: ``YYYY-MM-DD``, the untouched string when it does not parse, or
        ``"-"`` when the value is missing.
    """
    if not isinstance(value, str) or not value:
        return "-"
    try:
        return datetime.fromisoformat(value).strftime("%Y-%m-%d")
    except ValueError:
        return value


#: How long AutoDL keeps a powered-off instance before releasing it. The web
#: console counts down from ``status_at + SHUTDOWN_RETENTION``.
SHUTDOWN_RETENTION = timedelta(days=15)


def _parse_timestamp(value: object) -> datetime | None:
    """Parse an ISO 8601 timestamp.

    :param value: Raw timestamp from the instance response.
    :returns: The parsed datetime, or ``None`` when missing or invalid.
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _current_time() -> datetime:
    """Return the current local time.

    Isolated in a function so tests can freeze the release countdown.

    :returns: The current time with the local timezone attached.
    """
    return datetime.now().astimezone()


def _format_remaining(delta: timedelta) -> str:
    """Format a duration like the web console's release countdown.

    :param delta: Positive time remaining.
    :returns: ``13d 05h 38m``, ``5h 38m``, or ``38m``.
    """
    minutes = int(delta.total_seconds() // 60)
    days, remainder = divmod(minutes, 24 * 60)
    hours, minutes = divmod(remainder, 60)
    if days:
        return f"{days}d {hours:02d}h {minutes:02d}m"
    if hours:
        return f"{hours}h {minutes:02d}m"
    return f"{minutes}m"


def _format_instance_release(instance: dict[str, object], *, now: datetime | None = None) -> str:
    """Return the auto-release countdown shown by the web console.

    A powered-off instance is released if it is not powered on again within
    :data:`SHUTDOWN_RETENTION` days of its last status change. Running
    instances fall back to their expiry or rent deadline; the timed shutdown
    is a separate column built by :func:`_format_instance_stop`.

    :param instance: One instance mapping returned by the API handler.
    :param now: Current time, used by tests to freeze the countdown; defaults
        to :func:`_current_time`.
    :returns: ``in 13d 05h 38m``, ``due`` once the window has passed, or a
        ``YYYY-MM-DD`` deadline.
    """
    if instance.get("status") == "shutdown":
        status_at = _parse_timestamp(instance.get("status_at"))
        if status_at is not None:
            release_at = status_at + SHUTDOWN_RETENTION
            current = now or _current_time()
            if release_at.tzinfo is None:
                current = current.replace(tzinfo=None)
            else:
                current = current.astimezone(release_at.tzinfo)
            remaining = release_at - current
            if remaining.total_seconds() <= 0:
                return "due"
            return f"in {_format_remaining(remaining)}"

    expired_at = instance.get("expired_at")
    if isinstance(expired_at, dict) and expired_at.get("Valid"):
        return _format_date(expired_at.get("Time"))
    return _format_date(instance.get("rent_deadline"))


def _format_instance_stop(instance: dict[str, object]) -> str:
    """Return the instance's scheduled shutdown, when one is set.

    :param instance: One instance mapping returned by the API handler.
    :returns: ``"Stop YYYY-MM-DD"``, or an empty string when no timed shutdown
        is scheduled.
    """
    value = instance.get("timed_shutdown_at")
    if isinstance(value, dict) and value.get("Valid"):
        return f"Stop {_format_date(value.get('Time'))}"
    return ""


def _release_style(release: str) -> str:
    """Pick a colour for a release deadline.

    :param release: Formatted release text.
    :returns: Red when due, yellow while counting down, cyan for a date.
    """
    if release == "due":
        return _STYLE_ERR
    if release.startswith("in "):
        return _STYLE_WARN
    return _STYLE_COLUMN


def _format_instance_release_cell(instance: dict[str, object]) -> Text:
    """Build the Release cell: the release deadline plus timed shutdown.

    :param instance: One instance mapping returned by the API handler.
    :returns: The release text coloured by urgency, with the scheduled stop
        appended in yellow when set.
    """
    release = _format_instance_release(instance)
    text = Text()
    text.append(release, style=_release_style(release))
    stop = _format_instance_stop(instance)
    if stop:
        text.append("\n")
        text.append(stop, style=_STYLE_WARN)
    return text


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


def _text_width(value: str | Text) -> int:
    """Return the display width of a possibly multi-line cell.

    :param value: Cell text, plain or rich.
    :returns: The widest line's display width.
    """
    text = value.plain if isinstance(value, Text) else value
    return max((cell_len(line) for line in text.splitlines()), default=0)


def _instance_health_cell(instance: dict[str, object]) -> Text:
    """Build the disk-health cell.

    :param instance: One instance mapping returned by the API handler.
    :returns: The health string in green when normal, yellow otherwise.
    """
    health = _first_text(instance, "disk_health_status")
    if health == "-":
        return Text("-", style=_STYLE_META)
    return Text(health, style=_STYLE_OK if health.lower() in {"normal", "healthy", "ok"} else _STYLE_WARN)


def _format_instance_details(instance: dict[str, object]) -> Text:
    """Build the stacked detail cell used when the wide table cannot fit.

    :param instance: One instance mapping returned by the API handler.
    :returns: Several styled lines combining every field shown by the wide
        table.
    """
    text = Text()
    text.append(_format_instance_location(instance), style=_STYLE_META)
    name = instance.get("name")
    if isinstance(name, str) and name:
        text.append(" · ", style=_STYLE_META)
        text.append(name, style=_STYLE_LABEL)

    text.append("\nStatus ", style=_STYLE_META)
    text.append_text(_instance_status_cell(instance))
    text.append(" · Spec ", style=_STYLE_META)
    spec = _format_instance_spec(instance)
    text.append(spec, style=_STYLE_WARN if spec == "CPU" else _STYLE_COLUMN)
    cards = _instance_cards_cell(instance)
    if cards is not None:
        text.append(" · ", style=_STYLE_META)
        text.append_text(cards)

    text.append("\nDisk ", style=_STYLE_META)
    text.append_text(_instance_disk_cell(instance, separator=" / "))
    text.append(" · Health ", style=_STYLE_META)
    text.append_text(_instance_health_cell(instance))

    text.append("\nBilling ", style=_STYLE_META)
    text.append(_format_value(instance.get("charge_type")), style=_STYLE_META)
    price = _format_instance_price(instance)
    if price != "-":
        text.append(" ", style=_STYLE_META)
        text.append(price, style=_STYLE_MONEY)
    release = _format_instance_release(instance)
    text.append(" · Release ", style=_STYLE_META)
    text.append(release, style=_release_style(release))
    stop = _format_instance_stop(instance)
    if stop:
        text.append(" · ", style=_STYLE_META)
        text.append(stop, style=_STYLE_WARN)

    ssh = _format_value(instance.get("ssh_command"))
    text.append("\nSSH ", style=_STYLE_META)
    text.append(ssh, style=_STYLE_META if ssh == "-" else _STYLE_LINK)
    return text


def _render_stacked_instances(instances: Sequence[dict[str, object]]) -> None:
    """Render instances as an ID column plus stacked details.

    Used when the terminal is too narrow for even the short columns of the
    wide table, so no identifier or field is silently truncated.

    :param instances: Mappings returned by
        :func:`autodl_cli.handlers.instance.list_instances`.
    """
    table = _table(f"Instances ({len(instances)})")
    table.add_column("ID", no_wrap=True)
    table.add_column("Details")
    for instance in instances:
        table.add_row(_value_cell(instance.get("uuid"), _STYLE_COLUMN), _format_instance_details(instance))
    console.print(table)


def render_instances(instances: Sequence[dict[str, object]]) -> None:
    """Render a list of instances as a one-row-per-instance Rich table.

    The columns mirror the web console: location/ID/name, status (with an
    ``OOM`` marker), spec and the machine's free/total cards, disk, health,
    billing, release deadline with the scheduled stop, and SSH. Short columns
    keep their content width; SSH takes whatever space is left and is
    ellipsised, or omitted, on narrower terminals. If even the short columns do
    not fit, the fields are stacked under the instance ID instead. ``--json``
    callers receive the complete data.

    :param instances: Mappings returned by
        :func:`autodl_cli.handlers.instance.list_instances`.
    """
    if not instances:
        console.print("No instances found.", style=_STYLE_META)
        return

    headers = ("Instance", "Status", "Spec", "Disk", "Health", "Billing", "Release", "SSH")
    rows = [
        (
            _format_instance_title(instance),
            _instance_status_cell(instance),
            _format_instance_spec_cell(instance),
            _instance_disk_cell(instance),
            _instance_health_cell(instance),
            _instance_billing_cell(instance),
            _format_instance_release_cell(instance),
            _value_cell(instance.get("ssh_command"), _STYLE_LINK),
        )
        for instance in instances
    ]

    # Rich does not shrink no_wrap columns when the table is over-wide, so size
    # the SSH column explicitly and let it absorb the remaining width.
    content_widths = [
        max(_text_width(header), *(_text_width(row[index]) for row in rows)) for index, header in enumerate(headers)
    ]
    cell_padding = 2  # one space on each side of every cell
    border_width = 2 + len(headers) - 1  # table edges plus the inner borders
    other_width = sum(width + cell_padding for width in content_widths[:-1])
    ssh_width = max(1, console.width - border_width - other_width - cell_padding)
    # Keep the column only while ``ssh -p …`` (8 cells) still fits; a shorter
    # column would show little beyond the ellipsis.
    include_ssh = ssh_width >= 8

    if other_width + border_width - 1 > console.width:
        _render_stacked_instances(instances)
        return

    table = _table(f"Instances ({len(instances)})")
    for header in headers:
        if header == "SSH":
            if include_ssh:
                table.add_column(header, max_width=ssh_width, no_wrap=True)
            continue
        table.add_column(header, no_wrap=True)
    for row in rows:
        table.add_row(*(row if include_ssh else row[:-1]))

    console.print(table)


def _format_detail_gpu(detail: dict[str, object], machine: dict[str, object]) -> str:
    """Return the instance's GPU model, with its vendor when reported.

    The user-defined alias wins, then the snapshot alias, then the machine's
    GPU type.

    :param detail: Snapshot mapping returned by the API handler.
    :param machine: The snapshot's ``machine_info_snapshot`` mapping.
    :returns: ``"RTX 3090 (nvidia)"`` or ``"-"`` when no GPU is reported.
    """
    name = _first_text(detail, "user_define_gpu_name", "snapshot_gpu_alias_name")
    if name == "-":
        gpu_type = machine.get("gpu_type")
        if isinstance(gpu_type, dict):
            value = gpu_type.get("name")
            if isinstance(value, str) and value:
                name = value
    if name == "-":
        return "-"

    chip_corp = detail.get("chip_corp")
    if isinstance(chip_corp, str) and chip_corp:
        return f"{name} ({chip_corp})"
    return name


def _format_detail_gpu_memory(machine: dict[str, object]) -> str:
    """Return the per-GPU memory reported by the machine.

    :param machine: The snapshot's ``machine_info_snapshot`` mapping.
    :returns: A byte count such as ``"24G"``, or ``"-"``.
    """
    gpu_type = machine.get("gpu_type")
    if not isinstance(gpu_type, dict):
        return "-"
    return _format_gib(gpu_type.get("memory"))


def _format_detail_price(detail: dict[str, object]) -> str:
    """Format the hourly price and the undiscounted list price.

    :param detail: Snapshot mapping returned by the API handler.
    :returns: ``"¥1.480/h (list ¥1.560/h)"``, or ``"-"`` when no price is
        reported.
    """
    price = detail.get("payg_price")
    if isinstance(price, bool) or not isinstance(price, int) or price <= 0:
        return "-"

    text = f"{_format_yuan(price)}/h"
    origin = detail.get("origin_pay_price")
    if isinstance(origin, int) and not isinstance(origin, bool) and origin > 0 and origin != price:
        text = f"{text} (list {_format_yuan(origin)}/h)"
    return text


def _format_detail_framework(image: dict[str, object]) -> str:
    """Join the image's framework name and version.

    :param image: The snapshot's ``image`` mapping.
    :returns: ``"PyTorch 2.12.1"``, or whichever part is present.
    """
    name = image.get("framework_name")
    version = image.get("framework_version")
    if isinstance(name, str) and name and isinstance(version, str) and version:
        return f"{name} {version}"
    if isinstance(name, str) and name:
        return name
    if isinstance(version, str) and version:
        return version
    return "-"


def _format_detail_region(machine: dict[str, object]) -> str:
    """Return the region name with its sign in parentheses.

    :param machine: The snapshot's ``machine_info_snapshot`` mapping.
    :returns: ``"内蒙B区 (nm-B2)"``, or whichever part is present.
    """
    name = _format_value(machine.get("region_name"))
    sign = machine.get("region_sign")
    if name != "-" and isinstance(sign, str) and sign:
        return f"{name} ({sign})"
    return name


def _format_detail_cpu_cores(machine: dict[str, object]) -> str:
    """Format the machine's used and total CPU cores.

    :param machine: The snapshot's ``machine_info_snapshot`` mapping.
    :returns: ``"14 used / 112 total"``, or ``"-"`` when the counts are missing.
    """
    total = machine.get("cpu_num")
    used = machine.get("cpu_used")
    if (
        isinstance(total, int)
        and not isinstance(total, bool)
        and total > 0
        and isinstance(used, int)
        and not isinstance(used, bool)
    ):
        return f"{used} used / {total} total"
    return "-"


def _format_detail_memory(machine: dict[str, object]) -> str:
    """Format the machine's used and total memory.

    :param machine: The snapshot's ``machine_info_snapshot`` mapping.
    :returns: ``"60G / 503G"``, or ``"-"`` when no total is reported.
    """
    total = machine.get("memory")
    used = machine.get("mem_used")
    if (
        isinstance(total, int)
        and not isinstance(total, bool)
        and total > 0
        and isinstance(used, int)
        and not isinstance(used, bool)
    ):
        return f"{_format_gib(used)} / {_format_gib(total)}"
    return _format_gib(total)


def _format_detail_machine_disk(machine: dict[str, object]) -> str:
    """Format the host machine's disk size and type.

    :param machine: The snapshot's ``machine_info_snapshot`` mapping.
    :returns: ``"7.0T SSD"``, ``"50G"``, or ``"-"``.
    """
    size = _format_gib(machine.get("disk_size"))
    if size == "-":
        return size
    disk_type = machine.get("disk_type")
    if isinstance(disk_type, str) and disk_type:
        return f"{size} {disk_type}"
    return size


def _format_yes_no(value: object) -> str:
    """Format an optional boolean as ``yes`` or ``no``.

    :param value: Field value from the API response.
    :returns: ``"yes"``/``"no"`` for booleans, otherwise :func:`_format_value`.
    """
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return _format_value(value)


def _detail_value_style(label: str, text: str) -> str:
    """Pick a colour for one instance-detail value.

    :param label: Field label.
    :param text: Already-formatted value.
    :returns: A style name.
    """
    if label == "Restarted":
        return _STYLE_META
    if label == "NVIDIA Docker":
        return _STYLE_OK if text == "yes" else _STYLE_WARN
    if label == "Price":
        return _STYLE_MONEY
    if label in ("GPU memory", "CPU cores", "Memory", "Machine disk", "Instance disk limit", "Writable now"):
        return _STYLE_NUM
    return _STYLE_COLUMN


def render_instance_detail(detail: dict[str, object], *, instance_uuid: str | None = None) -> None:
    """Render one instance's configuration snapshot as a Rich table.

    Fields are grouped into Instance, Image, and Machine sections; a section is
    omitted when every field in it is missing. Values are kept human-readable
    (yuan prices, GiB sizes), so ``--json`` callers receive the untouched API
    response instead.

    :param detail: Snapshot mapping returned by
        :func:`autodl_cli.handlers.instance.get_instance`.
    :param instance_uuid: UUID the snapshot was requested for, when known.
    """
    image = detail.get("image")
    if not isinstance(image, dict):
        image = {}
    machine = detail.get("machine_info_snapshot")
    if not isinstance(machine, dict):
        machine = {}

    # Build every section first so empty ones are not printed as bare headers.
    sections: list[tuple[str, list[tuple[str, str]]]] = [
        ("Instance", []),
        ("Image", []),
        ("Machine", []),
    ]
    instance_rows, image_rows, machine_rows = (rows for _, rows in sections)

    base_image = image.get("base_image_uuid")
    if base_image == image.get("image_name"):
        base_image = None

    rows: tuple[tuple[list[tuple[str, str]], str, object], ...] = (
        (instance_rows, "UUID", instance_uuid),
        (instance_rows, "GPU", _format_detail_gpu(detail, machine)),
        (instance_rows, "GPU memory", _format_detail_gpu_memory(machine)),
        (instance_rows, "Price", _format_detail_price(detail)),
        (instance_rows, "Architecture", detail.get("cpu_arch")),
        (image_rows, "Image name", image.get("image_name")),
        (image_rows, "Base image", base_image),
        (image_rows, "Framework", _format_detail_framework(image)),
        (image_rows, "Python", image.get("python_version")),
        (image_rows, "CUDA", image.get("cuda_version")),
        (image_rows, "Image type", image.get("image_type")),
        (machine_rows, "Region", _format_detail_region(machine)),
        (machine_rows, "Data center", machine.get("data_center")),
        (machine_rows, "CPU", machine.get("cpu_name")),
        (machine_rows, "CPU cores", _format_detail_cpu_cores(machine)),
        (machine_rows, "Memory", _format_detail_memory(machine)),
        (machine_rows, "Machine disk", _format_detail_machine_disk(machine)),
        (machine_rows, "Instance disk limit", _format_gib(machine.get("max_instance_disk_size"))),
        (machine_rows, "Writable now", _format_gib(detail.get("max_writable_size_in_byte"))),
        (machine_rows, "OS", machine.get("os_name")),
        (machine_rows, "Docker", machine.get("docker_version")),
        (machine_rows, "Kernel", machine.get("kernel_version")),
        (machine_rows, "NVIDIA Docker", _format_yes_no(machine.get("nvidia_docker"))),
        (machine_rows, "IP address", machine.get("ip_address")),
        (machine_rows, "Restarted", _format_timestamp(machine.get("restart_time"))),
    )
    for target, label, value in rows:
        text = _format_value(value)
        if text != "-":
            target.append((label, text))

    title = "Instance detail" if not instance_uuid else f"Instance {instance_uuid}"
    table = _table(title)
    table.add_column("Field")
    table.add_column("Value")
    for section, section_rows in sections:
        if not section_rows:
            continue
        table.add_row(Text(section, style=_STYLE_TITLE), "")
        for label, value in section_rows:
            table.add_row(_styled(label, _STYLE_LABEL), _styled(value, _detail_value_style(label, value)))

    console.print(table)


def render_regions(regions: Sequence[dict[str, object]]) -> None:
    """Render the region catalogue as a Rich table.

    The signs column lists every region sign grouped under the data center, so
    any of them can be passed to ``--region``; a trailing hint says so.
    ``--json`` callers receive the complete handler result instead.

    :param regions: Mappings returned by
        :func:`autodl_cli.handlers.gpu.list_regions`.
    """
    if not regions:
        console.print("No regions found.", style=_STYLE_META)
        return

    table = _table("Available regions")
    table.add_column("Region")
    table.add_column("Data center")
    table.add_column("Signs")
    for region in regions:
        signs = region.get("region_signs")
        sign_text = ", ".join(sign for sign in signs if isinstance(sign, str)) if isinstance(signs, list) else ""
        table.add_row(
            _value_cell(region.get("region_name"), _STYLE_COLUMN),
            _value_cell(region.get("data_center"), _STYLE_COLUMN),
            _value_cell(sign_text, _STYLE_WARN),
        )
    console.print(table)
    console.print("Pick a sign from the Signs column and pass it to -r/--region.", style=_STYLE_META)


def render_gpu_availability(regions: Sequence[dict[str, object]]) -> None:
    """Render GPU availability by region as a Rich table.

    A region with no GPU types still gets a row, with ``"-"`` in every column
    after the region name. ``--json`` callers receive the complete handler
    result instead.

    :param regions: Mappings returned by
        :func:`autodl_cli.handlers.gpu.list_gpu_availability`.
    """
    if not regions:
        console.print("No GPU availability found.", style=_STYLE_META)
        return

    table = _table("GPU availability")
    table.add_column("Region")
    table.add_column("GPU")
    table.add_column("Idle", justify="right")
    table.add_column("Total", justify="right")
    table.add_column("Chip")
    for region in regions:
        region_name = _format_value(region.get("region_name"))
        gpus = region.get("gpus")
        if not isinstance(gpus, list) or not gpus:
            table.add_row(
                _styled(region_name, _STYLE_COLUMN),
                _styled("-", _STYLE_META),
                _styled("-", _STYLE_META),
                _styled("-", _STYLE_META),
                _styled("-", _STYLE_META),
            )
            continue
        for gpu in gpus:
            if not isinstance(gpu, dict):
                continue
            table.add_row(
                _styled(region_name, _STYLE_COLUMN),
                _value_cell(gpu.get("gpu_type"), _STYLE_LABEL),
                _count_cell(gpu.get("idle_gpu_num"), alert_zero=True),
                _count_cell(gpu.get("total_gpu_num")),
                _value_cell(gpu.get("chip_corp"), _STYLE_META),
            )
    console.print(table)


def render_gpu_matches(matches: Sequence[dict[str, object]]) -> None:
    """Render a flat GPU search result as a Rich table.

    Each match already names its region, so the region is a column rather than
    a section heading. ``--json`` callers receive the complete handler result
    instead.

    :param matches: Mappings returned by
        :func:`autodl_cli.handlers.gpu.find_gpu`.
    """
    if not matches:
        console.print("No matching GPUs found.", style=_STYLE_META)
        return

    table = _table(f"Matching GPUs ({len(matches)})")
    table.add_column("Region")
    table.add_column("GPU")
    table.add_column("Idle", justify="right")
    table.add_column("Total", justify="right")
    table.add_column("Chip")
    for gpu in matches:
        table.add_row(
            _value_cell(gpu.get("region_name"), _STYLE_COLUMN),
            _value_cell(gpu.get("gpu_type"), _STYLE_LABEL),
            _count_cell(gpu.get("idle_gpu_num"), alert_zero=True),
            _count_cell(gpu.get("total_gpu_num")),
            _value_cell(gpu.get("chip_corp"), _STYLE_META),
        )
    console.print(table)


def _format_image_name(image: Mapping[str, object]) -> str:
    """Join an image's framework name and version.

    :param image: One mapping returned by
        :func:`autodl_cli.handlers.image.list_images`.
    :returns: ``"PyTorch 2.12.1"``, or whichever part is present.
    """
    framework = _format_value(image.get("framework_name"))
    version = image.get("framework_version")
    if isinstance(version, str) and version:
        return f"{framework} {version}"
    return framework


def _image_name_cell(image: Mapping[str, object]) -> Text:
    """Build the image cell: framework name and version, plus a desktop marker.

    :param image: One image mapping.
    :returns: The name in bold, with ``" (desktop)"`` in yellow when the image
        runs a desktop environment.
    """
    text = Text(_format_image_name(image), style=_STYLE_LABEL)
    if image.get("is_desktop") is True:
        text.append(" (desktop)", style=_STYLE_WARN)
    return text


#: Image table columns, in display order.
_IMAGE_HEADERS: tuple[str, ...] = ("Image", "Python", "CUDA", "Chip", "Arch", "UUID")


def _image_row(image: Mapping[str, object]) -> tuple[Text, ...]:
    """Build one row of the wide image table.

    :param image: One mapping returned by
        :func:`autodl_cli.handlers.image.list_images`.
    :returns: One styled cell per entry of :data:`_IMAGE_HEADERS`.
    """
    return (
        _image_name_cell(image),
        _value_cell(image.get("python_version"), _STYLE_COLUMN),
        _value_cell(image.get("cuda_version"), _STYLE_NUM),
        _value_cell(image.get("chip_corp"), _STYLE_META),
        _value_cell(image.get("cpu_arch"), _STYLE_META),
        _value_cell(image.get("image_uuid"), _STYLE_COLUMN),
    )


def _format_image_details(image: Mapping[str, object]) -> Text:
    """Build the stacked detail cell used when the wide table cannot fit.

    :param image: One image mapping.
    :returns: Three styled lines combining every field shown by the wide
        table.
    """
    text = Text()
    text.append_text(_image_name_cell(image))
    text.append("\n")
    text.append("Python ", style=_STYLE_META)
    text.append(_format_value(image.get("python_version")), style=_STYLE_COLUMN)
    text.append(" · CUDA ", style=_STYLE_META)
    text.append(_format_value(image.get("cuda_version")), style=_STYLE_NUM)
    text.append("\n")
    text.append(_format_value(image.get("chip_corp")), style=_STYLE_META)
    text.append(" · ", style=_STYLE_META)
    text.append(_format_value(image.get("cpu_arch")), style=_STYLE_META)
    text.append(" · ", style=_STYLE_META)
    text.append(_format_value(image.get("image_uuid")), style=_STYLE_COLUMN)
    return text


def _render_stacked_images(images: Sequence[dict[str, object]]) -> None:
    """Render images as a single stacked-details column.

    Used when the terminal is too narrow for the wide table, so no field is
    silently truncated.

    :param images: Mappings returned by
        :func:`autodl_cli.handlers.image.list_images`.
    """
    table = _table(f"Base images ({len(images)})")
    table.add_column("Details")
    for image in images:
        table.add_row(_format_image_details(image))
    console.print(table)


def render_images(images: Sequence[dict[str, object]]) -> None:
    """Render the base-image catalogue as a Rich table.

    Each row is one selectable image. The wide table shows the framework and
    version, Python/OS, CUDA, chip vendor, CPU architecture, and the UUID used
    when ordering; when it does not fit the terminal, the fields are stacked
    under the image name instead. ``--json`` callers receive the complete
    handler result.

    :param images: Mappings returned by
        :func:`autodl_cli.handlers.image.list_images`.
    """
    if not images:
        console.print("No images found.", style=_STYLE_META)
        return

    rows = [_image_row(image) for image in images]

    # Rich shrinks columns until their content is ellipsised, so check whether
    # the natural table width fits before drawing it.
    content_widths = [
        max(_text_width(header), *(_text_width(row[index]) for row in rows))
        for index, header in enumerate(_IMAGE_HEADERS)
    ]
    cell_padding = 2  # one space on each side of every cell
    border_width = 2 + len(_IMAGE_HEADERS) - 1  # table edges plus the inner borders
    if sum(width + cell_padding for width in content_widths) + border_width > console.width:
        _render_stacked_images(images)
        return

    table = _table(f"Base images ({len(images)})")
    for header in _IMAGE_HEADERS:
        table.add_column(header, justify="right" if header == "CUDA" else "left")
    for row in rows:
        table.add_row(*row)

    console.print(table)


def _format_gib(value: object) -> str:
    """Format a byte count for the machine table.

    :param value: Raw byte count from the machine response.
    :returns: ``"62G"``, ``"1.5T"``, or ``"-"`` when the value is not a
        positive integer.
    """
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return "-"
    gib = value / (1024**3)
    if gib >= 1024:
        return f"{gib / 1024:.1f}T"
    return f"{gib:.0f}G"


def _machine_region_cell(machine: dict[str, object]) -> Text:
    """Build the region cell: region over its sign.

    :param machine: One machine mapping.
    :returns: The region in cyan with the sign dimmed on a second line.
    """
    text = Text()
    text.append(_format_value(machine.get("region_name")), style=_STYLE_COLUMN)
    sign = machine.get("region_sign")
    if isinstance(sign, str) and sign:
        text.append("\n")
        text.append(sign, style=_STYLE_META)
    return text


def _machine_title_cell(machine: dict[str, object]) -> Text:
    """Build the identifier cell: alias (or name) over the machine ID.

    :param machine: One machine mapping.
    :returns: The alias in bold with the machine ID dimmed on a second line.
    """
    alias = machine.get("machine_alias")
    header = alias if isinstance(alias, str) and alias else _format_value(machine.get("machine_name"))
    text = Text()
    text.append(header, style=_STYLE_LABEL)
    machine_id = machine.get("machine_id")
    if isinstance(machine_id, str) and machine_id:
        text.append("\n")
        text.append(machine_id, style=_STYLE_META)
    return text


def _machine_idle_cell(machine: dict[str, object]) -> Text:
    """Build the ``idle/total`` stock cell.

    :param machine: One machine mapping.
    :returns: The idle count in red when zero, magenta otherwise, with the
        total count dimmed.
    """
    idle = _format_value(machine.get("gpu_idle_num"))
    total = _format_value(machine.get("gpu_number"))
    if idle == "-":
        idle_style = _STYLE_META
    elif idle == "0":
        idle_style = _STYLE_ERR
    else:
        idle_style = _STYLE_NUM
    text = Text()
    text.append(idle, style=idle_style)
    text.append(f"/{total}", style=_STYLE_META)
    return text


def _format_machine_spec(machine: dict[str, object]) -> str:
    """Format the per-GPU CPU and memory allocation.

    :param machine: One machine mapping.
    :returns: ``"12c/62G"``, with ``"-"`` for a missing part.
    """
    cpu = machine.get("cpu_per_gpu")
    cpu_text = f"{cpu}c" if isinstance(cpu, int) and not isinstance(cpu, bool) and cpu > 0 else "-"
    return f"{cpu_text}/{_format_gib(machine.get('mem_per_gpu'))}"


def _format_machine_price(machine: dict[str, object], key: str) -> str:
    """Format a raw thousandths-of-a-yuan price.

    :param machine: One machine mapping.
    :param key: Price field name.
    :returns: A ``¥`` amount, or ``"-"`` when the price is missing.
    """
    return _format_yuan(machine.get(key))


def _render_machine_page_footer(page: Mapping[str, object]) -> None:
    """Print the pagination summary below the machine table.

    :param page: The mapping returned by
        :func:`autodl_cli.handlers.gpu.list_machines`.
    """
    total = _format_value(page.get("result_total"))
    max_page = page.get("max_page")
    if page.get("all_pages"):
        console.print(f"Showing every page ({total} machines).", style=_STYLE_META)
        return
    if isinstance(max_page, int) and not isinstance(max_page, bool) and max_page > 1:
        console.print(
            f"Page {_format_value(page.get('page_index'))}/{max_page} · {total} machines · "
            "use --page, --page-size, or --all.",
            style=_STYLE_META,
        )
        return
    console.print(f"{total} machines.", style=_STYLE_META)


#: Machine table columns, in display order.
_MACHINE_HEADERS: tuple[str, ...] = (
    "Region",
    "Machine",
    "GPU",
    "Idle",
    "¥/h",
    "¥/day",
    "CPU/RAM",
    "Disk",
    "CUDA",
)


def _machine_row(machine: dict[str, object]) -> tuple[Text, ...]:
    """Build one row of the wide machine table.

    :param machine: One mapping returned by
        :func:`autodl_cli.handlers.gpu.list_machines`.
    :returns: One styled cell per entry of :data:`_MACHINE_HEADERS`.
    """
    return (
        _machine_region_cell(machine),
        _machine_title_cell(machine),
        _value_cell(machine.get("gpu_name"), _STYLE_COLUMN),
        _machine_idle_cell(machine),
        _value_cell(_format_machine_price(machine, "payg_price"), _STYLE_MONEY),
        _value_cell(_format_machine_price(machine, "daily_price"), _STYLE_MONEY),
        _value_cell(_format_machine_spec(machine), _STYLE_NUM),
        _value_cell(_format_gib(machine.get("max_instance_disk_size")), _STYLE_NUM),
        _value_cell(machine.get("highest_cuda_version"), _STYLE_META),
    )


def _format_machine_details(machine: dict[str, object]) -> Text:
    """Build the stacked detail cell used when the wide table cannot fit.

    :param machine: One machine mapping.
    :returns: Three styled lines combining every field shown by the wide
        table.
    """
    region = _format_value(machine.get("region_name"))
    sign = machine.get("region_sign")
    if isinstance(sign, str) and sign:
        region = f"{region} ({sign})"
    alias = machine.get("machine_alias")
    label = alias if isinstance(alias, str) and alias else _format_value(machine.get("machine_name"))
    machine_id = machine.get("machine_id")
    if isinstance(machine_id, str) and machine_id:
        label = f"{label} ({machine_id})"

    total = _format_value(machine.get("gpu_number"))
    text = Text()
    text.append(region, style=_STYLE_COLUMN)
    text.append(" · ", style=_STYLE_META)
    text.append(label, style=_STYLE_LABEL)
    text.append("\n")
    text.append(_format_value(machine.get("gpu_name")), style=_STYLE_COLUMN)
    text.append(f" ×{total}", style=_STYLE_NUM)
    text.append(" · Idle ", style=_STYLE_META)
    text.append_text(_machine_idle_cell(machine))
    text.append(" · CUDA ", style=_STYLE_META)
    text.append(_format_value(machine.get("highest_cuda_version")), style=_STYLE_META)
    text.append("\n")
    text.append(_format_machine_price(machine, "payg_price"), style=_STYLE_MONEY)
    text.append("/h · ", style=_STYLE_META)
    text.append(_format_machine_price(machine, "daily_price"), style=_STYLE_MONEY)
    text.append("/day · ", style=_STYLE_META)
    text.append(_format_machine_spec(machine), style=_STYLE_NUM)
    text.append(" · Disk ", style=_STYLE_META)
    text.append(_format_gib(machine.get("max_instance_disk_size")), style=_STYLE_NUM)
    return text


def _render_stacked_machines(machines: Sequence[dict[str, object]]) -> None:
    """Render machines as a single stacked-details column.

    Used when the terminal is too narrow for the wide table, so no field is
    silently truncated.

    :param machines: Mappings returned by
        :func:`autodl_cli.handlers.gpu.list_machines`.
    """
    table = _table(f"GPU machines ({len(machines)})")
    table.add_column("Details")
    for machine in machines:
        table.add_row(_format_machine_details(machine))
    console.print(table)


def render_gpu_machines(page: Mapping[str, object]) -> None:
    """Render a machine-listing page as a Rich table.

    The table shows the per-machine GPU stock, pay-as-you-go and daily prices,
    per-GPU CPU/memory allocation, instance disk limit, and CUDA version. When
    the table does not fit the terminal, every field is stacked under a single
    details column instead. ``--json`` callers receive the complete handler
    result instead.

    :param page: The mapping returned by
        :func:`autodl_cli.handlers.gpu.list_machines`.
    """
    entries = page.get("machines")
    if not isinstance(entries, list) or not entries:
        console.print("No matching machines found.", style=_STYLE_META)
        return

    machines = [machine for machine in entries if isinstance(machine, dict)]
    if not machines:
        console.print("No matching machines found.", style=_STYLE_META)
        return
    rows = [_machine_row(machine) for machine in machines]

    # Rich shrinks columns until their content is ellipsised, so check whether
    # the natural table width fits before drawing it.
    content_widths = [
        max(_text_width(header), *(_text_width(row[index]) for row in rows))
        for index, header in enumerate(_MACHINE_HEADERS)
    ]
    cell_padding = 2  # one space on each side of every cell
    border_width = 2 + len(_MACHINE_HEADERS) - 1  # table edges plus the inner borders
    if sum(width + cell_padding for width in content_widths) + border_width > console.width:
        _render_stacked_machines(machines)
        _render_machine_page_footer(page)
        return

    table = _table(f"GPU machines ({len(machines)})")
    for header in _MACHINE_HEADERS:
        right_aligned = header not in ("Region", "Machine", "GPU", "CUDA")
        table.add_column(header, justify="right" if right_aligned else "left")
    for row in rows:
        table.add_row(*row)

    console.print(table)
    _render_machine_page_footer(page)


def success(message: str) -> None:
    """Print a success message.

    :param message: Text to display.
    """
    console.print(message, style=_STYLE_OK, markup=False)


def info(message: str) -> None:
    """Print an informational message.

    :param message: Text to display.
    """
    console.print(message, style=_STYLE_META, markup=False)


def warning(message: str) -> None:
    """Print a warning message.

    :param message: Text to display.
    """
    console.print(message, style=_STYLE_WARN, markup=False)


def error(message: str) -> None:
    """Print an error message on stderr.

    :param message: Text to display.
    """
    console.print(message, style=_STYLE_ERR, stderr=True, markup=False)
