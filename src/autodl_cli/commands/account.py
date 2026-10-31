"""``autodl account`` — account-level commands.

TODO: implement ``register_account`` with a balance command.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import click


def register_account(main_group: click.Group) -> click.Group:
    """Register the ``account`` command group on ``main_group``.

    :param main_group: Root Click group.
    :returns: The same group, for chaining.
    """
    ...
