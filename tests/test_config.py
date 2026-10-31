"""Tests for :mod:`autodl_cli.config`."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from autodl_cli.client import APP_VERSION, DEFAULT_BASE_URL, DEFAULT_TIMEOUT
from autodl_cli.config import (
    DEFAULT_PHONE_AREA,
    config_path,
    get_app_version,
    get_base_url,
    get_device_fingerprint,
    get_phone_area,
    get_timeout,
    get_token,
    load_config,
    save_config,
    set_app_version,
    set_base_url,
    set_device_fingerprint,
    set_phone_area,
    set_timeout,
    set_token,
)

#: Fingerprint-shaped value used to make round-trip failures obvious.
_FINGERPRINT = "0123456789abcdef0123456789abcdef"


@pytest.fixture
def home(monkeypatch, tmp_path: Path) -> Path:
    """Point ``AUTODL_CLI_HOME`` at an isolated temporary directory.

    :param monkeypatch: pytest's monkeypatch fixture.
    :param tmp_path: Per-test temporary directory.
    :returns: The redirected home directory.
    """
    target = tmp_path / "autodl-home"
    monkeypatch.setenv("AUTODL_CLI_HOME", str(target))
    return target


def test_missing_file_returns_empty(home: Path) -> None:
    """A missing config file parses as an empty mapping."""
    assert load_config() == {}
    assert config_path() == home / "config.toml"


def test_save_load_roundtrip(home: Path) -> None:
    """Every key the caller supplies survives a save/load cycle."""
    config = {
        "token": "fake-token",
        "phone_area": "+86",
        "device_fingerprint": _FINGERPRINT,
        "default_region": "west-b",
    }

    save_config(config)

    assert load_config() == config


def test_file_is_private_and_parent_created(home: Path) -> None:
    """Saving creates the parent directory and a mode-0600 file."""
    save_config({"token": "fake-token"})
    path = config_path()

    assert path.parent.is_dir()
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_save_preserves_unrelated_keys(home: Path) -> None:
    """Keys written by other features are not dropped by a later save."""
    save_config({"token": "first", "default_region": "west-b"})
    second = load_config()
    second["token"] = "second"

    save_config(second)

    loaded = load_config()
    assert loaded["token"] == "second"
    assert loaded["default_region"] == "west-b"


def test_getters_fall_back_to_defaults(home: Path) -> None:
    """An empty config yields the documented defaults for every optional key."""
    assert get_token() is None
    assert get_device_fingerprint() is None
    assert get_phone_area() == DEFAULT_PHONE_AREA
    assert get_base_url() == DEFAULT_BASE_URL
    assert get_timeout() == DEFAULT_TIMEOUT
    assert get_app_version() == APP_VERSION


def test_setters_roundtrip_and_normalise(home: Path) -> None:
    """Setters persist values and apply their documented normalisation."""
    set_token("token-value")
    set_device_fingerprint(_FINGERPRINT.upper())
    set_phone_area("+1")
    set_base_url("https://mirror.example.com/")
    set_timeout(5)
    set_app_version("v9.99.0")

    assert get_token() == "token-value"
    assert get_device_fingerprint() == _FINGERPRINT
    assert get_phone_area() == "+1"
    assert get_base_url() == "https://mirror.example.com"
    assert get_timeout() == 5.0
    assert get_app_version() == "v9.99.0"


@pytest.mark.parametrize(
    ("setter", "value"),
    [
        (set_token, "   "),
        (set_device_fingerprint, "not-a-fingerprint"),
        (set_phone_area, "86"),
        (set_base_url, "ftp://example.com"),
        (set_base_url, ""),
        (set_timeout, 0),
        (set_timeout, 601),
        (set_app_version, "6.53.0"),
    ],
)
def test_setters_reject_invalid_values(home: Path, setter, value) -> None:
    """Invalid values raise ``ValueError`` and leave the file untouched."""
    with pytest.raises(ValueError):
        setter(value)

    assert load_config() == {}


@pytest.mark.parametrize(
    ("setter", "getter", "value"),
    [
        (set_token, get_token, "token-value"),
        (set_device_fingerprint, get_device_fingerprint, _FINGERPRINT),
        (set_phone_area, get_phone_area, "+1"),
        (set_base_url, get_base_url, "https://mirror.example.com"),
        (set_timeout, get_timeout, 5),
        (set_app_version, get_app_version, "v9.99.0"),
    ],
)
def test_none_removes_key(home: Path, setter, getter, value) -> None:
    """Passing ``None`` deletes the key so the default applies again."""
    setter(value)
    assert load_config() != {}

    setter(None)

    assert load_config() == {}
    assert getter() != value
