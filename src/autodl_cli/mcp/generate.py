"""Generate MCP tools from the Click command tree.

TODO: walk the root group and build one typed tool per leaf command, skipping
commands that can never finish over MCP. See ``zhihu_cli.mcp.generate`` for the
signature-driven approach.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import click


def generate_tools(main_group: click.Group) -> list[object]:
    """Build one MCP tool per leaf command in ``main_group``.

    :param main_group: Root Click group.
    :returns: Generated tool objects, ready for the MCP server.
    """
    ...
