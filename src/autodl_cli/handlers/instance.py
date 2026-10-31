"""Instance-domain API handlers.

TODO: implement the calls behind these signatures and return the structures
defined in :mod:`autodl_cli.models` instead of raw response dictionaries.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from autodl_cli.client import AutoDLClient


def list_instances(client: AutoDLClient) -> list[dict[str, object]]:
    """Return every instance visible to the authenticated account.

    :param client: Authenticated API client.
    :returns: One mapping per instance.
    """
    ...


def get_instance(client: AutoDLClient, instance_id: str) -> dict[str, object]:
    """Return one instance's details.

    :param client: Authenticated API client.
    :param instance_id: Instance identifier.
    :returns: The instance mapping.
    """
    ...


def get_instance_status(client: AutoDLClient, instance_id: str) -> dict[str, object]:
    """Return one instance's current status.

    :param client: Authenticated API client.
    :param instance_id: Instance identifier.
    :returns: The status mapping.
    """
    ...


def create_instance(client: AutoDLClient, options: dict[str, object]) -> dict[str, object]:
    """Create an instance.

    :param client: Authenticated API client.
    :param options: Order parameters (image, GPU type, region, …).
    :returns: The created instance mapping.
    """
    ...


def power_on(client: AutoDLClient, instance_id: str) -> dict[str, object]:
    """Power an instance on.

    :param client: Authenticated API client.
    :param instance_id: Instance identifier.
    :returns: The operation result.
    """
    ...


def power_off(client: AutoDLClient, instance_id: str) -> dict[str, object]:
    """Power an instance off.

    :param client: Authenticated API client.
    :param instance_id: Instance identifier.
    :returns: The operation result.
    """
    ...


def release_instance(client: AutoDLClient, instance_id: str) -> dict[str, object]:
    """Release an instance.

    :param client: Authenticated API client.
    :param instance_id: Instance identifier.
    :returns: The operation result.
    """
    ...


def save_image(client: AutoDLClient, instance_id: str, image_name: str) -> dict[str, object]:
    """Save an instance as a custom image.

    :param client: Authenticated API client.
    :param instance_id: Instance identifier.
    :param image_name: Name for the new image.
    :returns: The operation result.
    """
    ...
