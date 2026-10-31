"""Tests for ``autodl auth login`` through the real Click entry point."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from autodl_cli import config as config_module
from autodl_cli.commands import auth as auth_commands
from autodl_cli.errors import AuthError
from autodl_cli.main import main

PHONE = "13800138000"
PASSWORD = "secret"
TOKEN = "fake-token"
USER = {"id": 42, "username": "tester"}
STORED_FINGERPRINT = "abcdef0123456789abcdef0123456789"


@pytest.fixture
def home(monkeypatch, tmp_path: Path) -> Path:
    """Point the data tree at an isolated temporary directory.

    :param monkeypatch: pytest's monkeypatch fixture.
    :param tmp_path: Per-test temporary directory.
    :returns: The redirected home directory.
    """
    monkeypatch.setenv("AUTODL_CLI_HOME", str(tmp_path))
    return tmp_path


def _seed_fingerprint() -> None:
    """Store a browser fingerprint so password login can proceed."""
    config_module.save_config({"device_fingerprint": STORED_FINGERPRINT})


def test_login_json_success_persists_token(home: Path, monkeypatch) -> None:
    """A successful login emits JSON, saves the token, and hides the token."""
    _seed_fingerprint()
    monkeypatch.setattr(
        auth_commands.auth_handler,
        "login",
        lambda client, phone, password, *, phone_area, device_fingerprint: {
            "token": TOKEN,
            "user": USER,
            "device_fingerprint": device_fingerprint,
        },
    )

    result = CliRunner().invoke(
        main,
        ["--json", "auth", "login", "--phone", PHONE, "--password", PASSWORD],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload == {
        "authenticated": True,
        "user": USER,
        "config_path": str(home / "config.toml"),
    }
    assert TOKEN not in result.output

    saved = config_module.load_config()
    assert saved["token"] == TOKEN
    assert saved["phone_area"] == "+86"
    assert saved["device_fingerprint"] == STORED_FINGERPRINT


def test_login_reuses_stored_fingerprint_and_preserves_config(home: Path, monkeypatch) -> None:
    """A valid stored fingerprint is reused and unrelated keys survive."""
    config_module.save_config(
        {
            "token": "old-token",
            "device_fingerprint": STORED_FINGERPRINT,
            "default_region": "west-b",
        }
    )
    captured: dict[str, object] = {}

    def fake_login(client, phone, password, *, phone_area, device_fingerprint):
        captured["fingerprint"] = device_fingerprint
        captured["phone_area"] = phone_area
        return {
            "token": TOKEN,
            "user": USER,
            "device_fingerprint": device_fingerprint,
        }

    monkeypatch.setattr(auth_commands.auth_handler, "login", fake_login)

    result = CliRunner().invoke(
        main,
        ["--json", "auth", "login", "--phone", PHONE, "--password", PASSWORD],
    )

    assert result.exit_code == 0, result.output
    assert captured == {"fingerprint": STORED_FINGERPRINT, "phone_area": "+86"}

    saved = config_module.load_config()
    assert saved["device_fingerprint"] == STORED_FINGERPRINT
    assert saved["token"] == TOKEN
    assert saved["default_region"] == "west-b"


def test_login_failure_is_a_clean_click_exception(home: Path, monkeypatch) -> None:
    """A failed login exits 1 with a clean message and writes no token."""
    _seed_fingerprint()

    def failing_login(client, phone, password, *, phone_area, device_fingerprint):
        raise AuthError("invalid credentials")

    monkeypatch.setattr(auth_commands.auth_handler, "login", failing_login)

    result = CliRunner().invoke(
        main,
        ["--json", "auth", "login", "--phone", PHONE, "--password", PASSWORD],
    )

    assert result.exit_code == 1
    assert "invalid credentials" in result.output
    assert "Traceback" not in result.output
    assert config_module.load_config().get("token") is None


def test_password_can_come_from_environment(home: Path, monkeypatch) -> None:
    """``AUTODL_PASSWORD`` supplies the password without an option or prompt."""
    _seed_fingerprint()
    captured: dict[str, object] = {}

    def fake_login(client, phone, password, *, phone_area, device_fingerprint):
        captured["password"] = password
        return {"token": TOKEN, "user": USER, "device_fingerprint": device_fingerprint}

    monkeypatch.setattr(auth_commands.auth_handler, "login", fake_login)

    result = CliRunner().invoke(
        main,
        ["--json", "auth", "login", "--phone", PHONE],
        env={"AUTODL_PASSWORD": PASSWORD},
    )

    assert result.exit_code == 0, result.output
    assert captured["password"] == PASSWORD


def test_login_prompts_for_password_once(home: Path, monkeypatch) -> None:
    """Interactive login reads a single password line, not a confirmation."""
    _seed_fingerprint()
    captured: dict[str, object] = {}

    def fake_login(client, phone, password, *, phone_area, device_fingerprint):
        captured["password"] = password
        return {"token": TOKEN, "user": USER, "device_fingerprint": device_fingerprint}

    monkeypatch.setattr(auth_commands.auth_handler, "login", fake_login)

    result = CliRunner().invoke(
        main,
        ["auth", "login", "--phone", PHONE],
        input="secret\n",
    )

    assert result.exit_code == 0, result.output
    assert captured["password"] == PASSWORD


def test_login_without_fingerprint_explains_paste(home: Path, monkeypatch) -> None:
    """Password login refuses to generate a random fingerprint or call the API."""

    def fail_client(*args, **kwargs):
        raise AssertionError("no API client should be constructed without a fingerprint")

    def fail_login(*args, **kwargs):
        raise AssertionError("the login handler must not run without a fingerprint")

    monkeypatch.setattr(auth_commands, "AutoDLClient", fail_client)
    monkeypatch.setattr(auth_commands.auth_handler, "login", fail_login)

    result = CliRunner().invoke(
        main,
        ["--json", "auth", "login", "--phone", PHONE, "--password", PASSWORD],
    )

    assert result.exit_code == 1
    assert "autodl auth paste" in result.output
    assert "No device fingerprint is stored" in result.output
    assert "Traceback" not in result.output
