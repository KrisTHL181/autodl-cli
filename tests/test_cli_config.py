"""Tests for ``autodl config`` through the real Click entry point."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from autodl_cli import config as config_module
from autodl_cli.client import DEFAULT_BASE_URL, DEFAULT_TIMEOUT
from autodl_cli.main import main

TOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dummysignature"


@pytest.fixture
def home(monkeypatch, tmp_path: Path) -> Path:
    """Point the data tree at an isolated temporary directory.

    :param monkeypatch: pytest's monkeypatch fixture.
    :param tmp_path: Per-test temporary directory.
    :returns: The redirected home directory.
    """
    monkeypatch.setenv("AUTODL_CLI_HOME", str(tmp_path))
    return tmp_path


def test_show_reports_the_default(home: Path) -> None:
    """An empty config still shows the effective default."""
    result = CliRunner().invoke(main, ["config", "base-url", "show"])

    assert result.exit_code == 0, result.output
    assert DEFAULT_BASE_URL in result.output


def test_set_persists_and_show_reads_it(home: Path) -> None:
    """``set`` writes the value, and ``show`` reads it back."""
    runner = CliRunner()

    result = runner.invoke(main, ["config", "base-url", "set", "https://mirror.example.com/"])
    assert result.exit_code == 0, result.output
    assert "https://mirror.example.com" in result.output

    result = runner.invoke(main, ["config", "base-url", "show"])
    assert result.exit_code == 0, result.output
    assert "https://mirror.example.com" in result.output
    assert config_module.load_config()["base_url"] == "https://mirror.example.com"


def test_set_uses_the_click_type(home: Path) -> None:
    """Numeric settings are converted by Click and stored as numbers."""
    result = CliRunner().invoke(main, ["config", "timeout", "set", "5"])

    assert result.exit_code == 0, result.output
    assert config_module.load_config()["timeout"] == 5.0


def test_clear_restores_the_default(home: Path) -> None:
    """``clear`` resets the key to its default value."""
    runner = CliRunner()
    runner.invoke(main, ["config", "timeout", "set", "5"])

    result = runner.invoke(main, ["config", "timeout", "clear"])

    assert result.exit_code == 0, result.output
    assert config_module.get_timeout() == DEFAULT_TIMEOUT


def test_json_output_is_machine_readable(home: Path) -> None:
    """``--json`` emits a single object keyed by the config name."""
    runner = CliRunner()
    runner.invoke(main, ["config", "timeout", "set", "5"])

    result = runner.invoke(main, ["--json", "config", "timeout", "show"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {"timeout": 5.0}


def test_token_is_masked_in_human_and_json_output(home: Path) -> None:
    """The token never appears in full in any command's output."""
    runner = CliRunner()
    runner.invoke(main, ["config", "token", "set", TOKEN])

    human = runner.invoke(main, ["config", "token", "show"])
    machine = runner.invoke(main, ["--json", "config", "token", "show"])

    assert human.exit_code == 0, human.output
    assert machine.exit_code == 0, machine.output
    assert TOKEN not in human.output
    assert TOKEN not in machine.output
    assert "…" in human.output
    assert json.loads(machine.output)["token"].endswith("ture")


def test_clearing_the_token_explains_how_to_authenticate(home: Path) -> None:
    """An empty token shows the login hint instead of a bare ``None``."""
    runner = CliRunner()
    runner.invoke(main, ["config", "token", "set", TOKEN])

    result = runner.invoke(main, ["config", "token", "clear"])

    assert result.exit_code == 0, result.output
    assert config_module.get_token() is None

    result = runner.invoke(main, ["config", "token", "show"])
    assert "autodl auth paste" in result.output


def test_invalid_value_is_a_clean_error(home: Path) -> None:
    """A rejected value exits 1 without a traceback and writes nothing."""
    result = CliRunner().invoke(main, ["config", "device-fingerprint", "set", "not-a-fingerprint"])

    assert result.exit_code == 1
    assert "32 lowercase hexadecimal" in result.output
    assert "Traceback" not in result.output
    assert config_module.load_config() == {}
