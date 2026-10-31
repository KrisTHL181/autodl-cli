"""``autodl gpu`` — GPU capacity commands.

``list`` queries ``POST /api/v1/machine/region/gpu_type`` for one or more
regions; without ``--region`` it lists the region catalogue from
``GET /api/v1/common`` instead. ``find`` searches every region for a GPU model
and returns the matches as one flat list.
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


def register_gpu(main_group: click.Group) -> click.Group:
    """Register the ``gpu`` command group on ``main_group``.

    :param main_group: Root Click group.
    :returns: The same group, for chaining.
    """
    main_group.add_command(gpu)
    return main_group
