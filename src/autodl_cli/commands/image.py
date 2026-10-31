"""``autodl image`` — image listing and create-option commands.

TODO: implement ``register_image`` with subcommands for listing images and
showing the options accepted by instance creation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import click


def register_image(main_group: click.Group) -> click.Group:
    """Register the ``image`` command group on ``main_group``.

    :param main_group: Root Click group.
    :returns: The same group, for chaining.
    """
    ...
