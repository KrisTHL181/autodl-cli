"""Terminal output layer.

All Rich rendering and ``--json`` output is centralised here; command modules
call these helpers instead of printing themselves. Handlers never write to the
terminal.

TODO: add the styled renderers (tables, key/value blocks, errors) and keep the
``--json`` path free of ANSI escapes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


def render_json(payload: object) -> None:
    """Print ``payload`` as JSON on stdout.

    :param payload: JSON-serialisable data.
    """
    ...


def render_table(rows: Sequence[dict[str, object]], columns: Sequence[str]) -> None:
    """Render ``rows`` as a Rich table.

    :param rows: Row mappings.
    :param columns: Column keys, in display order.
    """
    ...
