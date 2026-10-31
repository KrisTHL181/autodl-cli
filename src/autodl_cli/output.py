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

from rich.cells import cell_len
from rich.console import Console
from rich.table import Table

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

#: Shared console; Rich disables colour automatically when stdout is not a TTY.
console = Console()


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


def _format_instance_title(instance: dict[str, object]) -> str:
    """Build the multi-line identifier cell of the wide table.

    :param instance: One instance mapping returned by the API handler.
    :returns: Location, UUID, and name (when set), one per line.
    """
    lines = [_format_instance_location(instance), _format_value(instance.get("uuid"))]
    name = instance.get("name")
    if isinstance(name, str) and name:
        lines.append(name)
    return "\n".join(lines)


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


def _format_instance_spec(instance: dict[str, object]) -> str:
    """Describe the GPU allocation as the web console does.

    :param instance: One instance mapping returned by the API handler.
    :returns: The GPU alias and requested count (``"RTX 3090 ×1"``), ``"CPU"``
        for a CPU-only instance, or ``"-"``.
    """
    name = instance.get("user_define_gpu_name") or instance.get("snapshot_gpu_alias_name")
    if not isinstance(name, str) or not name:
        return "CPU" if instance.get("start_mode") == "non_gpu" else "-"
    amount = instance.get("req_gpu_amount")
    if isinstance(amount, int) and not isinstance(amount, bool) and amount > 0:
        return f"{name} ×{amount}"
    return name


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


def _format_instance_billing(instance: dict[str, object]) -> str:
    """Format the billing mode and price.

    :param instance: One instance mapping returned by the API handler.
    :returns: The charge type, plus the price on a second line when one is
        reported.
    """
    lines = [_format_value(instance.get("charge_type"))]
    price = _format_instance_price(instance)
    if price != "-":
        lines.append(price)
    return "\n".join(lines)


def _format_instance_disk(instance: dict[str, object]) -> str:
    """Format system and data disk usage as two lines of percentages.

    The data-disk figures only exist inside ``usage_info``; the system-disk
    rate is reported directly on the instance.

    :param instance: One instance mapping returned by the API handler.
    :returns: ``Sys NN.NN%`` and ``Data NN.NN%`` lines.
    """
    system_rate = instance.get("root_fs_used_rate")
    if isinstance(system_rate, (int, float)) and not isinstance(system_rate, bool):
        system = f"Sys {system_rate * 100:.2f}%"
    else:
        system = "Sys -"

    data = "-"
    usage = instance.get("usage_info")
    if isinstance(usage, dict):
        used = usage.get("data_disk_used_size")
        total = usage.get("data_disk_total_size")
        if isinstance(used, int) and isinstance(total, int) and total > 0:
            data = f"{used / total * 100:.2f}%"
    return f"{system}\nData {data}"


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
    instances fall back to the scheduled stop, expiry, or rent deadline.

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

    for key in ("timed_shutdown_at", "expired_at"):
        value = instance.get(key)
        if isinstance(value, dict) and value.get("Valid"):
            return _format_date(value.get("Time"))
    return _format_date(instance.get("rent_deadline"))


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


def _text_width(value: str) -> int:
    """Return the display width of a possibly multi-line cell.

    :param value: Cell text.
    :returns: The widest line's display width.
    """
    return max((cell_len(line) for line in value.splitlines()), default=0)


def _format_instance_details(instance: dict[str, object]) -> str:
    """Build the stacked detail cell used when the wide table cannot fit.

    :param instance: One instance mapping returned by the API handler.
    :returns: Several lines combining every field shown by the wide table.
    """
    location = _format_instance_location(instance)
    name = instance.get("name")
    header = f"{location} · {name}" if isinstance(name, str) and name else location

    disk = _format_instance_disk(instance).replace("\n", " / ")
    billing = _format_instance_billing(instance).replace("\n", " ")
    lines = (
        header,
        f"Status {_format_instance_status(instance)} · Spec {_format_instance_spec(instance)}",
        f"Disk {disk} · Health {_first_text(instance, 'disk_health_status')}",
        f"Billing {billing} · Release {_format_instance_release(instance)}",
        f"SSH {_format_value(instance.get('ssh_command'))}",
    )
    return "\n".join(lines)


def _render_stacked_instances(instances: Sequence[dict[str, object]]) -> None:
    """Render instances as an ID column plus stacked details.

    Used when the terminal is too narrow for even the short columns of the
    wide table, so no identifier or field is silently truncated.

    :param instances: Mappings returned by
        :func:`autodl_cli.handlers.instance.list_instances`.
    """
    table = Table(title=f"Instances ({len(instances)})")
    table.add_column("ID", no_wrap=True)
    table.add_column("Details")
    for instance in instances:
        table.add_row(_format_value(instance.get("uuid")), _format_instance_details(instance))
    console.print(table)


def render_instances(instances: Sequence[dict[str, object]]) -> None:
    """Render a list of instances as a one-row-per-instance Rich table.

    The columns mirror the web console: location/ID/name, status, spec, disk,
    health, billing, release deadline, and SSH. Short columns keep their
    content width; SSH takes whatever space is left and is ellipsised, or
    omitted, on narrower terminals. If even the short columns do not fit, the
    fields are stacked under the instance ID instead. ``--json`` callers
    receive the complete data.

    :param instances: Mappings returned by
        :func:`autodl_cli.handlers.instance.list_instances`.
    """
    if not instances:
        console.print("No instances found.")
        return

    headers = ("Instance", "Status", "Spec", "Disk", "Health", "Billing", "Release", "SSH")
    rows = [
        (
            _format_instance_title(instance),
            _format_instance_status(instance),
            _format_instance_spec(instance),
            _format_instance_disk(instance),
            _first_text(instance, "disk_health_status"),
            _format_instance_billing(instance),
            _format_instance_release(instance),
            _format_value(instance.get("ssh_command")),
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

    table = Table(title=f"Instances ({len(instances)})")
    for header in headers:
        if header == "SSH":
            if include_ssh:
                table.add_column(header, max_width=ssh_width, no_wrap=True)
            continue
        table.add_column(header, no_wrap=True)
    for row in rows:
        table.add_row(*(row if include_ssh else row[:-1]))

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
        console.print("No regions found.")
        return

    table = Table(title="Available regions")
    table.add_column("Region")
    table.add_column("Data center")
    table.add_column("Signs")
    for region in regions:
        signs = region.get("region_signs")
        sign_text = ", ".join(sign for sign in signs if isinstance(sign, str)) if isinstance(signs, list) else ""
        table.add_row(
            _format_value(region.get("region_name")),
            _format_value(region.get("data_center")),
            _format_value(sign_text),
        )
    console.print(table)
    console.print("Pick a sign from the Signs column and pass it to -r/--region.", style="dim")


def render_gpu_availability(regions: Sequence[dict[str, object]]) -> None:
    """Render GPU availability by region as a Rich table.

    A region with no GPU types still gets a row, with ``"-"`` in every column
    after the region name. ``--json`` callers receive the complete handler
    result instead.

    :param regions: Mappings returned by
        :func:`autodl_cli.handlers.gpu.list_gpu_availability`.
    """
    if not regions:
        console.print("No GPU availability found.")
        return

    table = Table(title="GPU availability")
    table.add_column("Region")
    table.add_column("GPU")
    table.add_column("Idle", justify="right")
    table.add_column("Total", justify="right")
    table.add_column("Chip")
    for region in regions:
        region_name = _format_value(region.get("region_name"))
        gpus = region.get("gpus")
        if not isinstance(gpus, list) or not gpus:
            table.add_row(region_name, "-", "-", "-", "-")
            continue
        for gpu in gpus:
            if not isinstance(gpu, dict):
                continue
            table.add_row(
                region_name,
                _format_value(gpu.get("gpu_type")),
                _format_value(gpu.get("idle_gpu_num")),
                _format_value(gpu.get("total_gpu_num")),
                _format_value(gpu.get("chip_corp")),
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
        console.print("No matching GPUs found.")
        return

    table = Table(title=f"Matching GPUs ({len(matches)})")
    table.add_column("Region")
    table.add_column("GPU")
    table.add_column("Idle", justify="right")
    table.add_column("Total", justify="right")
    table.add_column("Chip")
    for gpu in matches:
        table.add_row(
            _format_value(gpu.get("region_name")),
            _format_value(gpu.get("gpu_type")),
            _format_value(gpu.get("idle_gpu_num")),
            _format_value(gpu.get("total_gpu_num")),
            _format_value(gpu.get("chip_corp")),
        )
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


def _format_machine_region(machine: dict[str, object]) -> str:
    """Return the region name with its sign on a second line.

    :param machine: One mapping returned by
        :func:`autodl_cli.handlers.gpu.list_machines`.
    :returns: ``"北京B区\\nbj-B1"``, or whichever part is present.
    """
    region = _format_value(machine.get("region_name"))
    sign = machine.get("region_sign")
    if isinstance(sign, str) and sign:
        return f"{region}\n{sign}"
    return region


def _format_machine_title(machine: dict[str, object]) -> str:
    """Build the identifier cell: alias (or name) over the machine ID.

    :param machine: One machine mapping.
    :returns: The two-line identifier.
    """
    alias = machine.get("machine_alias")
    header = alias if isinstance(alias, str) and alias else _format_value(machine.get("machine_name"))
    machine_id = machine.get("machine_id")
    if isinstance(machine_id, str) and machine_id:
        return f"{header}\n{machine_id}"
    return header


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
        console.print(f"Showing every page ({total} machines).", style="dim")
        return
    if isinstance(max_page, int) and not isinstance(max_page, bool) and max_page > 1:
        console.print(
            f"Page {_format_value(page.get('page_index'))}/{max_page} · {total} machines · "
            "use --page, --page-size, or --all.",
            style="dim",
        )
        return
    console.print(f"{total} machines.", style="dim")


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


def _machine_row(machine: dict[str, object]) -> tuple[str, ...]:
    """Build one row of the wide machine table.

    :param machine: One mapping returned by
        :func:`autodl_cli.handlers.gpu.list_machines`.
    :returns: One cell per entry of :data:`_MACHINE_HEADERS`.
    """
    idle = _format_value(machine.get("gpu_idle_num"))
    total = _format_value(machine.get("gpu_number"))
    return (
        _format_machine_region(machine),
        _format_machine_title(machine),
        _format_value(machine.get("gpu_name")),
        f"{idle}/{total}",
        _format_machine_price(machine, "payg_price"),
        _format_machine_price(machine, "daily_price"),
        _format_machine_spec(machine),
        _format_gib(machine.get("max_instance_disk_size")),
        _format_value(machine.get("highest_cuda_version")),
    )


def _format_machine_details(machine: dict[str, object]) -> str:
    """Build the stacked detail cell used when the wide table cannot fit.

    :param machine: One machine mapping.
    :returns: Three lines combining every field shown by the wide table.
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

    idle = _format_value(machine.get("gpu_idle_num"))
    total = _format_value(machine.get("gpu_number"))
    gpu = _format_value(machine.get("gpu_name"))
    cuda = _format_value(machine.get("highest_cuda_version"))
    payg = _format_machine_price(machine, "payg_price")
    daily = _format_machine_price(machine, "daily_price")
    return "\n".join(
        (
            f"{region} · {label}",
            f"{gpu} ×{total} · Idle {idle}/{total} · CUDA {cuda}",
            f"{payg}/h · {daily}/day · {_format_machine_spec(machine)} · "
            f"Disk {_format_gib(machine.get('max_instance_disk_size'))}",
        )
    )


def _render_stacked_machines(machines: Sequence[dict[str, object]]) -> None:
    """Render machines as a single stacked-details column.

    Used when the terminal is too narrow for the wide table, so no field is
    silently truncated.

    :param machines: Mappings returned by
        :func:`autodl_cli.handlers.gpu.list_machines`.
    """
    table = Table(title=f"GPU machines ({len(machines)})")
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
        console.print("No matching machines found.")
        return

    machines = [machine for machine in entries if isinstance(machine, dict)]
    if not machines:
        console.print("No matching machines found.")
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

    table = Table(title=f"GPU machines ({len(machines)})")
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
