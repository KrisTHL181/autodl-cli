"""NFS-domain API handlers.

TODO: implement the call behind this signature.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from autodl_cli.client import AutoDLClient


def mount_nfs(client: AutoDLClient, options: dict[str, object]) -> dict[str, object]:
    """Mount a network filesystem on an instance.

    :param client: Authenticated API client.
    :param options: Mount parameters (instance, source, target, …).
    :returns: The operation result.
    """
    ...
