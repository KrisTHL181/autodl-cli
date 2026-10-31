"""Read and write ``~/.autodl-cli/config.toml``.

The file is resolved through :func:`autodl_cli.paths.autodl_home` — the
directory name is never hardcoded here — and a missing file is treated as an
empty config. Writes are atomic and the resulting file is private to the user.
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlparse

import tomli_w

if sys.version_info >= (3, 11):
    import tomllib
else:  # Python 3.10
    import tomli as tomllib

from autodl_cli.client import APP_VERSION, DEFAULT_BASE_URL, DEFAULT_TIMEOUT
from autodl_cli.paths import autodl_home

#: Phone area prefix used when none is configured.
DEFAULT_PHONE_AREA = "+86"

#: Valid device fingerprints are FingerprintJS visitor IDs.
_FINGERPRINT_RE = re.compile(r"[0-9a-f]{32}")

#: Valid phone area prefixes, for example ``"+86"``.
_PHONE_AREA_RE = re.compile(r"\+\d{1,4}")

#: Valid ``AppVersion`` values, for example ``"v6.53.0"``.
_APP_VERSION_RE = re.compile(r"v\d+(?:\.\d+)*")


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


def _effective(config: Mapping[str, object] | None) -> Mapping[str, object]:
    """Return *config*, loading it from disk when it is ``None``.

    :param config: Already-parsed config, or ``None`` to load it.
    :returns: The config mapping to read.
    """
    return load_config() if config is None else config


def _store(key: str, value: object) -> None:
    """Persist one config key atomically.

    A ``None`` value deletes the key instead of writing it.

    :param key: TOML key to update.
    :param value: New value, or ``None`` to remove the key.
    """
    config = load_config()
    if value is None:
        config.pop(key, None)
    else:
        config[key] = value
    save_config(config)


def get_token(config: Mapping[str, object] | None = None) -> str | None:
    """Return the configured API token.

    :param config: Already-parsed config, or ``None`` to load it.
    :returns: The stored non-empty token, or ``None`` when unset.
    """
    value = _effective(config).get("token")
    return value if isinstance(value, str) and value else None


def get_device_fingerprint(config: Mapping[str, object] | None = None) -> str | None:
    """Return the configured device fingerprint.

    :param config: Already-parsed config, or ``None`` to load it.
    :returns: The stored non-empty fingerprint, or ``None`` when unset.
    """
    value = _effective(config).get("device_fingerprint")
    return value if isinstance(value, str) and value else None


def get_phone_area(config: Mapping[str, object] | None = None) -> str:
    """Return the phone area prefix used by password login.

    :param config: Already-parsed config, or ``None`` to load it.
    :returns: The stored prefix, or :data:`DEFAULT_PHONE_AREA`.
    """
    value = _effective(config).get("phone_area")
    return value if isinstance(value, str) and value else DEFAULT_PHONE_AREA


def get_base_url(config: Mapping[str, object] | None = None) -> str:
    """Return the API base URL.

    :param config: Already-parsed config, or ``None`` to load it.
    :returns: The stored URL, or :data:`autodl_cli.client.DEFAULT_BASE_URL`.
    """
    value = _effective(config).get("base_url")
    return value if isinstance(value, str) and value else DEFAULT_BASE_URL


def get_timeout(config: Mapping[str, object] | None = None) -> float:
    """Return the per-request timeout in seconds.

    :param config: Already-parsed config, or ``None`` to load it.
    :returns: The stored timeout when it is a number in ``(0, 600]``,
        otherwise :data:`autodl_cli.client.DEFAULT_TIMEOUT`.
    """
    value = _effective(config).get("timeout")
    if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 < value <= 600:
        return float(value)
    return DEFAULT_TIMEOUT


def get_app_version(config: Mapping[str, object] | None = None) -> str:
    """Return the value used for the mandatory ``AppVersion`` header.

    :param config: Already-parsed config, or ``None`` to load it.
    :returns: The stored version, or :data:`autodl_cli.client.APP_VERSION`.
    """
    value = _effective(config).get("app_version")
    return value if isinstance(value, str) and value else APP_VERSION


def set_token(value: str | None) -> None:
    """Store or remove the API token.

    :param value: Token to store; ``None`` removes it. Surrounding whitespace
        is stripped.
    :raises ValueError: When *value* is empty after stripping.
    """
    if value is None:
        _store("token", None)
        return
    token = value.strip()
    if not token:
        raise ValueError("API token must not be empty.")
    _store("token", token)


def set_device_fingerprint(value: str | None) -> None:
    """Store or remove the device fingerprint.

    :param value: Fingerprint to store; ``None`` removes it. Input is
        stripped and lowercased.
    :raises ValueError: When *value* is not 32 hexadecimal characters.
    """
    if value is None:
        _store("device_fingerprint", None)
        return
    fingerprint = value.strip().lower()
    if not _FINGERPRINT_RE.fullmatch(fingerprint):
        raise ValueError("Device fingerprint must be 32 lowercase hexadecimal characters.")
    _store("device_fingerprint", fingerprint)


def set_phone_area(value: str | None) -> None:
    """Store or remove the phone area prefix.

    :param value: Prefix such as ``"+86"``; ``None`` removes it.
    :raises ValueError: When *value* is not ``+`` followed by 1-4 digits.
    """
    if value is None:
        _store("phone_area", None)
        return
    if not _PHONE_AREA_RE.fullmatch(value):
        raise ValueError("Phone area prefix must be '+' followed by 1-4 digits, for example '+86'.")
    _store("phone_area", value)


def set_base_url(value: str | None) -> None:
    """Store or remove the API base URL.

    :param value: Absolute ``http`` or ``https`` URL; ``None`` removes it.
        Trailing slashes are stripped.
    :raises ValueError: When *value* is not an absolute HTTP(S) URL.
    """
    if value is None:
        _store("base_url", None)
        return
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("Base URL must be an absolute http or https URL.")
    _store("base_url", value.rstrip("/"))


def set_timeout(value: float | None) -> None:
    """Store or remove the request timeout.

    :param value: Timeout in seconds; ``None`` removes it.
    :raises ValueError: When *value* is not a number in ``(0, 600]``.
    """
    if value is None:
        _store("timeout", None)
        return
    try:
        seconds = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Timeout must be a number of seconds.") from exc
    if not 0 < seconds <= 600:
        raise ValueError("Timeout must be greater than 0 and at most 600 seconds.")
    _store("timeout", seconds)


def set_app_version(value: str | None) -> None:
    """Store or remove the ``AppVersion`` header value.

    :param value: Version such as ``"v6.53.0"``; ``None`` removes it.
    :raises ValueError: When *value* does not look like ``v<number>`` with
        optional dot-separated components.
    """
    if value is None:
        _store("app_version", None)
        return
    if not _APP_VERSION_RE.fullmatch(value):
        raise ValueError("AppVersion must look like 'v6.53.0'.")
    _store("app_version", value)
