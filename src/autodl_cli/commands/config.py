"""``autodl config`` — local configuration commands.

TODO: implement ``register_config`` with show / set / path subcommands backed
by :mod:`autodl_cli.config`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import click


def register_config(main_group: click.Group) -> click.Group:
    """Register the ``config`` command group on ``main_group``.

    :param main_group: Root Click group.
    :returns: The same group, for chaining.
    """
    ...
