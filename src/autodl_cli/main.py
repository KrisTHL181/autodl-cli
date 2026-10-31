"""``autodl`` CLI — unified entry point.

This module is a thin hub: it builds the root Click group, stores the global
``--json`` switch in ``ctx.obj``, and calls each
``commands.<name>.register_<name>(main_group)``. Command logic belongs in
``commands/``.
"""

from __future__ import annotations

import click

from autodl_cli.commands.account import register_account
from autodl_cli.commands.auth import register_auth
from autodl_cli.commands.config import register_config
from autodl_cli.commands.gpu import register_gpu
from autodl_cli.commands.image import register_image
from autodl_cli.commands.instance import register_instance
from autodl_cli.commands.nfs import register_nfs
from autodl_cli.commands.tools import register_tools


@click.group(help="Manage AutoDL container instances from the command line.")
@click.version_option(package_name="autodl-cli", prog_name="autodl")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON instead of human-readable output.")
@click.pass_context
def main(ctx: click.Context, as_json: bool) -> None:
    """Manage AutoDL container instances from the command line.

    :param ctx: Click context; receives ``{"json": as_json}``.
    :param as_json: Whether the global ``--json`` switch was passed.
    """
    ctx.obj = {"json": as_json}


register_auth(main)
register_account(main)
register_config(main)
register_gpu(main)
register_image(main)
register_instance(main)
register_nfs(main)
register_tools(main)


if __name__ == "__main__":
    main()
