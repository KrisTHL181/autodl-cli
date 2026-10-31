"""``autodl instance`` — instance lifecycle commands.

TODO: implement ``register_instance`` with subcommands for list / show /
create / power-on / power-off / release / save-image.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import click


def register_instance(main_group: click.Group) -> click.Group:
    """Register the ``instance`` command group on ``main_group``.

    :param main_group: Root Click group.
    :returns: The same group, for chaining.
    """
    ...
