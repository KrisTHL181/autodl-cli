"""``autodl instance`` — instance lifecycle commands.

``list`` is implemented against ``POST /api/v1/instance`` and ``gpu`` against
``POST /api/v1/machine/region/gpu_type``; without ``--region``, ``gpu`` lists
the region catalogue from ``GET /api/v1/common`` instead. The remaining
lifecycle commands wait for their handlers.
"""

from __future__ import annotations

import click

from autodl_cli import output
from autodl_cli.client import AutoDLClient
from autodl_cli.commands._helpers import require_token
from autodl_cli.config import load_config
from autodl_cli.errors import AutoDLError
from autodl_cli.handlers import instance as instance_handler


@click.group(help="Manage AutoDL container instances.")
def instance() -> None:
    """Manage AutoDL container instances."""


@instance.command("list", help="List every instance on the account.")
@click.option(
    "--status",
    "statuses",
    multiple=True,
    metavar="STATUS",
    help="Only instances in this status (repeatable).",
)
@click.option(
    "--charge-type",
    "charge_types",
    multiple=True,
    metavar="TYPE",
    help="Only instances with this billing mode (repeatable).",
)
@click.option("--sub-name", default="", help="Only instances whose sub-user name matches this value.")
@click.option("--unbind-sub-user", is_flag=True, help="Only instances with no bound sub-user.")
@click.option(
    "--page-size",
    default=instance_handler.DEFAULT_PAGE_SIZE,
    show_default=True,
    type=click.IntRange(min=1, max=100),
    help="Instances requested per API call.",
)
@click.pass_context
def list_command(
    ctx: click.Context,
    statuses: tuple[str, ...],
    charge_types: tuple[str, ...],
    sub_name: str,
    unbind_sub_user: bool,
    page_size: int,
) -> None:
    """List every instance on the account.

    :param ctx: Click context; ``ctx.obj["json"]`` selects JSON output.
    :param statuses: Status values to filter by; empty means no filter.
    :param charge_types: Billing modes to filter by; empty means no filter.
    :param sub_name: Sub-user name filter.
    :param unbind_sub_user: Whether to keep only instances with no bound
        sub-user.
    :param page_size: Instances requested per API call.
    :raises click.ClickException: When no token is configured or the API call
        fails.
    """
    token = require_token(load_config())

    try:
        with AutoDLClient(token) as client:
            instances = instance_handler.list_instances(
                client,
                page_size=page_size,
                statuses=statuses,
                charge_types=charge_types,
                sub_name=sub_name,
                unbind_sub_user=unbind_sub_user,
            )
    except AutoDLError as exc:
        raise click.ClickException(str(exc)) from exc

    if ctx.obj and ctx.obj.get("json"):
        output.render_json(instances)
        return

    output.render_instances(instances)


@instance.command("gpu", help="Show GPU availability in one or more regions.")
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
def gpu_command(
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
            regions = instance_handler.list_regions(client)
            if not region_values:
                if as_json:
                    output.render_json(regions)
                else:
                    output.render_regions(regions)
                return

            try:
                selected = instance_handler.select_regions(regions, region_values)
            except ValueError as exc:
                raise click.ClickException(str(exc)) from exc
            availability = instance_handler.list_gpu_availability(
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


def register_instance(main_group: click.Group) -> click.Group:
    """Register the ``instance`` command group on ``main_group``.

    :param main_group: Root Click group.
    :returns: The same group, for chaining.
    """
    main_group.add_command(instance)
    return main_group
