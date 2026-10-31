"""``autodl instance`` — instance lifecycle commands.

``list`` is implemented against ``POST /api/v1/instance``; its ``--query``
filter is applied locally because the API has no keyword field. ``detail``
reads one instance's configuration snapshot from
``GET /api/v1/instance/snapshot``. The remaining lifecycle commands wait for
their handlers.
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
    "--query",
    "-q",
    default="",
    metavar="TEXT",
    help="Only instances whose UUID, name, region, machine alias, or GPU name contains this text.",
)
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
    query: str,
    page_size: int,
) -> None:
    """List every instance on the account.

    :param ctx: Click context; ``ctx.obj["json"]`` selects JSON output.
    :param statuses: Status values to filter by; empty means no filter.
    :param charge_types: Billing modes to filter by; empty means no filter.
    :param sub_name: Sub-user name filter.
    :param unbind_sub_user: Whether to keep only instances with no bound
        sub-user.
    :param query: Free-text filter applied locally; empty means no filter.
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
                query=query,
            )
    except AutoDLError as exc:
        raise click.ClickException(str(exc)) from exc

    if ctx.obj and ctx.obj.get("json"):
        output.render_json(instances)
        return

    output.render_instances(instances)


@instance.command("detail", help="Show one instance's configuration and machine details.")
@click.argument("instance_uuid")
@click.pass_context
def detail_command(ctx: click.Context, instance_uuid: str) -> None:
    """Show one instance's configuration and machine details.

    The snapshot covers the base image, GPU allocation, host machine, and
    prices. It does not include the live status or SSH command; use
    ``instance list`` for those.

    :param ctx: Click context; ``ctx.obj["json"]`` selects JSON output.
    :param instance_uuid: Instance UUID as printed by ``instance list``.
    :raises click.ClickException: When no token is configured or the API call
        fails.
    """
    token = require_token(load_config())

    try:
        with AutoDLClient(token) as client:
            detail = instance_handler.get_instance(client, instance_uuid)
    except AutoDLError as exc:
        raise click.ClickException(str(exc)) from exc

    if ctx.obj and ctx.obj.get("json"):
        output.render_json(detail)
        return

    output.render_instance_detail(detail, instance_uuid=instance_uuid)


def register_instance(main_group: click.Group) -> click.Group:
    """Register the ``instance`` command group on ``main_group``.

    :param main_group: Root Click group.
    :returns: The same group, for chaining.
    """
    main_group.add_command(instance)
    return main_group
