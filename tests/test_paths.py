"""Tests for :mod:`autodl_cli.paths` and the ``AUTODL_CLI_HOME`` override."""

from __future__ import annotations

from pathlib import Path

from autodl_cli.paths import HOME_ENV, autodl_home


def test_home_env_name() -> None:
    """The data-directory environment variable name stays stable."""
    assert HOME_ENV == "AUTODL_CLI_HOME"


def test_default_home(monkeypatch, tmp_path: Path) -> None:
    """Without the override the directory is ``$HOME/.autodl-cli``."""
    monkeypatch.delenv(HOME_ENV, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))

    assert autodl_home() == tmp_path / ".autodl-cli"
    assert not (tmp_path / ".autodl-cli").exists()


def test_override(monkeypatch, tmp_path: Path) -> None:
    """A non-empty override is returned verbatim."""
    target = tmp_path / "custom-data"
    monkeypatch.setenv(HOME_ENV, str(target))

    assert autodl_home() == target


def test_override_expands_user(monkeypatch, tmp_path: Path) -> None:
    """A leading ``~`` in the override is expanded."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv(HOME_ENV, "~/sandbox")

    assert autodl_home() == tmp_path / "sandbox"


def test_empty_override_falls_back(monkeypatch, tmp_path: Path) -> None:
    """An empty override behaves as though it were unset."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv(HOME_ENV, "")

    assert autodl_home() == tmp_path / ".autodl-cli"
