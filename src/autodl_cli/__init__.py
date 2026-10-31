"""autodl-cli: command-line tooling and a Python SDK for AutoDL instances.

The public library entry point is :mod:`autodl_cli.api`; exception types live
in :mod:`autodl_cli.errors`.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("autodl-cli")
except PackageNotFoundError:  # not installed when running from a source tree
    __version__ = "0.0.0"

__all__ = ["__version__"]
