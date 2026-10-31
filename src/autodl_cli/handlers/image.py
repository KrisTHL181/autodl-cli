"""Image-domain API handlers.

TODO: implement the calls behind these signatures.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from autodl_cli.client import AutoDLClient


def list_images(client: AutoDLClient) -> list[dict[str, object]]:
    """Return the images available for new instances.

    :param client: Authenticated API client.
    :returns: One mapping per image.
    """
    ...


def get_create_options(client: AutoDLClient) -> dict[str, object]:
    """Return the options accepted when creating an instance.

    :param client: Authenticated API client.
    :returns: The create-options mapping.
    """
    ...
