"""``autodl account`` — account-level commands.

Exposes the authenticated account profile, the wallet balance, and billing
usage statistics. The handlers already convert AutoDL's money values to yuan,
so both the human-readable view and ``--json`` report yuan with the API's field
names.
"""

from __future__ import annotations

import click

from autodl_cli import output
from autodl_cli.commands._helpers import build_client, require_token
from autodl_cli.config import load_config
from autodl_cli.errors import AutoDLError
from autodl_cli.handlers import account as account_handler


@click.group(help="Inspect the AutoDL account.")
def account() -> None:
    """Inspect the AutoDL account."""


@account.command("balance", help="Show the account balance.")
@click.option(
    "--charge-type",
    default="payg",
    show_default=True,
    help="Billing mode to query (for example payg).",
)
@click.pass_context
def balance(ctx: click.Context, charge_type: str) -> None:
    """Show the account balance.

    :param ctx: Click context; ``ctx.obj["json"]`` selects JSON output.
    :param charge_type: Billing mode passed to the wallet endpoint.
    :raises click.ClickException: When no token is configured or the API call
        fails.
    """
    config = load_config()
    token = require_token(config)

    try:
        with build_client(token, config) as client:
            result = account_handler.get_balance(client, charge_type=charge_type)
    except AutoDLError as exc:
        raise click.ClickException(str(exc)) from exc

    if ctx.obj and ctx.obj.get("json"):
        output.render_json(result)
        return

    output.render_balance(result, charge_type=charge_type)


@account.command("usage", help="Show billing usage statistics.")
@click.option(
    "-g",
    "--granularity",
    type=click.Choice(["monthly", "daily"]),
    default="monthly",
    show_default=True,
    help="Bucket size of the reported periods.",
)
@click.option(
    "--sub-name",
    default="",
    help="Only include this sub-user; empty means every sub-user.",
)
@click.option(
    "--exclude-sub-user",
    is_flag=True,
    default=False,
    help="Exclude sub-user transactions.",
)
@click.pass_context
def usage(ctx: click.Context, granularity: str, sub_name: str, exclude_sub_user: bool) -> None:
    """Show billing usage statistics.

    :param ctx: Click context; ``ctx.obj["json"]`` selects JSON output.
    :param granularity: ``monthly`` or ``daily`` reporting bucket.
    :param sub_name: Sub-user name to filter by; empty means every sub-user.
    :param exclude_sub_user: Whether to exclude sub-user transactions.
    :raises click.ClickException: When no token is configured or the API call
        fails.
    """
    config = load_config()
    token = require_token(config)

    try:
        with build_client(token, config) as client:
            result = account_handler.get_usage_statistics(
                client,
                granularity=granularity,
                sub_name=sub_name,
                exclude_sub_user=exclude_sub_user,
            )
    except AutoDLError as exc:
        raise click.ClickException(str(exc)) from exc

    if ctx.obj and ctx.obj.get("json"):
        output.render_json(result)
        return

    output.render_usage(result, granularity=granularity)


@account.command("me", help="Show the authenticated account profile.")
@click.pass_context
def me(ctx: click.Context) -> None:
    """Show the authenticated account profile.

    :param ctx: Click context; ``ctx.obj["json"]`` selects JSON output.
    :raises click.ClickException: When no token is configured or the API call
        fails.
    """
    config = load_config()
    token = require_token(config)

    try:
        with build_client(token, config) as client:
            result = account_handler.get_me(client)
    except AutoDLError as exc:
        raise click.ClickException(str(exc)) from exc

    if ctx.obj and ctx.obj.get("json"):
        output.render_json(result)
        return

    output.render_account(result)


def register_account(main_group: click.Group) -> click.Group:
    """Register the ``account`` command group on ``main_group``.

    :param main_group: Root Click group.
    :returns: The same group, for chaining.
    """
    main_group.add_command(account)
    return main_group
