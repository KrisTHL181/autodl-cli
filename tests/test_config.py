"""Tests for :mod:`autodl_cli.config`."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from autodl_cli.config import config_path, load_config, save_config

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
