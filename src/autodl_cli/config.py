"""Read and write ``~/.autodl-cli/config.toml``.

The file is resolved through :func:`autodl_cli.paths.autodl_home` — the
directory name is never hardcoded here — and a missing file is treated as an
empty config. Writes are atomic and the resulting file is private to the user.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import tomli_w

if sys.version_info >= (3, 11):
    import tomllib
else:  # Python 3.10
    import tomli as tomllib

from autodl_cli.paths import autodl_home


def config_path() -> Path:
    """Return the path of the local config file.

    :returns: ``autodl_home() / "config.toml"``.
    """
    return autodl_home() / "config.toml"


def load_config() -> dict[str, object]:
    """Read the local config file.

    :returns: The parsed config, or an empty mapping when the file is absent.
    """
    path = config_path()
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except FileNotFoundError:
        return {}


def save_config(config: dict[str, object]) -> None:
    """Write the local config file.

    The parent directory is created with mode ``0o700``; the file itself is
    written to a temporary file in the same directory and then moved into place
    so a reader never observes a partially written file. The final file has
    mode ``0o600``.

    :param config: Mapping to serialise as TOML.
    """
    path = config_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)

    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=".config-", suffix=".toml")
    try:
        with os.fdopen(descriptor, "wb") as handle:
            tomli_w.dump(config, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise
