"""Tests for ``autodl instance`` commands through the real Click entry point."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from autodl_cli import config as config_module
from autodl_cli.commands import instance as instance_commands
from autodl_cli.errors import AuthError
from autodl_cli.main import main

TOKEN = "fake-token"
INSTANCES = [
    {
        "uuid": "cs1a2b3c4d5e6f7g8h",
        "name": "",
        "status": "running",
        "sub_status": "",
        "snapshot_gpu_alias_name": "RTX 3090",
        "req_gpu_amount": 1,
        "region_name": "内蒙B区",
        "charge_type": "payg",
        "payg_price": 1480,
        "daily_price": 0,
        "ssh_command": "ssh -p 39684 root@connect.nmb2.seetacloud.com",
    },
    {
        "uuid": "cs9z8y7x6w5v4u3t2s",
        "name": "trainer",
        "status": "shutdown",
        "sub_status": "",
        "snapshot_gpu_alias_name": "RTX 3080 Ti",
        "req_gpu_amount": 3,
        "region_name": "西北B区",
        "charge_type": "payg",
        "payg_price": 3250,
        "daily_price": 0,
        "ssh_command": "ssh -p 35677 root@connect.westd.seetacloud.com",
    },
]


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
    """Store a token so the instance commands can run."""
    config_module.save_config({"token": TOKEN})


def test_list_json_returns_raw_instances(home: Path, monkeypatch) -> None:
    """``--json`` emits the handler result unchanged."""
    _seed_token()
    monkeypatch.setattr(
        instance_commands.instance_handler,
        "list_instances",
        lambda client, **kwargs: INSTANCES,
    )

    result = CliRunner().invoke(main, ["--json", "instance", "list"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == INSTANCES
    assert TOKEN not in result.output


def test_list_human_output_shows_instances(home: Path, monkeypatch) -> None:
    """The table shows IDs, status, GPU, region, price, and SSH command."""
    _seed_token()
    monkeypatch.setattr(
        instance_commands.instance_handler,
        "list_instances",
        lambda client, **kwargs: INSTANCES,
    )

    result = CliRunner().invoke(main, ["instance", "list"])

    assert result.exit_code == 0, result.output
    assert "Instances (2)" in result.output
    assert "cs1a2b3c4d5e6f7g8h" in result.output
    assert "trainer" in result.output
    assert "running" in result.output
    assert "RTX 3090" in result.output
    assert "RTX 3080 Ti ×3" in result.output
    assert "内蒙B区" in result.output
    assert "¥1.480/h" in result.output
    assert "ssh -p 39684" in result.output
    assert TOKEN not in result.output


def test_list_empty_result_prints_message(home: Path, monkeypatch) -> None:
    """An empty account prints a short message instead of an empty table."""
    _seed_token()
    monkeypatch.setattr(instance_commands.instance_handler, "list_instances", lambda client, **kwargs: [])

    result = CliRunner().invoke(main, ["instance", "list"])

    assert result.exit_code == 0, result.output
    assert "No instances found." in result.output


def test_list_forwards_filters_and_page_size(home: Path, monkeypatch) -> None:
    """Every filter option and the page size reach the handler."""
    _seed_token()
    captured: dict[str, object] = {}

    def fake_list_instances(client, **kwargs):
        captured.update(kwargs)
        return INSTANCES

    monkeypatch.setattr(instance_commands.instance_handler, "list_instances", fake_list_instances)

    result = CliRunner().invoke(
        main,
        [
            "--json",
            "instance",
            "list",
            "--status",
            "running",
            "--status",
            "shutdown",
            "--charge-type",
            "payg",
            "--sub-name",
            "alice",
            "--unbind-sub-user",
            "--page-size",
            "25",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured == {
        "page_size": 25,
        "statuses": ("running", "shutdown"),
        "charge_types": ("payg",),
        "sub_name": "alice",
        "unbind_sub_user": True,
    }


def test_list_requires_token(home: Path, monkeypatch) -> None:
    """A missing token fails cleanly with the paste hint."""
    monkeypatch.setattr(
        instance_commands.instance_handler,
        "list_instances",
        lambda *args, **kwargs: pytest.fail("the handler must not run without a token"),
    )

    result = CliRunner().invoke(main, ["--json", "instance", "list"])

    assert result.exit_code == 1
    assert "autodl auth paste" in result.output
    assert "Traceback" not in result.output


def test_list_api_failure_is_a_clean_click_exception(home: Path, monkeypatch) -> None:
    """An API failure exits 1 without a traceback."""
    _seed_token()

    def failing_list_instances(client, **kwargs):
        raise AuthError("token expired")

    monkeypatch.setattr(instance_commands.instance_handler, "list_instances", failing_list_instances)

    result = CliRunner().invoke(main, ["--json", "instance", "list"])

    assert result.exit_code == 1
    assert "token expired" in result.output
    assert "Traceback" not in result.output


def test_list_rejects_page_size_above_server_limit(home: Path, monkeypatch) -> None:
    """Click rejects a page size the API cannot serve before any call is made."""
    _seed_token()
    monkeypatch.setattr(
        instance_commands.instance_handler,
        "list_instances",
        lambda *args, **kwargs: pytest.fail("the handler must not run for an invalid page size"),
    )

    result = CliRunner().invoke(main, ["instance", "list", "--page-size", "101"])

    assert result.exit_code == 2
    assert "101" in result.output
