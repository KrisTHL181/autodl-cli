"""CLI command group modules.

Each module exports one ``register_<name>(main_group)`` function that attaches
its subcommands to the root Click group.
"""

from __future__ import annotations

from autodl_cli.commands._helpers import require_token

__all__ = ["require_token"]
