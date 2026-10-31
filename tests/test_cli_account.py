"""Tests for ``autodl account balance`` through the real Click entry point."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from autodl_cli import config as config_module
from autodl_cli.commands import account as account_commands
from autodl_cli.errors import AuthError
from autodl_cli.main import main

TOKEN = "fake-token"
BALANCE = {
    "assets": 12345,
    "blocked_asset": 0,
    "accumulate": 67890,
    "voucher_balance": 1000,
    "available_coupon_num": 2,
    "to_expire_voucher_num": 1,
    "certain_conditions_voucher_balance": 0,
    "total_recharge_asset": 500000,
}


@pytest.fixture
def home(monkeypatch, tmp_path: Path) -> Path:
    """Point the data tree at an isolated temporary directory.

    :param monkeypatch: pytest's monkeypatch fixture.
    :param tmp_path: Per-test temporary directory.
    :returns: The redirected home directory.
    """
    monkeypatch.setenv("AUTODL_CLI_HOME", str(tmp_path))
    return tmp_path


def _seed_token() -> None:
    """Store a token so the balance command can run."""
    config_module.save_config({"token": TOKEN})


def test_balance_json_returns_raw_api_data(home: Path, monkeypatch) -> None:
    """``--json`` emits the handler result unchanged."""
    _seed_token()
    monkeypatch.setattr(
        account_commands.account_handler,
        "get_balance",
        lambda client, *, charge_type: BALANCE,
    )

    result = CliRunner().invoke(main, ["--json", "account", "balance"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == BALANCE


def test_balance_human_output_converts_money_to_yuan(home: Path, monkeypatch) -> None:
    """The table shows labels and yuan amounts rather than raw integers."""
    _seed_token()
    monkeypatch.setattr(
        account_commands.account_handler,
        "get_balance",
        lambda client, *, charge_type: BALANCE,
    )

    result = CliRunner().invoke(main, ["account", "balance"])

    assert result.exit_code == 0, result.output
    assert "Account balance (payg)" in result.output
    assert "Available" in result.output
    assert "¥12.345" in result.output
    assert "Available coupons" in result.output
    assert TOKEN not in result.output


def test_balance_forwards_charge_type(home: Path, monkeypatch) -> None:
    """``--charge-type`` reaches the handler."""
    _seed_token()
    captured: dict[str, object] = {}

    def fake_get_balance(client, *, charge_type):
        captured["charge_type"] = charge_type
        return BALANCE

    monkeypatch.setattr(account_commands.account_handler, "get_balance", fake_get_balance)

    result = CliRunner().invoke(main, ["--json", "account", "balance", "--charge-type", "prepaid"])

    assert result.exit_code == 0, result.output
    assert captured == {"charge_type": "prepaid"}


def test_balance_requires_token(home: Path, monkeypatch) -> None:
    """A missing token fails cleanly with the paste hint."""
    monkeypatch.setattr(
        account_commands.account_handler,
        "get_balance",
        lambda *args, **kwargs: pytest.fail("the handler must not run without a token"),
    )

    result = CliRunner().invoke(main, ["--json", "account", "balance"])

    assert result.exit_code == 1
    assert "autodl auth paste" in result.output
    assert "Traceback" not in result.output


def test_balance_api_failure_is_a_clean_click_exception(home: Path, monkeypatch) -> None:
    """An API failure exits 1 without a traceback."""
    _seed_token()

    def failing_get_balance(client, *, charge_type):
        raise AuthError("token expired")

    monkeypatch.setattr(account_commands.account_handler, "get_balance", failing_get_balance)

    result = CliRunner().invoke(main, ["--json", "account", "balance"])

    assert result.exit_code == 1
    assert "token expired" in result.output
    assert "Traceback" not in result.output
