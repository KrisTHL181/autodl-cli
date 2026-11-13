"""Read and write per-profile credentials and global settings.

Credentials live in ``profiles/<name>.toml`` under :func:`autodl_cli.paths.autodl_home`;
a plain-text ``active_profile`` file names the default credential set, and
``config.toml`` holds only global settings. The directory name is never
hardcoded here. Every write is atomic and private to the user.

:func:`load_config` returns a merged view of the global settings and the
effective profile's credentials, so callers that read a single mapping keep
working unchanged. :func:`save_config` splits the mapping back into its two
files.
"""

from __future__ import annotations

import io
import os
import re
import sys
import tempfile
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import tomli_w

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping
    from contextvars import Token

if sys.version_info >= (3, 11):
    import tomllib
else:  # Python 3.10
    import tomli as tomllib

from autodl_cli.client import APP_VERSION, DEFAULT_BASE_URL, DEFAULT_TIMEOUT
from autodl_cli.paths import autodl_home

#: Phone area prefix used when none is configured.
DEFAULT_PHONE_AREA = "+86"

#: Profile used when nothing else selects one.
DEFAULT_PROFILE = "default"

#: Environment variable that selects a profile when ``--profile`` is absent.
PROFILE_ENV = "AUTODL_PROFILE"

#: Keys stored in a profile file rather than in ``config.toml``.
PROFILE_KEYS: tuple[str, ...] = ("token", "phone_area")

#: Valid profile names: one leading alphanumeric plus up to 63 of ``._-``.
_PROFILE_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")

#: Valid device fingerprints are FingerprintJS visitor IDs.
_FINGERPRINT_RE = re.compile(r"[0-9a-f]{32}")

#: Valid phone area prefixes, for example ``"+86"``.
_PHONE_AREA_RE = re.compile(r"\+\d{1,4}")

#: Valid ``AppVersion`` values, for example ``"v6.53.0"``.
_APP_VERSION_RE = re.compile(r"v\d+(?:\.\d+)*")

#: Explicit selection made by the root ``--profile`` flag, if any.
_profile_override: ContextVar[str | None] = ContextVar("autodl_cli_profile", default=None)


def validate_profile_name(name: str) -> str:
    """Return *name* when it is a valid profile name.

    Profile names are used as file stems, so path separators and traversal
    components are rejected rather than sanitised.

    :param name: Candidate profile name.
    :returns: The unchanged name.
    :raises ValueError: When *name* is not one leading alphanumeric character
        followed by up to 63 letters, digits, dots, underscores, or hyphens.
    """
    if not isinstance(name, str) or not _PROFILE_NAME_RE.fullmatch(name):
        raise ValueError(
            f"Invalid profile name {name!r}. Use 1-64 letters, digits, '.', '_' or '-', "
            "starting with a letter or digit."
        )
    return name


def config_path() -> Path:
    """Return the path of the global config file.

    :returns: ``autodl_home() / "config.toml"``.
    """
    return autodl_home() / "config.toml"


def profiles_dir() -> Path:
    """Return the directory that holds per-profile credential files.

    :returns: ``autodl_home() / "profiles"``.
    """
    return autodl_home() / "profiles"


def profile_path(name: str | None = None) -> Path:
    """Return the credential file for one profile.

    :param name: Profile name, or ``None`` for the effective profile.
    :returns: ``profiles_dir() / "<name>.toml"``.
    :raises ValueError: When *name* is not a valid profile name.
    """
    resolved = _effective_profile_name() if name is None else name
    return profiles_dir() / f"{validate_profile_name(resolved)}.toml"


def active_profile_path() -> Path:
    """Return the file that records the active profile name.

    :returns: ``autodl_home() / "active_profile"``.
    """
    return autodl_home() / "active_profile"


def set_profile(name: str | None) -> Token[str | None]:
    """Pin the profile used by config lookups in the current context.

    The root CLI callback calls this for every invocation and resets the
    returned token when the Click context closes, so a run cannot leak its
    selection into the next one.

    :param name: Profile to pin, or ``None`` to fall back to the environment,
        the active-profile file, and finally ``"default"``.
    :returns: A token accepted by :func:`reset_profile`.
    :raises ValueError: When *name* is not a valid profile name.
    """
    if name is not None:
        validate_profile_name(name)
    return _profile_override.set(name)


def reset_profile(token: Token[str | None]) -> None:
    """Undo a :func:`set_profile` call.

    :param token: Token returned by :func:`set_profile`.
    """
    _profile_override.reset(token)


@contextmanager
def use_profile(name: str | None) -> Iterator[None]:
    """Temporarily pin the profile used by config lookups.

    :param name: Profile to pin, or ``None`` for normal resolution.
    :yields: Nothing; the pin is active for the ``with`` body.
    :raises ValueError: When *name* is not a valid profile name.
    """
    token = set_profile(name)
    try:
        yield
    finally:
        reset_profile(token)


def current_profile() -> tuple[str, str]:
    """Return the effective profile and where the selection came from.

    The precedence is the root ``--profile`` flag, then ``AUTODL_PROFILE``,
    then the ``active_profile`` file, then ``"default"``.

    :returns: ``(name, source)`` where *source* is ``"flag"``, ``"env"``,
        ``"active"``, or ``"default"``.
    :raises ValueError: When ``AUTODL_PROFILE`` contains an invalid name.
    """
    _migrate_legacy()
    return _resolve_profile()


def list_profiles() -> list[str]:
    """Return every profile name, always including ``"default"``.

    :returns: Sorted names; malformed file stems are ignored.
    """
    _migrate_legacy()
    names = {DEFAULT_PROFILE}
    directory = profiles_dir()
    if directory.is_dir():
        for entry in directory.glob("*.toml"):
            try:
                names.add(validate_profile_name(entry.stem))
            except ValueError:
                continue
    return sorted(names)


def profile_exists(name: str) -> bool:
    """Return whether a profile credential file exists.

    :param name: Profile name.
    :returns: ``True`` when ``profiles/<name>.toml`` exists.
    :raises ValueError: When *name* is not a valid profile name.
    """
    return profile_path(validate_profile_name(name)).exists()


def profile_has_token(name: str) -> bool:
    """Return whether a profile stores a non-empty API token.

    The legacy top-level ``token`` is still honoured for ``"default"`` when no
    profile file was written.

    :param name: Profile name.
    :returns: ``True`` when a token is available for that profile.
    :raises ValueError: When *name* is not a valid profile name.
    """
    validated = validate_profile_name(name)
    profile_config = _read_profile(validated)
    token = profile_config.get("token")
    if isinstance(token, str) and token:
        return True
    if "token" in profile_config:
        return False
    if validated == DEFAULT_PROFILE:
        legacy = _read_global().get("token")
        return isinstance(legacy, str) and bool(legacy)
    return False


def set_active_profile(name: str) -> None:
    """Write the active-profile pointer.

    Unlike :func:`switch_profile` this does not require the profile file to
    exist, which lets authentication create a profile implicitly.

    :param name: Profile to activate.
    :raises ValueError: When *name* is not a valid profile name.
    """
    _write_active_name(validate_profile_name(name))


def switch_profile(name: str) -> None:
    """Point the active-profile file at an existing profile.

    ``"default"`` is allowed even when its file does not exist yet.

    :param name: Profile to activate.
    :raises ValueError: When *name* is invalid or its file does not exist.
    """
    validated = validate_profile_name(name)
    if validated != DEFAULT_PROFILE and not profile_path(validated).exists():
        raise ValueError(f"Profile '{validated}' does not exist.")
    set_active_profile(validated)


def delete_profile(name: str) -> None:
    """Delete a profile file and clear the pointer when it named that profile.

    :param name: Profile to delete.
    :raises ValueError: When *name* is invalid or its file does not exist.
    """
    validated = validate_profile_name(name)
    path = profile_path(validated)
    if not path.exists():
        raise ValueError(f"Profile '{validated}' does not exist.")

    pointer = _read_active_name()
    path.unlink()

    if pointer is None:
        return
    try:
        pointer_name = validate_profile_name(pointer)
    except ValueError:
        return
    if pointer_name != validated:
        return
    try:
        active_profile_path().unlink()
    except FileNotFoundError:
        pass


def load_config() -> dict[str, object]:
    """Read the merged configuration.

    The result contains every global setting plus the effective profile's
    ``token`` and ``phone_area``. A legacy top-level credential is used as a
    fallback when the profile does not define one.

    :returns: The parsed config, or an empty mapping when no file exists.
    """
    _migrate_legacy()
    merged = _read_global()
    for key, value in _read_profile(_effective_profile_name()).items():
        if key in PROFILE_KEYS:
            merged[key] = value
    return merged


def save_config(config: Mapping[str, object]) -> None:
    """Write a merged config mapping back to its global and profile files.

    ``token`` and ``phone_area`` go to the effective profile; every other key
    goes to ``config.toml``. Other profiles and unknown global keys supplied
    by the caller are preserved. The active-profile pointer is never changed
    here — authentication commands do that explicitly.

    :param config: Mapping to serialise, typically the result of
        :func:`load_config`.
    """
    global_config = {key: value for key, value in config.items() if key not in PROFILE_KEYS}
    profile_config = {key: value for key, value in config.items() if key in PROFILE_KEYS}

    stored_global = _read_global()
    stored_global.update(global_config)
    _write_global(stored_global)

    if not profile_config:
        return
    name = _effective_profile_name()
    path = profile_path(name)
    if path.exists():
        existing = _read_profile(name)
        existing.update(profile_config)
        profile_config = existing
    _write_profile(name, profile_config)


def _effective(config: Mapping[str, object] | None) -> Mapping[str, object]:
    """Return *config*, loading it from disk when it is ``None``.

    :param config: Already-parsed config, or ``None`` to load it.
    :returns: The config mapping to read.
    """
    return load_config() if config is None else config


def _store(key: str, value: object) -> None:
    """Persist one config key atomically.

    A ``None`` value deletes the key instead of writing it, and deletion never
    creates a missing file.

    :param key: TOML key to update.
    :param value: New value, or ``None`` to remove the key.
    """
    if key in PROFILE_KEYS:
        _store_profile_key(key, value)
        return
    _store_global_key(key, value)


def _store_global_key(key: str, value: object) -> None:
    """Persist one key in ``config.toml``.

    :param key: TOML key to update.
    :param value: New value, or ``None`` to remove the key.
    """
    if value is None:
        if not config_path().exists():
            return
        config = _read_global()
        config.pop(key, None)
        _write_global(config)
        return
    config = _read_global()
    config[key] = value
    _write_global(config)


def _store_profile_key(key: str, value: object) -> None:
    """Persist one credential key in the effective profile file.

    :param key: TOML key to update.
    :param value: New value, or ``None`` to remove the key.
    """
    name = _effective_profile_name()
    path = profile_path(name)
    if value is None:
        if not path.exists():
            return
        config = _read_profile(name)
        config.pop(key, None)
        _write_profile(name, config)
        return
    config = _read_profile(name)
    config[key] = value
    _write_profile(name, config)


def get_token(config: Mapping[str, object] | None = None) -> str | None:
    """Return the configured API token for the effective profile.

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
    """Store or remove the effective profile's API token.

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
    """Store or remove the effective profile's phone area prefix.

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


def _resolve_profile() -> tuple[str, str]:
    """Resolve the effective profile without touching disk unnecessarily.

    :returns: ``(name, source)`` using the documented precedence.
    :raises ValueError: When ``AUTODL_PROFILE`` holds an invalid name.
    """
    pinned = _profile_override.get()
    if pinned is not None:
        return pinned, "flag"

    environment = os.environ.get(PROFILE_ENV, "").strip()
    if environment:
        return validate_profile_name(environment), "env"

    pointer = _read_active_name()
    if pointer is not None:
        try:
            name = validate_profile_name(pointer)
        except ValueError:
            name = None
        if name is not None:
            return name, "active"

    return DEFAULT_PROFILE, "default"


def _effective_profile_name() -> str:
    """Return the name of the profile config lookups use.

    :returns: The resolved profile name.
    """
    return _resolve_profile()[0]


def _read_global() -> dict[str, object]:
    """Read ``config.toml``.

    :returns: The parsed mapping, or an empty mapping when the file is absent.
    """
    return _read_toml(config_path())


def _read_profile(name: str) -> dict[str, object]:
    """Read one profile's credential file.

    :param name: Profile name.
    :returns: The parsed mapping, or an empty mapping when the file is absent.
    """
    return _read_toml(profile_path(name))


def _read_toml(path: Path) -> dict[str, object]:
    """Read a TOML file, treating a missing file as empty.

    :param path: File to read.
    :returns: The parsed mapping.
    """
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except FileNotFoundError:
        return {}


def _read_active_name() -> str | None:
    """Read the active-profile pointer.

    :returns: The stripped file contents, or ``None`` when unset or empty.
    """
    try:
        value = active_profile_path().read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    return value or None


def _write_global(config: Mapping[str, object]) -> None:
    """Write ``config.toml`` atomically.

    :param config: Global settings to serialise.
    """
    _atomic_write(config_path(), _dump_toml(config))


def _write_profile(name: str, config: Mapping[str, object]) -> None:
    """Write one profile file atomically.

    :param name: Profile name.
    :param config: Credentials to serialise.
    """
    _atomic_write(profile_path(name), _dump_toml(config))


def _write_active_name(name: str) -> None:
    """Write the active-profile pointer atomically.

    :param name: Profile to record.
    """
    _atomic_write(active_profile_path(), f"{name}\n".encode())


def _migrate_legacy() -> None:
    """Move legacy top-level credentials into ``profiles/default.toml``.

    The migration is idempotent: it only acts while ``config.toml`` carries a
    top-level ``token`` or ``phone_area`` and ``profiles/default.toml`` does
    not exist. Failures are ignored so a read-only data directory still yields
    the merged fallback view.
    """
    try:
        global_config = _read_global()
        legacy = {key: global_config[key] for key in PROFILE_KEYS if key in global_config}
        if not legacy:
            return

        default_path = profiles_dir() / f"{DEFAULT_PROFILE}.toml"
        if default_path.exists():
            return

        for key in legacy:
            global_config.pop(key)
        _write_profile(DEFAULT_PROFILE, legacy)
        if _read_active_name() is None:
            _write_active_name(DEFAULT_PROFILE)
        _write_global(global_config)
    except OSError:
        return


def _dump_toml(config: Mapping[str, object]) -> bytes:
    """Serialise a mapping as TOML.

    :param config: Mapping to serialise.
    :returns: The encoded TOML document.
    """
    buffer = io.BytesIO()
    tomli_w.dump(config, buffer)
    return buffer.getvalue()


def _ensure_private_dir(path: Path) -> None:
    """Create *path* when needed and make it private to the user.

    :param path: Directory that will hold a credential or config file.
    """
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass


def _atomic_write(path: Path, data: bytes) -> None:
    """Write *data* to *path* without exposing a partial file.

    The temporary file lives in the destination directory, so :func:`os.replace`
    is atomic. The final file has mode ``0o600``.

    :param path: Destination file.
    :param data: Bytes to write.
    """
    _ensure_private_dir(path.parent)
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}-", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
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
