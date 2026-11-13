"""Tests for the ``autodl profile`` command group."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from autodl_cli import config as config_module
from autodl_cli.main import main

TOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dummysignature"
FINGERPRINT = "0123456789abcdef0123456789abcdef"


@pytest.fixture
def home(monkeypatch, tmp_path: Path) -> Path:
    """Point the data tree at an isolated temporary directory.

    :param monkeypatch: pytest's monkeypatch fixture.
    :param tmp_path: Per-test temporary directory.
    :returns: The redirected home directory.
    """
    monkeypatch.setenv("AUTODL_CLI_HOME", str(tmp_path))
    monkeypatch.delenv(config_module.PROFILE_ENV, raising=False)
    return tmp_path


def _seed_profile(name: str, token: str = TOKEN) -> None:
    """Create a profile holding one token.

    :param name: Profile name.
    :param token: Token to store.
    """
    with config_module.use_profile(name):
        config_module.save_config({"token": token})


def test_list_json_includes_default_and_marks_active(home: Path) -> None:
    """The listing always includes ``default`` and reports authentication."""
    _seed_profile("work")

    result = CliRunner().invoke(main, ["--json", "profile", "list"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == [
        {"name": "default", "active": True, "authenticated": False},
        {"name": "work", "active": False, "authenticated": True},
    ]


def test_list_human_output(home: Path) -> None:
    """The human listing names every profile."""
    _seed_profile("work")

    result = CliRunner().invoke(main, ["profile", "list"])

    assert result.exit_code == 0, result.output
    assert "Profiles" in result.output
    assert "default" in result.output
    assert "work" in result.output


def test_current_default_json(home: Path) -> None:
    """With nothing configured the effective profile is the implicit default."""
    result = CliRunner().invoke(main, ["--json", "profile", "current"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {"profile": "default", "source": "default"}


def test_current_human_output(home: Path) -> None:
    """The human output shows the name and the selection source."""
    result = CliRunner().invoke(main, ["profile", "current"])

    assert result.exit_code == 0, result.output
    assert "default" in result.output
    assert "Source" in result.output


def test_global_profile_flag_wins(home: Path) -> None:
    """``--profile`` selects the profile and is reported as the source."""
    _seed_profile("work")

    result = CliRunner().invoke(main, ["--json", "--profile", "work", "profile", "current"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {"profile": "work", "source": "flag"}


def test_profile_flag_does_not_leak_between_invocations(home: Path) -> None:
    """The pin is reset when the Click context closes."""
    runner = CliRunner()

    first = runner.invoke(main, ["--json", "--profile", "work", "profile", "current"])
    second = runner.invoke(main, ["--json", "profile", "current"])

    assert json.loads(first.output) == {"profile": "work", "source": "flag"}
    assert json.loads(second.output) == {"profile": "default", "source": "default"}


def test_autodl_profile_environment_variable(home: Path) -> None:
    """``AUTODL_PROFILE`` is used when the flag is absent."""
    result = CliRunner().invoke(
        main,
        ["--json", "profile", "current"],
        env={"AUTODL_PROFILE": "work"},
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {"profile": "work", "source": "env"}


def test_switch_writes_pointer_and_current_reports_active(home: Path) -> None:
    """Switching an existing profile writes the active pointer."""
    _seed_profile("work")
    runner = CliRunner()

    switched = runner.invoke(main, ["--json", "profile", "switch", "work"])

    assert switched.exit_code == 0, switched.output
    assert json.loads(switched.output) == {"profile": "work"}
    assert (home / "active_profile").read_text(encoding="utf-8").strip() == "work"

    current = runner.invoke(main, ["--json", "profile", "current"])
    assert json.loads(current.output) == {"profile": "work", "source": "active"}


def test_switch_allows_implicit_default(home: Path) -> None:
    """``default`` may be activated before its file exists."""
    result = CliRunner().invoke(main, ["--json", "profile", "switch", "default"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {"profile": "default"}
    assert (home / "active_profile").read_text(encoding="utf-8").strip() == "default"


def test_switch_missing_profile_is_a_clean_error(home: Path) -> None:
    """Switching to an unknown profile exits 1 without a traceback."""
    result = CliRunner().invoke(main, ["profile", "switch", "missing"])

    assert result.exit_code == 1
    assert "does not exist" in result.output
    assert "Traceback" not in result.output


def test_switch_invalid_name_is_a_clean_error(home: Path) -> None:
    """A path-like name is rejected before any file is touched."""
    result = CliRunner().invoke(main, ["profile", "switch", "../escape"])

    assert result.exit_code == 1
    assert "Invalid profile name" in result.output
    assert "Traceback" not in result.output


def test_delete_with_yes_clears_the_pointer(home: Path) -> None:
    """``--yes`` deletes the file, clears the pointer, and reports JSON."""
    _seed_profile("work")
    config_module.switch_profile("work")
    runner = CliRunner()

    result = runner.invoke(main, ["--json", "profile", "delete", "work", "--yes"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {"profile": "work", "deleted": True}
    assert not (home / "profiles" / "work.toml").exists()
    assert not (home / "active_profile").exists()
    assert config_module.current_profile() == ("default", "default")


def test_delete_missing_profile_is_a_clean_error(home: Path) -> None:
    """Deleting an unknown profile exits 1 without a traceback."""
    result = CliRunner().invoke(main, ["profile", "delete", "missing", "--yes"])

    assert result.exit_code == 1
    assert "does not exist" in result.output
    assert "Traceback" not in result.output


def test_delete_asks_for_confirmation(home: Path) -> None:
    """Declining the prompt leaves the profile in place."""
    _seed_profile("work")

    result = CliRunner().invoke(main, ["profile", "delete", "work"], input="n\n")

    assert result.exit_code == 1
    assert "Delete profile 'work'?" in result.output
    assert (home / "profiles" / "work.toml").exists()


def test_invalid_global_profile_flag_is_clean(home: Path) -> None:
    """Click reports an invalid ``--profile`` value without a traceback."""
    result = CliRunner().invoke(main, ["--profile", "bad/name", "profile", "current"])

    assert result.exit_code == 2
    assert "Invalid profile name" in result.output
    assert "Traceback" not in result.output


def test_invalid_environment_profile_is_clean(home: Path) -> None:
    """An invalid ``AUTODL_PROFILE`` value is rejected as a usage error."""
    result = CliRunner().invoke(
        main,
        ["profile", "current"],
        env={"AUTODL_PROFILE": "bad/name"},
    )

    assert result.exit_code == 2
    assert "AUTODL_PROFILE" in result.output
    assert "Invalid profile name" in result.output
    assert "Traceback" not in result.output


def test_config_token_uses_the_selected_profile(home: Path) -> None:
    """``config token set`` writes to the profile pinned by ``--profile``."""
    result = CliRunner().invoke(main, ["--profile", "work", "config", "token", "set", TOKEN])

    assert result.exit_code == 0, result.output
    assert "(profile work)" in result.output
    assert config_module.profile_has_token("work") is True
    assert not (home / "profiles" / "default.toml").exists()


def test_auth_paste_creates_and_activates_the_selected_profile(home: Path) -> None:
    """A token paste under ``--profile`` creates that profile and activates it."""
    text = f"Authorization: Bearer {TOKEN}"

    result = CliRunner().invoke(
        main,
        ["--json", "--profile", "work", "auth", "paste", "--no-verify"],
        input=text,
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["profile"] == "work"
    assert payload["profile_path"] == str(home / "profiles" / "work.toml")
    assert config_module.profile_has_token("work") is True
    assert (home / "active_profile").read_text(encoding="utf-8").strip() == "work"


def test_fingerprint_only_paste_does_not_create_a_profile(home: Path) -> None:
    """A fingerprint-only paste saves global data but no profile or pointer."""
    result = CliRunner().invoke(
        main,
        ["--profile", "work", "auth", "paste"],
        input=FINGERPRINT,
    )

    assert result.exit_code == 0, result.output
    assert not (home / "profiles").exists()
    assert not (home / "active_profile").exists()
    assert config_module.load_config() == {"device_fingerprint": FINGERPRINT}
