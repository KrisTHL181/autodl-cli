"""``autodl gpu`` — GPU capacity commands.

``list`` queries ``POST /api/v1/machine/region/gpu_type`` for one or more
regions; without ``--region`` it lists the region catalogue from
``GET /api/v1/common`` instead. ``find`` searches every region for a GPU model
and returns the matches as one flat list. ``machines`` lists the individual
machines behind that stock from ``POST /api/v1/user/machine/list``.
"""

from __future__ import annotations

import click

from autodl_cli import output
from autodl_cli.client import AutoDLClient
from autodl_cli.commands._helpers import require_token
from autodl_cli.config import load_config
from autodl_cli.errors import AutoDLError
from autodl_cli.handlers import gpu as gpu_handler


@click.group(help="Browse AutoDL GPU capacity.")
def gpu() -> None:
    """Browse AutoDL GPU capacity."""


@gpu.command("list", help="Show GPU availability in one or more regions.")
@click.option(
    "--region",
    "-r",
    "region_values",
    multiple=True,
    metavar="REGION",
    help="Region sign, data center, or name (repeatable); omit to list the available regions.",
)
@click.option(
    "--available",
    "-a",
    is_flag=True,
    help="Only show GPU types with idle capacity.",
)
@click.pass_context
def list_command(
    ctx: click.Context,
    region_values: tuple[str, ...],
    available: bool,
) -> None:
    """Show GPU availability in one or more regions.

    Without ``--region`` the command only prints the region catalogue, so the
    valid identifiers can be discovered before spending a request per region.

    :param ctx: Click context; ``ctx.obj["json"]`` selects JSON output.
    :param region_values: Region signs, data centers, or names to query; empty
        means list the available regions instead of querying stock.
    :param available: Whether to drop GPU types with no idle capacity.
    :raises click.ClickException: When an identifier is unknown, no token is
        configured, or the API call fails.
    """
    token = require_token(load_config())
    as_json = bool(ctx.obj and ctx.obj.get("json"))

    try:
        with AutoDLClient(token) as client:
            regions = gpu_handler.list_regions(client)
            if not region_values:
                if as_json:
                    output.render_json(regions)
                else:
                    output.render_regions(regions)
                return

            try:
                selected = gpu_handler.select_regions(regions, region_values)
            except ValueError as exc:
                raise click.ClickException(str(exc)) from exc
            availability = gpu_handler.list_gpu_availability(
                client,
                selected,
                available_only=available,
            )
    except AutoDLError as exc:
        raise click.ClickException(str(exc)) from exc

    if as_json:
        output.render_json(availability)
        return

    output.render_gpu_availability(availability)


@gpu.command("find", help="Search GPU models across regions.")
@click.argument("model")
@click.option(
    "--region",
    "-r",
    "region_values",
    multiple=True,
    metavar="REGION",
    help="Region sign, data center, or name to search (repeatable); omit to search every region.",
)
@click.option(
    "--available",
    "-a",
    is_flag=True,
    help="Only show GPU types with idle capacity.",
)
@click.pass_context
def find_command(
    ctx: click.Context,
    model: str,
    region_values: tuple[str, ...],
    available: bool,
) -> None:
    """Search every region for GPU types matching ``model``.

    The model is matched case-insensitively as a substring of the GPU type.
    Without ``--region`` every region in the catalogue is searched, which costs
    one request per region.

    :param ctx: Click context; ``ctx.obj["json"]`` selects JSON output.
    :param model: Model name or fragment to match (for example ``4090``).
    :param region_values: Region signs, data centers, or names to search; empty
        means search every region.
    :param available: Whether to drop GPU types with no idle capacity.
    :raises click.ClickException: When an identifier is unknown, the model is
        empty, no token is configured, or the API call fails.
    """
    token = require_token(load_config())
    as_json = bool(ctx.obj and ctx.obj.get("json"))

    try:
        with AutoDLClient(token) as client:
            regions = gpu_handler.list_regions(client)
            if region_values:
                try:
                    selected = gpu_handler.select_regions(regions, region_values)
                except ValueError as exc:
                    raise click.ClickException(str(exc)) from exc
            else:
                selected = regions
            try:
                matches = gpu_handler.find_gpu(client, selected, model, available_only=available)
            except ValueError as exc:
                raise click.ClickException(str(exc)) from exc
    except AutoDLError as exc:
        raise click.ClickException(str(exc)) from exc

    if as_json:
        output.render_json(matches)
        return

    output.render_gpu_matches(matches)


@gpu.command("machines", help="List individual GPU machines with idle capacity.")
@click.option(
    "--region",
    "-r",
    "region_values",
    multiple=True,
    metavar="REGION",
    help="Region sign, data center, or name (repeatable); omit to search every region.",
)
@click.option(
    "--gpu",
    "-g",
    "gpu_types",
    multiple=True,
    metavar="NAME",
    help="Exact GPU type name to include (repeatable).",
)
@click.option(
    "--machine-tag",
    "-t",
    "machine_tags",
    multiple=True,
    metavar="TAG",
    help="Machine tag to include (repeatable).",
)
@click.option(
    "--idle",
    "-i",
    "gpu_idle_num",
    default=1,
    show_default=True,
    type=click.IntRange(min=0),
    metavar="N",
    help="Minimum idle GPUs per machine; 0 disables the filter.",
)
@click.option(
    "--charge-type",
    type=click.Choice(gpu_handler.MACHINE_CHARGE_TYPES),
    default="payg",
    show_default=True,
    help="Billing mode the machine must support.",
)
@click.option(
    "--chip",
    "chip_corps",
    multiple=True,
    metavar="CORP",
    help="Chip vendor to include (repeatable), for example nvidia.",
)
@click.option(
    "--cpu-arch",
    "cpu_archs",
    multiple=True,
    metavar="ARCH",
    help="CPU architecture to include (repeatable), for example x86.",
)
@click.option("--mount-net-disk", is_flag=True, help="Only machines that support mounting a network disk.")
@click.option("--machine-id", default="", metavar="ID", help="Only this machine ID.")
@click.option(
    "--date-range", default="", metavar="RANGE", help="Availability date filter, passed to the API unchanged."
)
@click.option("--date-from", default="", metavar="DATE", help="Start date for --date-range.")
@click.option("--date-to", default="", metavar="DATE", help="End date for --date-range.")
@click.option(
    "--sort",
    "sort_field",
    type=click.Choice(gpu_handler.MACHINE_SORT_FIELDS),
    default=None,
    help="Sort by hourly price, idle GPUs, or instance disk size; fetches every page and sorts locally.",
)
@click.option(
    "--order",
    "sort_order",
    type=click.Choice(["asc", "desc"]),
    default="asc",
    show_default=True,
    help="Sort direction; only used with --sort.",
)
@click.option(
    "--page",
    "page_index",
    default=1,
    show_default=True,
    type=click.IntRange(min=1),
    help="Page to show when --all is not set.",
)
@click.option(
    "--page-size",
    default=gpu_handler.DEFAULT_MACHINE_PAGE_SIZE,
    show_default=True,
    type=click.IntRange(min=1, max=gpu_handler.MAX_MACHINE_PAGE_SIZE),
    help="Machines per returned page.",
)
@click.option("--all", "fetch_all", is_flag=True, help="Fetch every page instead of one.")
@click.pass_context
def machines_command(
    ctx: click.Context,
    region_values: tuple[str, ...],
    gpu_types: tuple[str, ...],
    machine_tags: tuple[str, ...],
    gpu_idle_num: int,
    charge_type: str,
    chip_corps: tuple[str, ...],
    cpu_archs: tuple[str, ...],
    mount_net_disk: bool,
    machine_id: str,
    date_range: str,
    date_from: str,
    date_to: str,
    sort_field: str | None,
    sort_order: str,
    page_index: int,
    page_size: int,
    fetch_all: bool,
) -> None:
    """List the individual machines behind the GPU stock.

    ``--region`` accepts the same identifiers as ``gpu list`` and expands a
    data center to every one of its region signs. All other options map onto
    the JSON body used by the AutoDL create page. ``--sort`` fetches every
    matching page and sorts locally, because the API's ordering fields are not
    reliable across pages; ``--page`` then selects a page of that result. A
    positive ``--idle`` also fetches every page, because the API's idle filter
    lets fully used machines through.

    :param ctx: Click context; ``ctx.obj["json"]`` selects JSON output.
    :param region_values: Region signs, data centers, or names to search;
        empty means every region.
    :param gpu_types: Exact GPU type names to include.
    :param machine_tags: Machine tag names to include.
    :param gpu_idle_num: Minimum idle GPUs per machine; ``0`` disables it.
    :param charge_type: Billing mode the machine must support.
    :param chip_corps: Chip vendors to include.
    :param cpu_archs: CPU architectures to include.
    :param mount_net_disk: Whether to require network-disk support.
    :param machine_id: Only this machine ID; empty means no filter.
    :param date_range: Availability date filter passed through unchanged.
    :param date_from: Start date of the availability range.
    :param date_to: End date of the availability range.
    :param sort_field: Sort field, or ``None`` for the server's default order.
    :param sort_order: Sort direction used with ``sort_field``.
    :param page_index: Page to request when ``fetch_all`` is false.
    :param page_size: Machines requested per API call.
    :param fetch_all: Whether to fetch every page.
    :raises click.UsageError: When ``--page`` is combined with ``--all``.
    :raises click.ClickException: When an identifier is unknown, no token is
        configured, or the API call fails.
    """
    if fetch_all and page_index != 1:
        raise click.UsageError("--page cannot be combined with --all")

    token = require_token(load_config())
    as_json = bool(ctx.obj and ctx.obj.get("json"))

    try:
        with AutoDLClient(token) as client:
            signs: list[str] = []
            if region_values:
                regions = gpu_handler.list_regions(client)
                try:
                    selected = gpu_handler.select_regions(regions, region_values)
                except ValueError as exc:
                    raise click.ClickException(str(exc)) from exc
                signs = [sign for region in selected for sign in gpu_handler.region_signs(region)]
            page = gpu_handler.list_machines(
                client,
                charge_type=charge_type,
                region_signs=signs,
                gpu_types=gpu_types,
                machine_tags=machine_tags,
                gpu_idle_num=gpu_idle_num,
                mount_net_disk=mount_net_disk,
                cpu_archs=cpu_archs,
                chip_corps=chip_corps,
                machine_id=machine_id,
                date_range=date_range,
                date_from=date_from,
                date_to=date_to,
                sort_field=sort_field,
                sort_order=sort_order,
                page_index=page_index,
                page_size=page_size,
                all_pages=fetch_all,
            )
    except AutoDLError as exc:
        raise click.ClickException(str(exc)) from exc

    if as_json:
        output.render_json(page)
        return

    output.render_gpu_machines(page)


def register_gpu(main_group: click.Group) -> click.Group:
    """Register the ``gpu`` command group on ``main_group``.

    :param main_group: Root Click group.
    :returns: The same group, for chaining.
    """
    main_group.add_command(gpu)
    return main_group
