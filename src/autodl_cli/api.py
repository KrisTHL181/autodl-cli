"""Public library entry point.

Code that consumes autodl-toolkit as a library should import from here rather
than from :mod:`autodl_cli.handlers` directly. This module re-exports the
handler surface and normalises internal exceptions into the
:class:`~autodl_cli.errors.AutoDLError` hierarchy.

TODO: export the ``fetch_*`` / ``create_*`` helpers (instances, images,
account balance, NFS) once the handlers are implemented.
"""

from __future__ import annotations

__all__: list[str] = []
