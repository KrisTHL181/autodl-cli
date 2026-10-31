"""``autodl`` CLI — unified entry point.

TODO: create the root ``click.Group``, add the version option, then import and
call each ``commands.<name>.register_<name>(main_group)``. Keep this module a
thin hub — command logic belongs in ``commands/``.
"""

from __future__ import annotations


def main() -> None:
    """Run the ``autodl`` command-line interface."""
    ...
