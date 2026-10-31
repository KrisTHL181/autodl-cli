"""``autodl account`` — account-level commands.

Currently exposes the wallet balance. The handler returns AutoDL's raw
thousandths-of-a-yuan values; the human-readable view converts them to yuan
while ``--json`` preserves the API shape.
"""

from __future__ import annotations

import click

from autodl_cli import output
from autodl_cli.client import AutoDLClient
from autodl_cli.commands._helpers import require_token
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
    token = require_token(load_config())

    try:
        with AutoDLClient(token) as client:
            result = account_handler.get_balance(client, charge_type=charge_type)
    except AutoDLError as exc:
        raise click.ClickException(str(exc)) from exc

    if ctx.obj and ctx.obj.get("json"):
        output.render_json(result)
        return

    output.render_balance(result, charge_type=charge_type)


def register_account(main_group: click.Group) -> click.Group:
    """Register the ``account`` command group on ``main_group``.

    :param main_group: Root Click group.
    :returns: The same group, for chaining.
    """
    main_group.add_command(account)
    return main_group
