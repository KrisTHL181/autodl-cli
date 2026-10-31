"""Domain handlers.

Each handler module translates AutoDL API responses into plain Python data.
Handlers never write to the terminal and never read CLI options — command
modules and :mod:`autodl_cli.api` are the only callers.
"""

from __future__ import annotations

__all__: list[str] = []
