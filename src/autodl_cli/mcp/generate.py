"""AutoDL-specific configuration for the generic :mod:`click2mcp` generator.

The walker, signature synthesis, and argv encoding live in
:mod:`click2mcp.generator`. This module only names the autodl CLI, excludes the
one command that cannot run over MCP, and keeps the ``generate_tools`` entry
point working.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from click2mcp.generator import generate_tools as _generate_tools

if TYPE_CHECKING:
    import subprocess
    from collections.abc import Callable

    import click
    from click2mcp.generator import Tool

logger = logging.getLogger(__name__)

#: ``auth paste`` reads credentials from stdin, and the MCP child runs with
#: ``stdin=/dev/null``, so it can never work; it is excluded from typed tools and
#: refused by ``autodl_run``.
EXCLUDED_PATHS: frozenset[tuple[str, ...]] = frozenset({("auth", "paste")})


def _load_cli() -> click.Group | None:
    """Import the CLI entry point, or give up and serve only the shell tools.

    Losing the typed tools is survivable; failing to start the server is not.

    :returns: the root command group, or ``None`` if it could not be imported.
    """
    try:
        from autodl_cli.main import main
    except Exception:
        logger.warning(
            "autodl-mcp: could not import the autodl CLI; serving only autodl_help/autodl_run",
            exc_info=True,
        )
        return None
    return main


def generate_tools(
    *,
    invoke: Callable[[list[str]], subprocess.CompletedProcess[str]],
    exclude: frozenset[tuple[str, ...]] = EXCLUDED_PATHS,
    include: tuple[tuple[str, ...], ...] | None = None,
    inherit_group_options: bool = True,
) -> list[Tool]:
    """Build one typed MCP tool per leaf command of the ``autodl`` CLI.

    New code should use :func:`click2mcp.generator.generate_tools` directly; this
    wrapper only fills in the autodl-specific arguments.

    :param invoke: runs the CLI and returns the completed process.
    :param exclude: command paths to leave out — commands that cannot work over MCP.
    :param include: command path prefixes to expose; ``None`` for every leaf.
    :param inherit_group_options: whether ancestor group options are exposed on
        each leaf tool. On here, so the root ``--json`` appears as ``json``.
    :returns: the generated tools.
    """
    return _generate_tools(
        cli=_load_cli(),
        invoke=invoke,
        app="autodl",
        exclude=exclude,
        include=include,
        inherit_group_options=inherit_group_options,
    )
