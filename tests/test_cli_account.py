"""Tests for ``autodl account`` commands through the real Click entry point."""

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
    "assets": 12.345,
    "blocked_asset": 0.0,
    "accumulate": 67.89,
    "voucher_balance": 1.0,
    "available_coupon_num": 2,
    "to_expire_voucher_num": 1,
    "certain_conditions_voucher_balance": 0.0,
    "total_recharge_asset": 500.0,
}
USAGE = [
    {
        "asset_sum": 78.59,
        "pay_by_balance_sum": 78.59,
        "pay_by_voucher_sum": 0.0,
        "refund_asset_sum": 0.0,
        "report_date": "2025-12",
        "transaction_count": 83,
    },
    {
        "asset_sum": 12.5,
        "pay_by_balance_sum": 10.0,
        "pay_by_voucher_sum": 2.5,
        "refund_asset_sum": 0.0,
        "report_date": "2026-01",
        "transaction_count": 1,
    },
]
ACCOUNT = {
    "id": 751375,
    "username": "tester",
    "nickname": "",
    "email": "tester@example.com",
    "email_confirmed": True,
    "phone_area": "+86",
    "phone": "13800138000",
    "status": "normal",
    "created_at": "2026-01-01T00:00:00+08:00",
    "logged_in_at": "2026-10-31T23:28:26.905+08:00",
    "max_instance_num": 30,
    "sub_user_num": 10,
    "private_image_num": 20,
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


def test_balance_json_returns_yuan_data(home: Path, monkeypatch) -> None:
    """``--json`` emits the handler's yuan values unchanged."""
    _seed_token()
    monkeypatch.setattr(
        account_commands.account_handler,
        "get_balance",
        lambda client, *, charge_type: BALANCE,
    )

    result = CliRunner().invoke(main, ["--json", "account", "balance"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == BALANCE


def test_balance_human_output_shows_yuan_amounts(home: Path, monkeypatch) -> None:
    """The table shows labels and the handler's yuan amounts."""
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


def test_usage_json_returns_normalised_floats(home: Path, monkeypatch) -> None:
    """``--json`` emits the handler's normalised usage entries."""
    _seed_token()
    monkeypatch.setattr(
        account_commands.account_handler,
        "get_usage_statistics",
        lambda client, *, granularity, sub_name, exclude_sub_user: USAGE,
    )

    result = CliRunner().invoke(main, ["--json", "account", "usage"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == USAGE
    assert TOKEN not in result.output


def test_usage_human_output_shows_periods_and_total(home: Path, monkeypatch) -> None:
    """The table shows each period and a summed Total row."""
    _seed_token()
    monkeypatch.setattr(
        account_commands.account_handler,
        "get_usage_statistics",
        lambda client, *, granularity, sub_name, exclude_sub_user: USAGE,
    )

    result = CliRunner().invoke(main, ["account", "usage"])

    assert result.exit_code == 0, result.output
    assert "Usage (monthly)" in result.output
    assert "2025-12" in result.output
    assert "2026-01" in result.output
    assert "Total" in result.output
    assert "¥78.590" in result.output
    assert "¥91.090" in result.output
    assert "84" in result.output
    assert TOKEN not in result.output


def test_usage_forwards_options(home: Path, monkeypatch) -> None:
    """Granularity and sub-user filters reach the handler."""
    _seed_token()
    captured: dict[str, object] = {}

    def fake_get_usage_statistics(client, *, granularity, sub_name, exclude_sub_user):
        captured.update(
            granularity=granularity,
            sub_name=sub_name,
            exclude_sub_user=exclude_sub_user,
        )
        return USAGE

    monkeypatch.setattr(account_commands.account_handler, "get_usage_statistics", fake_get_usage_statistics)

    result = CliRunner().invoke(
        main,
        ["--json", "account", "usage", "-g", "daily", "--sub-name", "alice", "--exclude-sub-user"],
    )

    assert result.exit_code == 0, result.output
    assert captured == {
        "granularity": "daily",
        "sub_name": "alice",
        "exclude_sub_user": True,
    }


def test_usage_api_failure_is_a_clean_click_exception(home: Path, monkeypatch) -> None:
    """An API failure exits 1 without a traceback."""
    _seed_token()

    def failing_get_usage_statistics(client, *, granularity, sub_name, exclude_sub_user):
        raise AuthError("token expired")

    monkeypatch.setattr(account_commands.account_handler, "get_usage_statistics", failing_get_usage_statistics)

    result = CliRunner().invoke(main, ["--json", "account", "usage"])

    assert result.exit_code == 1
    assert "token expired" in result.output
    assert "Traceback" not in result.output


def test_me_json_returns_raw_api_data(home: Path, monkeypatch) -> None:
    """``--json`` emits the handler result unchanged."""
    _seed_token()
    monkeypatch.setattr(account_commands.account_handler, "get_me", lambda client: ACCOUNT)

    result = CliRunner().invoke(main, ["--json", "account", "me"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == ACCOUNT
    assert TOKEN not in result.output


def test_me_human_output_shows_profile(home: Path, monkeypatch) -> None:
    """The table shows identity, contact, and quota fields."""
    _seed_token()
    monkeypatch.setattr(account_commands.account_handler, "get_me", lambda client: ACCOUNT)

    result = CliRunner().invoke(main, ["account", "me"])

    assert result.exit_code == 0, result.output
    assert "Account" in result.output
    assert "tester" in result.output
    assert "751375" in result.output
    assert "+86 13800138000" in result.output
    assert "2026-10-31 23:28:26" in result.output
    assert "Max instances" in result.output
    assert TOKEN not in result.output


def test_me_requires_token(home: Path, monkeypatch) -> None:
    """A missing token fails cleanly with the paste hint."""
    monkeypatch.setattr(
        account_commands.account_handler,
        "get_me",
        lambda *args, **kwargs: pytest.fail("the handler must not run without a token"),
    )

    result = CliRunner().invoke(main, ["--json", "account", "me"])

    assert result.exit_code == 1
    assert "autodl auth paste" in result.output
    assert "Traceback" not in result.output


def test_me_api_failure_is_a_clean_click_exception(home: Path, monkeypatch) -> None:
    """An API failure exits 1 without a traceback."""
    _seed_token()

    def failing_get_me(client):
        raise AuthError("token expired")

    monkeypatch.setattr(account_commands.account_handler, "get_me", failing_get_me)

    result = CliRunner().invoke(main, ["--json", "account", "me"])

    assert result.exit_code == 1
    assert "token expired" in result.output
    assert "Traceback" not in result.output
