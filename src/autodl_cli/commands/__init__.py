"""CLI command group modules.

Each module exports one ``register_<name>(main_group)`` function that attaches
its subcommands to the root Click group.
"""

from __future__ import annotations

from autodl_cli.commands._helpers import parse_instance_id, require_token

__all__ = ["parse_instance_id", "require_token"]
