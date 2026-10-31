"""``autodl nfs`` — network filesystem commands.

TODO: implement ``register_nfs`` with a mount command.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import click


def register_nfs(main_group: click.Group) -> click.Group:
    """Register the ``nfs`` command group on ``main_group``.

    :param main_group: Root Click group.
    :returns: The same group, for chaining.
    """
    ...
