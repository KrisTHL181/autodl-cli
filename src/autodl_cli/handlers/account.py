"""Account-domain API handlers.

TODO: implement the call behind this signature.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from autodl_cli.client import AutoDLClient


def get_balance(client: AutoDLClient) -> dict[str, object]:
    """Return the account balance.

    :param client: Authenticated API client.
    :returns: The balance mapping.
    """
    ...
