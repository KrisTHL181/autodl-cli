"""Tests for ``autodl instance`` commands through the real Click entry point."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from click.testing import CliRunner
from rich.console import Console

from autodl_cli import config as config_module
from autodl_cli import output as output_module
from autodl_cli.commands import instance as instance_commands
from autodl_cli.errors import AuthError
from autodl_cli.main import main

TOKEN = "fake-token"

#: Frozen clock for the auto-release countdown (matches the web console capture).
NOW = datetime(2026, 11, 1, 0, 32, 7, tzinfo=timezone(timedelta(hours=8)))

INSTANCES = [
    {
        "uuid": "cs1a2b3c4d5e6f7g8h",
        "name": "",
        "machine_alias": "431机",
        "status": "running",
        "status_at": "2026-10-30T06:10:07+08:00",
        "sub_status": "",
        "start_mode": "gpu",
        "oom_killed": False,
        "gpu_all_num": 8,
        "gpu_idle_num": 7,
        "snapshot_gpu_alias_name": "RTX 3090",
        "req_gpu_amount": 1,
        "region_name": "内蒙B区",
        "root_fs_used_rate": 0.196,
        "usage_info": {"data_disk_used_size": 94, "data_disk_total_size": 100},
        "disk_health_status": "normal",
        "charge_type": "payg",
        "payg_price": 1480,
        "daily_price": 0,
        "rent_deadline": "2027-07-01T00:00:00+08:00",
        "timed_shutdown_at": {"Time": "2026-11-30T00:00:00+08:00", "Valid": True},
        "expired_at": {"Time": "0001-01-01T00:00:00Z", "Valid": False},
        "ssh_command": "ssh -p 39684 root@connect.nmb2.seetacloud.com",
    },
    {
        "uuid": "cs9z8y7x6w5v4u3t2s",
        "name": "trainer",
        "machine_alias": "496机",
        "status": "shutdown",
        "status_at": "2026-10-31T12:00:00+08:00",
        "sub_status": "",
        "start_mode": "gpu",
        "oom_killed": False,
        "gpu_all_num": 8,
        "gpu_idle_num": 0,
        "snapshot_gpu_alias_name": "RTX 3080 Ti",
        "req_gpu_amount": 3,
        "region_name": "西北B区",
        "root_fs_used_rate": 0.0324,
        "usage_info": {"data_disk_used_size": 50, "data_disk_total_size": 100},
        "disk_health_status": "normal",
        "charge_type": "payg",
        "payg_price": 3250,
        "daily_price": 0,
        "rent_deadline": "2027-05-01T00:00:00+08:00",
        "timed_shutdown_at": {"Time": "0001-01-01T00:00:00Z", "Valid": False},
        "expired_at": {"Time": "0001-01-01T00:00:00Z", "Valid": False},
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
    """On a wide terminal every column and the full SSH command fit."""
    _seed_token()
    monkeypatch.setattr(
        instance_commands.instance_handler,
        "list_instances",
        lambda client, **kwargs: INSTANCES,
    )
    monkeypatch.setattr(output_module, "console", Console(width=160))
    monkeypatch.setattr(output_module, "_current_time", lambda: NOW)

    result = CliRunner().invoke(main, ["instance", "list"])

    assert result.exit_code == 0, result.output
    assert "Instances (2)" in result.output
    for header in ("Instance", "Status", "Spec", "Disk", "Health", "Billing", "Release", "SSH"):
        assert header in result.output
    assert "内蒙B区 / 431机" in result.output
    assert "西北B区 / 496机" in result.output
    assert "cs1a2b3c4d5e6f7g8h" in result.output
    assert "trainer" in result.output
    assert "running" in result.output
    assert "RTX 3090 ×1" in result.output
    assert "RTX 3080 Ti ×3" in result.output
    assert "Cards 7/8" in result.output
    assert "Cards 0/8" in result.output
    assert "Sys 19.60%" in result.output
    assert "Data 94.00%" in result.output
    assert "Sys 3.24%" in result.output
    assert "Data 50.00%" in result.output
    assert "normal" in result.output
    assert "¥1.480/h" in result.output
    assert "2027-07-01" in result.output
    assert "Stop 2026-11-30" in result.output
    assert "in 14d 11h 27m" in result.output
    assert "ssh -p 39684 root@connect.nmb2.seetacloud.com" in result.output
    assert TOKEN not in result.output


def test_list_release_countdown_matches_web_console(home: Path, monkeypatch) -> None:
    """A shut-down instance counts down 15 days from its last status change."""
    _seed_token()
    instance = dict(INSTANCES[0], status="shutdown", status_at="2026-10-30T06:10:07+08:00")
    monkeypatch.setattr(instance_commands.instance_handler, "list_instances", lambda client, **kwargs: [instance])
    monkeypatch.setattr(output_module, "console", Console(width=160))
    monkeypatch.setattr(output_module, "_current_time", lambda: NOW)

    result = CliRunner().invoke(main, ["instance", "list"])

    assert result.exit_code == 0, result.output
    assert "in 13d 05h 38m" in result.output


def test_list_release_shows_due_after_retention(home: Path, monkeypatch) -> None:
    """Once the retention window has passed the countdown reads ``due``."""
    _seed_token()
    instance = dict(INSTANCES[0], status="shutdown", status_at="2026-10-30T06:10:07+08:00")
    later = datetime(2026, 11, 15, 0, 0, tzinfo=timezone(timedelta(hours=8)))
    monkeypatch.setattr(instance_commands.instance_handler, "list_instances", lambda client, **kwargs: [instance])
    monkeypatch.setattr(output_module, "console", Console(width=160))
    monkeypatch.setattr(output_module, "_current_time", lambda: later)

    result = CliRunner().invoke(main, ["instance", "list"])

    assert result.exit_code == 0, result.output
    assert "due" in result.output


def test_list_human_output_omits_ssh_when_it_does_not_fit(home: Path, monkeypatch) -> None:
    """At 110 columns the short columns fit but SSH is dropped."""
    _seed_token()
    monkeypatch.setattr(
        instance_commands.instance_handler,
        "list_instances",
        lambda client, **kwargs: INSTANCES,
    )
    monkeypatch.setattr(output_module, "console", Console(width=110))
    monkeypatch.setattr(output_module, "_current_time", lambda: NOW)

    result = CliRunner().invoke(main, ["instance", "list"])

    assert result.exit_code == 0, result.output
    assert "内蒙B区 / 431机" in result.output
    assert "cs1a2b3c4d5e6f7g8h" in result.output
    assert "in 14d 11h 27m" in result.output
    assert "SSH" not in result.output
    assert "root@connect" not in result.output


def test_list_human_output_stacks_fields_on_narrow_terminal(home: Path, monkeypatch) -> None:
    """At 80 columns the fields stack under the ID instead of being truncated."""
    _seed_token()
    monkeypatch.setattr(
        instance_commands.instance_handler,
        "list_instances",
        lambda client, **kwargs: INSTANCES,
    )
    monkeypatch.setattr(output_module, "console", Console(width=80))
    monkeypatch.setattr(output_module, "_current_time", lambda: NOW)

    result = CliRunner().invoke(main, ["instance", "list"])

    assert result.exit_code == 0, result.output
    assert "Instances (2)" in result.output
    assert "cs1a2b3c4d5e6f7g8h" in result.output
    assert "内蒙B区 / 431机" in result.output
    assert "Status running · Spec RTX 3090 ×1 · Cards 7/8" in result.output
    assert "Disk Sys 19.60% / Data 94.00% · Health normal" in result.output
    assert "Billing payg ¥1.480/h · Release 2027-07-01 · Stop" in result.output
    assert "2026-11-30" in result.output
    assert "Billing payg ¥3.250/h · Release in 14d 11h 27m" in result.output
    assert "SSH ssh -p 39684 root@connect.nmb2.seetacloud.com" in result.output


def test_list_stacked_output_reports_cpu_mode(home: Path, monkeypatch) -> None:
    """``start_mode: non_gpu`` wins over the snapshot GPU alias."""
    _seed_token()
    instance = dict(INSTANCES[0], start_mode="non_gpu", gpu_idle_num=0)
    monkeypatch.setattr(instance_commands.instance_handler, "list_instances", lambda client, **kwargs: [instance])
    monkeypatch.setattr(output_module, "console", Console(width=80))
    monkeypatch.setattr(output_module, "_current_time", lambda: NOW)

    result = CliRunner().invoke(main, ["instance", "list"])

    assert result.exit_code == 0, result.output
    assert "Spec CPU · Cards 0/8" in result.output
    assert "RTX 3090" not in result.output


def test_list_marks_oom_killed_instances(home: Path, monkeypatch) -> None:
    """A previously OOM-killed instance is flagged in the status column."""
    _seed_token()
    instance = dict(INSTANCES[0], oom_killed=True)
    monkeypatch.setattr(instance_commands.instance_handler, "list_instances", lambda client, **kwargs: [instance])
    monkeypatch.setattr(output_module, "console", Console(width=80))
    monkeypatch.setattr(output_module, "_current_time", lambda: NOW)

    result = CliRunner().invoke(main, ["instance", "list"])

    assert result.exit_code == 0, result.output
    assert "Status running (OOM)" in result.output


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
            "--query",
            "trainer",
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
        "query": "trainer",
    }


def test_list_query_short_option_is_forwarded(home: Path, monkeypatch) -> None:
    """``-q`` is an alias for ``--query`` and reaches the handler."""
    _seed_token()
    captured: dict[str, object] = {}

    def fake_list_instances(client, **kwargs):
        captured.update(kwargs)
        return INSTANCES

    monkeypatch.setattr(instance_commands.instance_handler, "list_instances", fake_list_instances)

    result = CliRunner().invoke(main, ["--json", "instance", "list", "-q", "4090"])

    assert result.exit_code == 0, result.output
    assert captured["query"] == "4090"


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
