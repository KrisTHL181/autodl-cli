"""Read and write ``~/.autodl-cli/config.toml``.

TODO: use ``tomllib`` (``tomli`` on 3.10) to read and ``tomli-w`` to write.
Resolve the file through :func:`autodl_cli.paths.autodl_home` — never hardcode
the directory name here — and treat a missing file as an empty config.
"""

from __future__ import annotations


def load_config() -> dict[str, object]:
    """Read the local config file.

    :returns: The parsed config, or an empty mapping when the file is absent.
    """
    ...


def save_config(config: dict[str, object]) -> None:
    """Write the local config file.

    :param config: Mapping to serialise as TOML.
    """
    ...
