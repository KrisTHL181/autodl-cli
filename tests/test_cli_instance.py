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
        "payg_price": 1.48,
        "daily_price": 0.0,
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
        "payg_price": 3.25,
        "daily_price": 0.0,
        "rent_deadline": "2027-05-01T00:00:00+08:00",
        "timed_shutdown_at": {"Time": "0001-01-01T00:00:00Z", "Valid": False},
        "expired_at": {"Time": "0001-01-01T00:00:00Z", "Valid": False},
        "ssh_command": "ssh -p 35677 root@connect.westd.seetacloud.com",
    },
]


INSTANCE_UUID = "9b384da211-e57974ef"
IMAGE_UUID = "base-image-ec1e9vdbd3"
RENAME_NAME = "AutoDL-CLI-Rename-Test"

DETAIL = {
    "image_type": "",
    "image": {
        "image_type": "public",
        "image_name": "base-image-ee43618uo7",
        "base_image_uuid": "base-image-ee43618uo7",
        "framework_name": "PyTorch",
        "framework_version": "2.12.1",
        "python_version": "3.12(ubuntu22.04)",
        "cuda_version": "13.0",
        "cpu_arch": "x86",
    },
    "payg_price": 1.48,
    "origin_pay_price": 1.56,
    "snapshot_gpu_alias_name": "RTX 3090",
    "user_define_gpu_name": "",
    "chip_corp": "nvidia",
    "cpu_arch": "x86",
    "machine_info_snapshot": {
        "cpu_num": 112,
        "cpu_name": "Intel(R) Xeon(R) Gold 6330 CPU @ 2.00GHz",
        "disk_size": 7679364128768,
        "disk_type": "SSD",
        "memory": 540651888640,
        "mem_used": 64424509440,
        "cpu_used": 14,
        "max_instance_disk_size": 53687091200,
        "region_sign": "nm-B2",
        "region_name": "内蒙B区",
        "data_center": "neimengDC3",
        "os_name": "ubuntu18.04",
        "docker_version": "27.2.0-umd18",
        "kernel_version": "5.15.0-94-generic",
        "nvidia_docker": True,
        "restart_time": "2026-07-02T17:06:57+08:00",
        "gpu_type": {"name": "RTX 3090", "memory": 25769803776},
    },
    "max_writable_size_in_byte": 32212254720,
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
    """Store a token so the instance commands can run."""
    config_module.save_config({"token": TOKEN})


def test_list_json_returns_instance_data(home: Path, monkeypatch) -> None:
    """``--json`` emits the handler's yuan-priced result unchanged."""
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


def test_detail_json_returns_snapshot(home: Path, monkeypatch) -> None:
    """``--json`` emits the handler's yuan-priced snapshot unchanged."""
    _seed_token()
    monkeypatch.setattr(
        instance_commands.instance_handler,
        "get_instance",
        lambda client, instance_id: DETAIL,
    )

    result = CliRunner().invoke(main, ["--json", "instance", "detail", INSTANCE_UUID])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == DETAIL
    assert TOKEN not in result.output


def test_detail_human_output_shows_snapshot(home: Path, monkeypatch) -> None:
    """The human output groups the snapshot into readable sections."""
    _seed_token()
    monkeypatch.setattr(
        instance_commands.instance_handler,
        "get_instance",
        lambda client, instance_id: DETAIL,
    )
    monkeypatch.setattr(output_module, "console", Console(width=160))

    result = CliRunner().invoke(main, ["instance", "detail", INSTANCE_UUID])

    assert result.exit_code == 0, result.output
    assert f"Instance {INSTANCE_UUID}" in result.output
    for header in ("Instance", "Image", "Machine", "Field", "Value"):
        assert header in result.output
    assert "RTX 3090 (nvidia)" in result.output
    assert "24G" in result.output
    assert "¥1.480/h (list ¥1.560/h)" in result.output
    assert "PyTorch 2.12.1" in result.output
    assert "3.12(ubuntu22.04)" in result.output
    assert "内蒙B区 (nm-B2)" in result.output
    assert "14 used / 112 total" in result.output
    assert "60G / " in result.output
    assert "7.0T SSD" in result.output
    assert "50G" in result.output
    assert "30G" in result.output
    assert "ubuntu18.04" in result.output
    assert "2026-07-02 17:06:57" in result.output
    assert TOKEN not in result.output


def test_detail_forwards_instance_uuid(home: Path, monkeypatch) -> None:
    """The positional UUID reaches the handler unchanged."""
    _seed_token()
    captured: dict[str, object] = {}

    def fake_get_instance(client, instance_id):
        captured["instance_id"] = instance_id
        return DETAIL

    monkeypatch.setattr(instance_commands.instance_handler, "get_instance", fake_get_instance)

    result = CliRunner().invoke(main, ["--json", "instance", "detail", INSTANCE_UUID])

    assert result.exit_code == 0, result.output
    assert captured["instance_id"] == INSTANCE_UUID


def test_detail_requires_token(home: Path, monkeypatch) -> None:
    """A missing token fails cleanly with the paste hint."""
    monkeypatch.setattr(
        instance_commands.instance_handler,
        "get_instance",
        lambda *args, **kwargs: pytest.fail("the handler must not run without a token"),
    )

    result = CliRunner().invoke(main, ["--json", "instance", "detail", INSTANCE_UUID])

    assert result.exit_code == 1
    assert "autodl auth paste" in result.output
    assert "Traceback" not in result.output


def test_detail_api_failure_is_a_clean_click_exception(home: Path, monkeypatch) -> None:
    """An API failure exits 1 without a traceback."""
    _seed_token()

    def failing_get_instance(client, instance_id):
        raise AuthError("token expired")

    monkeypatch.setattr(instance_commands.instance_handler, "get_instance", failing_get_instance)

    result = CliRunner().invoke(main, ["--json", "instance", "detail", INSTANCE_UUID])

    assert result.exit_code == 1
    assert "token expired" in result.output
    assert "Traceback" not in result.output


def test_save_image_forwards_arguments_and_returns_json(home: Path, monkeypatch) -> None:
    """The positionals and ``--try-again`` reach the handler; JSON is passed through."""
    _seed_token()
    captured: dict[str, object] = {}
    record = {
        "instance_uuid": INSTANCE_UUID,
        "image_name": "save-image-test1",
        "try_again": True,
        "saved": True,
    }

    def fake_save_image(client, instance_id, image_name, *, try_again):
        captured.update(instance_id=instance_id, image_name=image_name, try_again=try_again)
        return record

    monkeypatch.setattr(instance_commands.instance_handler, "save_image", fake_save_image)

    result = CliRunner().invoke(
        main, ["--json", "instance", "save-image", INSTANCE_UUID, "save-image-test1", "--try-again"]
    )

    assert result.exit_code == 0, result.output
    assert captured == {"instance_id": INSTANCE_UUID, "image_name": "save-image-test1", "try_again": True}
    assert json.loads(result.output) == record
    assert TOKEN not in result.output


def test_save_image_human_output_reports_success(home: Path, monkeypatch) -> None:
    """The human view confirms which instance and image were requested."""
    _seed_token()

    def fake_save_image(client, instance_id, image_name, *, try_again):
        return {
            "instance_uuid": instance_id,
            "image_name": image_name,
            "try_again": try_again,
            "saved": True,
        }

    monkeypatch.setattr(instance_commands.instance_handler, "save_image", fake_save_image)

    result = CliRunner().invoke(main, ["instance", "save-image", INSTANCE_UUID, "save-image-test1"])

    assert result.exit_code == 0, result.output
    assert f"Save requested for instance {INSTANCE_UUID} as image 'save-image-test1'." in result.output
    assert TOKEN not in result.output


def test_save_image_blank_argument_is_a_clean_error(home: Path, monkeypatch) -> None:
    """A blank name rejected by the handler exits 1 without a traceback."""
    _seed_token()

    def failing_save_image(client, instance_id, image_name, *, try_again):
        raise ValueError("image_name must not be empty")

    monkeypatch.setattr(instance_commands.instance_handler, "save_image", failing_save_image)

    result = CliRunner().invoke(main, ["instance", "save-image", INSTANCE_UUID, " "])

    assert result.exit_code == 1
    assert "image_name must not be empty" in result.output
    assert "Traceback" not in result.output


def test_save_image_requires_token(home: Path, monkeypatch) -> None:
    """A missing token fails cleanly with the paste hint."""
    monkeypatch.setattr(
        instance_commands.instance_handler,
        "save_image",
        lambda *args, **kwargs: pytest.fail("the handler must not run without a token"),
    )

    result = CliRunner().invoke(main, ["instance", "save-image", INSTANCE_UUID, "test"])

    assert result.exit_code == 1
    assert "autodl auth paste" in result.output
    assert "Traceback" not in result.output


def test_save_image_api_failure_is_a_clean_click_exception(home: Path, monkeypatch) -> None:
    """An API failure exits 1 without a traceback."""
    _seed_token()

    def failing_save_image(client, instance_id, image_name, *, try_again):
        raise AuthError("token expired")

    monkeypatch.setattr(instance_commands.instance_handler, "save_image", failing_save_image)

    result = CliRunner().invoke(main, ["instance", "save-image", INSTANCE_UUID, "test"])

    assert result.exit_code == 1
    assert "token expired" in result.output
    assert "Traceback" not in result.output


def test_power_off_forwards_instance_and_returns_json(home: Path, monkeypatch) -> None:
    """The positional UUID reaches the handler; JSON is passed through."""
    _seed_token()
    captured: dict[str, object] = {}
    record = {"instance_uuid": INSTANCE_UUID, "powered_off": True}

    def fake_power_off(client, instance_id):
        captured["instance_id"] = instance_id
        return record

    monkeypatch.setattr(instance_commands.instance_handler, "power_off", fake_power_off)

    result = CliRunner().invoke(main, ["--json", "instance", "power-off", INSTANCE_UUID])

    assert result.exit_code == 0, result.output
    assert captured == {"instance_id": INSTANCE_UUID}
    assert json.loads(result.output) == record
    assert TOKEN not in result.output


def test_power_off_human_output_reports_success(home: Path, monkeypatch) -> None:
    """The human view confirms which instance was asked to power off."""
    _seed_token()
    monkeypatch.setattr(
        instance_commands.instance_handler,
        "power_off",
        lambda client, instance_id: {"instance_uuid": instance_id, "powered_off": True},
    )

    result = CliRunner().invoke(main, ["instance", "power-off", INSTANCE_UUID])

    assert result.exit_code == 0, result.output
    assert f"Power-off requested for instance {INSTANCE_UUID}." in result.output
    assert TOKEN not in result.output


def test_power_off_blank_argument_is_a_clean_error(home: Path, monkeypatch) -> None:
    """A blank UUID rejected by the handler exits 1 without a traceback."""
    _seed_token()

    def failing_power_off(client, instance_id):
        raise ValueError("instance_id must not be empty")

    monkeypatch.setattr(instance_commands.instance_handler, "power_off", failing_power_off)

    result = CliRunner().invoke(main, ["instance", "power-off", " "])

    assert result.exit_code == 1
    assert "instance_id must not be empty" in result.output
    assert "Traceback" not in result.output


def test_power_off_requires_token(home: Path, monkeypatch) -> None:
    """A missing token fails cleanly with the paste hint."""
    monkeypatch.setattr(
        instance_commands.instance_handler,
        "power_off",
        lambda *args, **kwargs: pytest.fail("the handler must not run without a token"),
    )

    result = CliRunner().invoke(main, ["instance", "power-off", INSTANCE_UUID])

    assert result.exit_code == 1
    assert "autodl auth paste" in result.output
    assert "Traceback" not in result.output


def test_power_off_api_failure_is_a_clean_click_exception(home: Path, monkeypatch) -> None:
    """An API failure exits 1 without a traceback."""
    _seed_token()

    def failing_power_off(client, instance_id):
        raise AuthError("token expired")

    monkeypatch.setattr(instance_commands.instance_handler, "power_off", failing_power_off)

    result = CliRunner().invoke(main, ["instance", "power-off", INSTANCE_UUID])

    assert result.exit_code == 1
    assert "token expired" in result.output
    assert "Traceback" not in result.output


def test_reset_forwards_instance_and_returns_json(home: Path, monkeypatch) -> None:
    """``--yes`` skips the prompt, forwards the UUID, and emits the result."""
    _seed_token()
    captured: dict[str, object] = {}
    record = {"instance_uuid": INSTANCE_UUID, "reset": True}

    def fake_reset_instance(client, instance_id):
        captured["instance_id"] = instance_id
        return record

    monkeypatch.setattr(instance_commands.instance_handler, "reset_instance", fake_reset_instance)

    result = CliRunner().invoke(main, ["--json", "instance", "reset", INSTANCE_UUID, "--yes"])

    assert result.exit_code == 0, result.output
    assert captured == {"instance_id": INSTANCE_UUID}
    assert json.loads(result.output) == record
    assert TOKEN not in result.output


def test_reset_human_output_reports_success(home: Path, monkeypatch) -> None:
    """The human view confirms which instance was asked to reset."""
    _seed_token()
    monkeypatch.setattr(
        instance_commands.instance_handler,
        "reset_instance",
        lambda client, instance_id: {"instance_uuid": instance_id, "reset": True},
    )

    result = CliRunner().invoke(main, ["instance", "reset", INSTANCE_UUID, "--yes"])

    assert result.exit_code == 0, result.output
    assert f"Reset requested for instance {INSTANCE_UUID}." in result.output
    assert TOKEN not in result.output


def test_reset_prompts_and_accepts(home: Path, monkeypatch) -> None:
    """Without ``--yes`` the command asks, then resets when confirmed."""
    _seed_token()
    called: list[str] = []

    def fake_reset_instance(client, instance_id):
        called.append(instance_id)
        return {"instance_uuid": instance_id, "reset": True}

    monkeypatch.setattr(instance_commands.instance_handler, "reset_instance", fake_reset_instance)

    result = CliRunner().invoke(main, ["instance", "reset", INSTANCE_UUID], input="y\n")

    assert result.exit_code == 0, result.output
    assert f"Reset instance {INSTANCE_UUID}?" in result.output
    assert called == [INSTANCE_UUID]


def test_reset_prompt_can_abort(home: Path, monkeypatch) -> None:
    """Declining the prompt aborts without calling the handler."""
    _seed_token()
    monkeypatch.setattr(
        instance_commands.instance_handler,
        "reset_instance",
        lambda *args, **kwargs: pytest.fail("the handler must not run when the prompt is declined"),
    )

    result = CliRunner().invoke(main, ["instance", "reset", INSTANCE_UUID], input="n\n")

    assert result.exit_code == 1
    assert "Aborted" in result.output
    assert "Traceback" not in result.output


def test_reset_blank_argument_is_a_clean_error(home: Path, monkeypatch) -> None:
    """A blank UUID rejected by the handler exits 1 without a traceback."""
    _seed_token()

    def failing_reset_instance(client, instance_id):
        raise ValueError("instance_id must not be empty")

    monkeypatch.setattr(instance_commands.instance_handler, "reset_instance", failing_reset_instance)

    result = CliRunner().invoke(main, ["instance", "reset", " ", "--yes"])

    assert result.exit_code == 1
    assert "instance_id must not be empty" in result.output
    assert "Traceback" not in result.output


def test_reset_requires_token(home: Path, monkeypatch) -> None:
    """A missing token fails cleanly with the paste hint."""
    monkeypatch.setattr(
        instance_commands.instance_handler,
        "reset_instance",
        lambda *args, **kwargs: pytest.fail("the handler must not run without a token"),
    )

    result = CliRunner().invoke(main, ["instance", "reset", INSTANCE_UUID, "--yes"])

    assert result.exit_code == 1
    assert "autodl auth paste" in result.output
    assert "Traceback" not in result.output


def test_reset_api_failure_is_a_clean_click_exception(home: Path, monkeypatch) -> None:
    """An API failure exits 1 without a traceback."""
    _seed_token()

    def failing_reset_instance(client, instance_id):
        raise AuthError("token expired")

    monkeypatch.setattr(instance_commands.instance_handler, "reset_instance", failing_reset_instance)

    result = CliRunner().invoke(main, ["instance", "reset", INSTANCE_UUID, "--yes"])

    assert result.exit_code == 1
    assert "token expired" in result.output
    assert "Traceback" not in result.output


def test_change_image_forwards_arguments_and_returns_json(home: Path, monkeypatch) -> None:
    """``--yes`` skips the prompt, forwards both UUIDs, and emits the result."""
    _seed_token()
    captured: dict[str, object] = {}
    record = {
        "instance_uuid": INSTANCE_UUID,
        "base_image_uuid": IMAGE_UUID,
        "image_changed": True,
    }

    def fake_change_image(client, instance_id, base_image_uuid):
        captured["instance_id"] = instance_id
        captured["base_image_uuid"] = base_image_uuid
        return record

    monkeypatch.setattr(instance_commands.instance_handler, "change_image", fake_change_image)

    result = CliRunner().invoke(
        main,
        ["--json", "instance", "change-image", INSTANCE_UUID, IMAGE_UUID, "--yes"],
    )

    assert result.exit_code == 0, result.output
    assert captured == {"instance_id": INSTANCE_UUID, "base_image_uuid": IMAGE_UUID}
    assert json.loads(result.output) == record
    assert TOKEN not in result.output


def test_change_image_human_output_reports_success(home: Path, monkeypatch) -> None:
    """The human view confirms the instance and the new image."""
    _seed_token()
    monkeypatch.setattr(
        instance_commands.instance_handler,
        "change_image",
        lambda client, instance_id, base_image_uuid: {
            "instance_uuid": instance_id,
            "base_image_uuid": base_image_uuid,
            "image_changed": True,
        },
    )

    result = CliRunner().invoke(main, ["instance", "change-image", INSTANCE_UUID, IMAGE_UUID, "--yes"])

    assert result.exit_code == 0, result.output
    assert f"Image change requested for {INSTANCE_UUID}: {IMAGE_UUID}." in result.output
    assert TOKEN not in result.output


def test_change_image_prompts_and_accepts(home: Path, monkeypatch) -> None:
    """Without ``--yes`` the command asks, then changes the image when confirmed."""
    _seed_token()
    called: list[tuple[str, str]] = []

    def fake_change_image(client, instance_id, base_image_uuid):
        called.append((instance_id, base_image_uuid))
        return {
            "instance_uuid": instance_id,
            "base_image_uuid": base_image_uuid,
            "image_changed": True,
        }

    monkeypatch.setattr(instance_commands.instance_handler, "change_image", fake_change_image)

    result = CliRunner().invoke(main, ["instance", "change-image", INSTANCE_UUID, IMAGE_UUID], input="y\n")

    assert result.exit_code == 0, result.output
    assert f"Change the image of instance {INSTANCE_UUID} to {IMAGE_UUID}?" in result.output
    assert called == [(INSTANCE_UUID, IMAGE_UUID)]


def test_change_image_prompt_can_abort(home: Path, monkeypatch) -> None:
    """Declining the prompt aborts without calling the handler."""
    _seed_token()
    monkeypatch.setattr(
        instance_commands.instance_handler,
        "change_image",
        lambda *args, **kwargs: pytest.fail("the handler must not run when the prompt is declined"),
    )

    result = CliRunner().invoke(main, ["instance", "change-image", INSTANCE_UUID, IMAGE_UUID], input="n\n")

    assert result.exit_code == 1
    assert "Aborted" in result.output
    assert "Traceback" not in result.output


def test_change_image_blank_argument_is_a_clean_error(home: Path, monkeypatch) -> None:
    """A blank base-image UUID rejected by the handler exits 1 without a traceback."""
    _seed_token()

    def failing_change_image(client, instance_id, base_image_uuid):
        raise ValueError("base_image_uuid must not be empty")

    monkeypatch.setattr(instance_commands.instance_handler, "change_image", failing_change_image)

    result = CliRunner().invoke(main, ["instance", "change-image", INSTANCE_UUID, " ", "--yes"])

    assert result.exit_code == 1
    assert "base_image_uuid must not be empty" in result.output
    assert "Traceback" not in result.output


def test_change_image_requires_token(home: Path, monkeypatch) -> None:
    """A missing token fails cleanly with the paste hint."""
    monkeypatch.setattr(
        instance_commands.instance_handler,
        "change_image",
        lambda *args, **kwargs: pytest.fail("the handler must not run without a token"),
    )

    result = CliRunner().invoke(main, ["instance", "change-image", INSTANCE_UUID, IMAGE_UUID, "--yes"])

    assert result.exit_code == 1
    assert "autodl auth paste" in result.output
    assert "Traceback" not in result.output


def test_change_image_api_failure_is_a_clean_click_exception(home: Path, monkeypatch) -> None:
    """An API failure exits 1 without a traceback."""
    _seed_token()

    def failing_change_image(client, instance_id, base_image_uuid):
        raise AuthError("token expired")

    monkeypatch.setattr(instance_commands.instance_handler, "change_image", failing_change_image)

    result = CliRunner().invoke(main, ["instance", "change-image", INSTANCE_UUID, IMAGE_UUID, "--yes"])

    assert result.exit_code == 1
    assert "token expired" in result.output
    assert "Traceback" not in result.output


def test_rename_forwards_arguments_and_returns_json(home: Path, monkeypatch) -> None:
    """The positionals reach the handler and JSON is passed through, without a prompt."""
    _seed_token()
    captured: dict[str, object] = {}
    record = {
        "instance_uuid": INSTANCE_UUID,
        "instance_name": RENAME_NAME,
        "renamed": True,
    }

    def fake_rename_instance(client, instance_id, instance_name):
        captured["instance_id"] = instance_id
        captured["instance_name"] = instance_name
        return record

    monkeypatch.setattr(instance_commands.instance_handler, "rename_instance", fake_rename_instance)

    result = CliRunner().invoke(main, ["--json", "instance", "rename", INSTANCE_UUID, RENAME_NAME])

    assert result.exit_code == 0, result.output
    assert captured == {"instance_id": INSTANCE_UUID, "instance_name": RENAME_NAME}
    assert json.loads(result.output) == record
    assert TOKEN not in result.output


def test_rename_human_output_reports_success(home: Path, monkeypatch) -> None:
    """The human view confirms the instance's new name."""
    _seed_token()
    monkeypatch.setattr(
        instance_commands.instance_handler,
        "rename_instance",
        lambda client, instance_id, instance_name: {
            "instance_uuid": instance_id,
            "instance_name": instance_name,
            "renamed": True,
        },
    )

    result = CliRunner().invoke(main, ["instance", "rename", INSTANCE_UUID, RENAME_NAME])

    assert result.exit_code == 0, result.output
    assert f"Renamed instance {INSTANCE_UUID} to {RENAME_NAME!r}." in result.output
    assert TOKEN not in result.output


def test_rename_blank_argument_is_a_clean_error(home: Path, monkeypatch) -> None:
    """A blank name rejected by the handler exits 1 without a traceback."""
    _seed_token()

    def failing_rename_instance(client, instance_id, instance_name):
        raise ValueError("instance_name must not be empty")

    monkeypatch.setattr(instance_commands.instance_handler, "rename_instance", failing_rename_instance)

    result = CliRunner().invoke(main, ["instance", "rename", INSTANCE_UUID, " "])

    assert result.exit_code == 1
    assert "instance_name must not be empty" in result.output
    assert "Traceback" not in result.output


def test_rename_requires_token(home: Path, monkeypatch) -> None:
    """A missing token fails cleanly with the paste hint."""
    monkeypatch.setattr(
        instance_commands.instance_handler,
        "rename_instance",
        lambda *args, **kwargs: pytest.fail("the handler must not run without a token"),
    )

    result = CliRunner().invoke(main, ["instance", "rename", INSTANCE_UUID, RENAME_NAME])

    assert result.exit_code == 1
    assert "autodl auth paste" in result.output
    assert "Traceback" not in result.output


def test_rename_api_failure_is_a_clean_click_exception(home: Path, monkeypatch) -> None:
    """An API failure exits 1 without a traceback."""
    _seed_token()

    def failing_rename_instance(client, instance_id, instance_name):
        raise AuthError("token expired")

    monkeypatch.setattr(instance_commands.instance_handler, "rename_instance", failing_rename_instance)

    result = CliRunner().invoke(main, ["instance", "rename", INSTANCE_UUID, RENAME_NAME])

    assert result.exit_code == 1
    assert "token expired" in result.output
    assert "Traceback" not in result.output


def test_power_on_forwards_instance_and_returns_json(home: Path, monkeypatch) -> None:
    """The positional UUID reaches the handler; JSON is passed through."""
    _seed_token()
    captured: dict[str, object] = {}
    record = {"instance_uuid": INSTANCE_UUID, "powered_on": True, "non_gpu": False}

    def fake_power_on(client, instance_id, *, non_gpu=False):
        captured["instance_id"] = instance_id
        captured["non_gpu"] = non_gpu
        return record

    monkeypatch.setattr(instance_commands.instance_handler, "power_on", fake_power_on)

    result = CliRunner().invoke(main, ["--json", "instance", "power-on", INSTANCE_UUID])

    assert result.exit_code == 0, result.output
    assert captured == {"instance_id": INSTANCE_UUID, "non_gpu": False}
    assert json.loads(result.output) == record
    assert TOKEN not in result.output


def test_power_on_non_gpu_flag_reaches_the_handler(home: Path, monkeypatch) -> None:
    """``--non-gpu`` is forwarded and the human view names the mode."""
    _seed_token()
    captured: dict[str, object] = {}

    def fake_power_on(client, instance_id, *, non_gpu=False):
        captured["instance_id"] = instance_id
        captured["non_gpu"] = non_gpu
        return {"instance_uuid": instance_id, "powered_on": True, "non_gpu": non_gpu}

    monkeypatch.setattr(instance_commands.instance_handler, "power_on", fake_power_on)

    result = CliRunner().invoke(main, ["instance", "power-on", INSTANCE_UUID, "--non-gpu"])

    assert result.exit_code == 0, result.output
    assert captured == {"instance_id": INSTANCE_UUID, "non_gpu": True}
    assert f"Power-on requested for instance {INSTANCE_UUID} in CPU-only mode." in result.output
    assert TOKEN not in result.output


def test_power_on_human_output_reports_success(home: Path, monkeypatch) -> None:
    """The human view confirms which instance was asked to power on."""
    _seed_token()
    monkeypatch.setattr(
        instance_commands.instance_handler,
        "power_on",
        lambda client, instance_id, *, non_gpu=False: {
            "instance_uuid": instance_id,
            "powered_on": True,
            "non_gpu": non_gpu,
        },
    )

    result = CliRunner().invoke(main, ["instance", "power-on", INSTANCE_UUID])

    assert result.exit_code == 0, result.output
    assert f"Power-on requested for instance {INSTANCE_UUID}." in result.output
    assert TOKEN not in result.output


def test_power_on_blank_argument_is_a_clean_error(home: Path, monkeypatch) -> None:
    """A blank UUID rejected by the handler exits 1 without a traceback."""
    _seed_token()

    def failing_power_on(client, instance_id, *, non_gpu=False):
        raise ValueError("instance_id must not be empty")

    monkeypatch.setattr(instance_commands.instance_handler, "power_on", failing_power_on)

    result = CliRunner().invoke(main, ["instance", "power-on", " "])

    assert result.exit_code == 1
    assert "instance_id must not be empty" in result.output
    assert "Traceback" not in result.output


def test_power_on_requires_token(home: Path, monkeypatch) -> None:
    """A missing token fails cleanly with the paste hint."""
    monkeypatch.setattr(
        instance_commands.instance_handler,
        "power_on",
        lambda *args, **kwargs: pytest.fail("the handler must not run without a token"),
    )

    result = CliRunner().invoke(main, ["instance", "power-on", INSTANCE_UUID])

    assert result.exit_code == 1
    assert "autodl auth paste" in result.output
    assert "Traceback" not in result.output


def test_power_on_api_failure_is_a_clean_click_exception(home: Path, monkeypatch) -> None:
    """An API failure exits 1 without a traceback."""
    _seed_token()

    def failing_power_on(client, instance_id, *, non_gpu=False):
        raise AuthError("token expired")

    monkeypatch.setattr(instance_commands.instance_handler, "power_on", failing_power_on)

    result = CliRunner().invoke(main, ["instance", "power-on", INSTANCE_UUID])

    assert result.exit_code == 1
    assert "token expired" in result.output
    assert "Traceback" not in result.output


def test_release_forwards_instance_and_returns_json(home: Path, monkeypatch) -> None:
    """``--yes`` skips the prompt, forwards the UUID, and emits the result."""
    _seed_token()
    captured: dict[str, object] = {}
    record = {"instance_uuid": INSTANCE_UUID, "released": True}

    def fake_release_instance(client, instance_id):
        captured["instance_id"] = instance_id
        return record

    monkeypatch.setattr(instance_commands.instance_handler, "release_instance", fake_release_instance)

    result = CliRunner().invoke(main, ["--json", "instance", "release", INSTANCE_UUID, "--yes"])

    assert result.exit_code == 0, result.output
    assert captured == {"instance_id": INSTANCE_UUID}
    assert json.loads(result.output) == record
    assert TOKEN not in result.output


def test_release_human_output_reports_success(home: Path, monkeypatch) -> None:
    """The human view confirms which instance was asked to release."""
    _seed_token()
    monkeypatch.setattr(
        instance_commands.instance_handler,
        "release_instance",
        lambda client, instance_id: {"instance_uuid": instance_id, "released": True},
    )

    result = CliRunner().invoke(main, ["instance", "release", INSTANCE_UUID, "--yes"])

    assert result.exit_code == 0, result.output
    assert f"Release requested for instance {INSTANCE_UUID}." in result.output
    assert TOKEN not in result.output


def test_release_prompts_and_accepts(home: Path, monkeypatch) -> None:
    """Without ``--yes`` the command asks, then releases when confirmed."""
    _seed_token()
    called: list[str] = []

    def fake_release_instance(client, instance_id):
        called.append(instance_id)
        return {"instance_uuid": instance_id, "released": True}

    monkeypatch.setattr(instance_commands.instance_handler, "release_instance", fake_release_instance)

    result = CliRunner().invoke(main, ["instance", "release", INSTANCE_UUID], input="y\n")

    assert result.exit_code == 0, result.output
    assert f"Release instance {INSTANCE_UUID}?" in result.output
    assert called == [INSTANCE_UUID]


def test_release_prompt_can_abort(home: Path, monkeypatch) -> None:
    """Declining the prompt aborts without calling the handler."""
    _seed_token()
    monkeypatch.setattr(
        instance_commands.instance_handler,
        "release_instance",
        lambda *args, **kwargs: pytest.fail("the handler must not run when the prompt is declined"),
    )

    result = CliRunner().invoke(main, ["instance", "release", INSTANCE_UUID], input="n\n")

    assert result.exit_code == 1
    assert "Aborted" in result.output
    assert "Traceback" not in result.output


def test_release_blank_argument_is_a_clean_error(home: Path, monkeypatch) -> None:
    """A blank UUID rejected by the handler exits 1 without a traceback."""
    _seed_token()

    def failing_release_instance(client, instance_id):
        raise ValueError("instance_id must not be empty")

    monkeypatch.setattr(instance_commands.instance_handler, "release_instance", failing_release_instance)

    result = CliRunner().invoke(main, ["instance", "release", " ", "--yes"])

    assert result.exit_code == 1
    assert "instance_id must not be empty" in result.output
    assert "Traceback" not in result.output


def test_release_requires_token(home: Path, monkeypatch) -> None:
    """A missing token fails cleanly with the paste hint."""
    monkeypatch.setattr(
        instance_commands.instance_handler,
        "release_instance",
        lambda *args, **kwargs: pytest.fail("the handler must not run without a token"),
    )

    result = CliRunner().invoke(main, ["instance", "release", INSTANCE_UUID, "--yes"])

    assert result.exit_code == 1
    assert "autodl auth paste" in result.output
    assert "Traceback" not in result.output


def test_release_api_failure_is_a_clean_click_exception(home: Path, monkeypatch) -> None:
    """An API failure exits 1 without a traceback."""
    _seed_token()

    def failing_release_instance(client, instance_id):
        raise AuthError("token expired")

    monkeypatch.setattr(instance_commands.instance_handler, "release_instance", failing_release_instance)

    result = CliRunner().invoke(main, ["instance", "release", INSTANCE_UUID, "--yes"])

    assert result.exit_code == 1
    assert "token expired" in result.output
    assert "Traceback" not in result.output


CREATE_MACHINE_ID = "1c0641804d"
CREATE_BASE_IMAGE_UUID = "base-image-ee43618uo7"
CREATE_PRIVATE_IMAGE_UUID = "image-abcd1234"
CREATE_INSTANCE_UUID = "1c0641804d-de35343b"

CREATE_RECORD = {
    "instance_uuid": CREATE_INSTANCE_UUID,
    "machine_id": CREATE_MACHINE_ID,
    "gpu_amount": 2,
    "charge_type": "payg",
    "base_image_uuid": CREATE_BASE_IMAGE_UUID,
    "private_image_uuid": "",
    "instance_name": "trainer",
    "expand_data_disk": 50,
}


def test_create_forwards_explicit_machine_and_options(home: Path, monkeypatch) -> None:
    """Every option reaches ``create_instance`` and JSON is passed through."""
    _seed_token()
    captured: dict[str, object] = {}

    def fake_create_instance(client, **kwargs):
        captured.update(kwargs)
        return CREATE_RECORD

    monkeypatch.setattr(instance_commands.instance_handler, "create_instance", fake_create_instance)
    monkeypatch.setattr(
        instance_commands.instance_handler,
        "select_machine",
        lambda *args, **kwargs: pytest.fail("no machine resolution is needed with --machine-id"),
    )

    result = CliRunner().invoke(
        main,
        [
            "--json",
            "instance",
            "create",
            "--machine-id",
            f" {CREATE_MACHINE_ID} ",
            "--image",
            CREATE_BASE_IMAGE_UUID,
            "--gpu-num",
            "2",
            "--name",
            "trainer",
            "--data-disk",
            "50",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured == {
        "machine_id": CREATE_MACHINE_ID,
        "base_image_uuid": CREATE_BASE_IMAGE_UUID,
        "private_image_uuid": "",
        "gpu_amount": 2,
        "instance_name": "trainer",
        "expand_data_disk": 50,
    }
    assert json.loads(result.output) == CREATE_RECORD
    assert TOKEN not in result.output


def test_create_resolves_region_and_gpu_to_a_machine(home: Path, monkeypatch) -> None:
    """``--region``/``--gpu`` call ``select_machine`` before ordering."""
    _seed_token()
    selected: dict[str, object] = {}
    captured: dict[str, object] = {}

    def fake_select_machine(client, *, region, gpu, gpu_amount):
        selected.update(region=region, gpu=gpu, gpu_amount=gpu_amount)
        return {"machine_id": CREATE_MACHINE_ID, "gpu_name": gpu, "gpu_idle_num": 8}

    def fake_create_instance(client, **kwargs):
        captured.update(kwargs)
        return CREATE_RECORD

    monkeypatch.setattr(instance_commands.instance_handler, "select_machine", fake_select_machine)
    monkeypatch.setattr(instance_commands.instance_handler, "create_instance", fake_create_instance)

    result = CliRunner().invoke(
        main,
        [
            "--json",
            "instance",
            "create",
            "--region",
            "nm-B2",
            "--gpu",
            "RTX 3090",
            "--private-image",
            CREATE_PRIVATE_IMAGE_UUID,
        ],
    )

    assert result.exit_code == 0, result.output
    assert selected == {"region": "nm-B2", "gpu": "RTX 3090", "gpu_amount": 1}
    assert captured["machine_id"] == CREATE_MACHINE_ID
    assert captured["base_image_uuid"] == ""
    assert captured["private_image_uuid"] == CREATE_PRIVATE_IMAGE_UUID
    assert captured["gpu_amount"] == 1


def test_create_human_output_reports_order(home: Path, monkeypatch) -> None:
    """The human view names the new instance and its machine, then hints at status."""
    _seed_token()
    monkeypatch.setattr(
        instance_commands.instance_handler,
        "create_instance",
        lambda client, **kwargs: CREATE_RECORD,
    )

    result = CliRunner().invoke(
        main,
        ["instance", "create", "--machine-id", CREATE_MACHINE_ID, "--image", CREATE_BASE_IMAGE_UUID],
    )

    assert result.exit_code == 0, result.output
    assert f"Instance {CREATE_INSTANCE_UUID} ordered on machine {CREATE_MACHINE_ID}." in result.output
    assert "Check its status with `autodl instance list`." in result.output
    assert TOKEN not in result.output


def test_create_rejects_machine_id_with_region_or_gpu(home: Path, monkeypatch) -> None:
    """Mixing the two selection modes is a clean usage error."""
    _seed_token()
    monkeypatch.setattr(
        instance_commands.instance_handler,
        "create_instance",
        lambda *args, **kwargs: pytest.fail("the handler must not run for mixed selection options"),
    )

    result = CliRunner().invoke(
        main,
        [
            "instance",
            "create",
            "--machine-id",
            CREATE_MACHINE_ID,
            "--region",
            "nm-B2",
            "--image",
            CREATE_BASE_IMAGE_UUID,
        ],
    )

    assert result.exit_code == 1
    assert "Use either --machine-id or --region/--gpu, not both." in result.output
    assert "Traceback" not in result.output


@pytest.mark.parametrize(
    "selection",
    [
        [],
        ["--region", "nm-B2"],
        ["--gpu", "RTX 3090"],
    ],
)
def test_create_requires_a_complete_selection(home: Path, monkeypatch, selection: list[str]) -> None:
    """Without a machine ID, both ``--region`` and ``--gpu`` are required."""
    _seed_token()
    monkeypatch.setattr(
        instance_commands.instance_handler,
        "create_instance",
        lambda *args, **kwargs: pytest.fail("the handler must not run without a complete selection"),
    )

    result = CliRunner().invoke(
        main,
        ["instance", "create", *selection, "--image", CREATE_BASE_IMAGE_UUID],
    )

    assert result.exit_code == 1
    assert "Pass --machine-id, or both --region and --gpu." in result.output
    assert "Traceback" not in result.output


def test_create_requires_token(home: Path, monkeypatch) -> None:
    """A missing token fails cleanly with the paste hint."""
    monkeypatch.setattr(
        instance_commands.instance_handler,
        "create_instance",
        lambda *args, **kwargs: pytest.fail("the handler must not run without a token"),
    )

    result = CliRunner().invoke(
        main,
        ["instance", "create", "--machine-id", CREATE_MACHINE_ID, "--image", CREATE_BASE_IMAGE_UUID],
    )

    assert result.exit_code == 1
    assert "autodl auth paste" in result.output
    assert "Traceback" not in result.output


def test_create_api_failure_is_a_clean_click_exception(home: Path, monkeypatch) -> None:
    """An API failure exits 1 without a traceback."""
    _seed_token()

    def failing_create_instance(client, **kwargs):
        raise AuthError("token expired")

    monkeypatch.setattr(instance_commands.instance_handler, "create_instance", failing_create_instance)

    result = CliRunner().invoke(
        main,
        ["instance", "create", "--machine-id", CREATE_MACHINE_ID, "--image", CREATE_BASE_IMAGE_UUID],
    )

    assert result.exit_code == 1
    assert "token expired" in result.output
    assert "Traceback" not in result.output


def test_create_value_error_is_a_clean_click_exception(home: Path, monkeypatch) -> None:
    """A validation error from the handler exits 1 without a traceback."""
    _seed_token()

    def failing_create_instance(client, **kwargs):
        raise ValueError("exactly one of base_image_uuid and private_image_uuid must be set")

    monkeypatch.setattr(instance_commands.instance_handler, "create_instance", failing_create_instance)

    result = CliRunner().invoke(
        main,
        ["instance", "create", "--machine-id", CREATE_MACHINE_ID],
    )

    assert result.exit_code == 1
    assert "exactly one of base_image_uuid and private_image_uuid must be set" in result.output
    assert "Traceback" not in result.output


CLONE_SOURCE_UUID = "71f24fb92a-e99de0d2"
CLONE_SOURCE_BASE_IMAGE_UUID = "base-image-ee43618uo7"
CLONE_SOURCE_GPU_AMOUNT = 3
CLONE_MACHINE_ID = "eb534b8ca9"
CLONE_NEW_UUID = "eb534b8ca9-0a1b2c3d"

CLONE_SOURCE = {
    "instance_uuid": CLONE_SOURCE_UUID,
    "base_image_uuid": CLONE_SOURCE_BASE_IMAGE_UUID,
    "private_image_uuid": "",
    "gpu_amount": CLONE_SOURCE_GPU_AMOUNT,
}

CLONE_RECORD = {
    "instance_uuid": CLONE_NEW_UUID,
    "source_instance_uuid": CLONE_SOURCE_UUID,
    "machine_id": CLONE_MACHINE_ID,
    "gpu_amount": CLONE_SOURCE_GPU_AMOUNT,
    "charge_type": "payg",
    "base_image_uuid": CLONE_SOURCE_BASE_IMAGE_UUID,
    "private_image_uuid": "",
    "instance_name": "trainer",
    "expand_data_disk": 50,
    "copy_data_disk": True,
    "keep_src_user_service_address": False,
}


def test_clone_forwards_explicit_machine_and_source_values(home: Path, monkeypatch) -> None:
    """The explicit machine and derived source values reach ``clone_instance``."""
    _seed_token()
    captured: dict[str, object] = {}

    def fake_resolve_clone_source(client, instance_uuid):
        captured["source_uuid"] = instance_uuid
        return CLONE_SOURCE

    def fake_clone_instance(client, instance_uuid, **kwargs):
        captured["instance_uuid"] = instance_uuid
        captured.update(kwargs)
        return CLONE_RECORD

    monkeypatch.setattr(instance_commands.instance_handler, "resolve_clone_source", fake_resolve_clone_source)
    monkeypatch.setattr(instance_commands.instance_handler, "clone_instance", fake_clone_instance)
    monkeypatch.setattr(
        instance_commands.instance_handler,
        "select_machine",
        lambda *args, **kwargs: pytest.fail("no machine resolution is needed with --machine-id"),
    )

    result = CliRunner().invoke(
        main,
        [
            "--json",
            "instance",
            "clone",
            CLONE_SOURCE_UUID,
            "--machine-id",
            f" {CLONE_MACHINE_ID} ",
            "--name",
            "trainer",
            "--data-disk",
            "50",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured == {
        "source_uuid": CLONE_SOURCE_UUID,
        "instance_uuid": CLONE_SOURCE_UUID,
        "machine_id": CLONE_MACHINE_ID,
        "base_image_uuid": CLONE_SOURCE_BASE_IMAGE_UUID,
        "private_image_uuid": "",
        "gpu_amount": CLONE_SOURCE_GPU_AMOUNT,
        "instance_name": "trainer",
        "expand_data_disk": 50,
        "copy_data_disk": True,
        "keep_src_user_service_address": False,
    }
    assert json.loads(result.output) == CLONE_RECORD
    assert TOKEN not in result.output


def test_clone_gpu_num_overrides_derived_amount(home: Path, monkeypatch) -> None:
    """``--gpu-num`` replaces the GPU count inherited from the source."""
    _seed_token()
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        instance_commands.instance_handler,
        "resolve_clone_source",
        lambda client, instance_uuid: CLONE_SOURCE,
    )

    def fake_clone_instance(client, instance_uuid, **kwargs):
        captured.update(kwargs)
        return CLONE_RECORD

    monkeypatch.setattr(instance_commands.instance_handler, "clone_instance", fake_clone_instance)

    result = CliRunner().invoke(
        main,
        [
            "--json",
            "instance",
            "clone",
            CLONE_SOURCE_UUID,
            "--machine-id",
            CLONE_MACHINE_ID,
            "--gpu-num",
            "2",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["gpu_amount"] == 2


def test_clone_resolves_region_and_gpu_with_derived_amount(home: Path, monkeypatch) -> None:
    """``--region``/``--gpu`` call ``select_machine`` with the source GPU count."""
    _seed_token()
    selected: dict[str, object] = {}
    captured: dict[str, object] = {}

    def fake_select_machine(client, *, region, gpu, gpu_amount):
        selected.update(region=region, gpu=gpu, gpu_amount=gpu_amount)
        return {"machine_id": CLONE_MACHINE_ID, "gpu_name": gpu, "gpu_idle_num": 8}

    def fake_clone_instance(client, instance_uuid, **kwargs):
        captured.update(kwargs)
        return CLONE_RECORD

    monkeypatch.setattr(
        instance_commands.instance_handler,
        "resolve_clone_source",
        lambda client, instance_uuid: CLONE_SOURCE,
    )
    monkeypatch.setattr(instance_commands.instance_handler, "select_machine", fake_select_machine)
    monkeypatch.setattr(instance_commands.instance_handler, "clone_instance", fake_clone_instance)

    result = CliRunner().invoke(
        main,
        [
            "--json",
            "instance",
            "clone",
            CLONE_SOURCE_UUID,
            "--region",
            "nm-B2",
            "--gpu",
            "RTX 3090",
        ],
    )

    assert result.exit_code == 0, result.output
    assert selected == {"region": "nm-B2", "gpu": "RTX 3090", "gpu_amount": CLONE_SOURCE_GPU_AMOUNT}
    assert captured["machine_id"] == CLONE_MACHINE_ID
    assert captured["gpu_amount"] == CLONE_SOURCE_GPU_AMOUNT


def test_clone_human_output_reports_clone(home: Path, monkeypatch) -> None:
    """The human view names the clone, its source, and the target machine."""
    _seed_token()
    monkeypatch.setattr(output_module, "console", Console(width=160))
    monkeypatch.setattr(
        instance_commands.instance_handler,
        "resolve_clone_source",
        lambda client, instance_uuid: CLONE_SOURCE,
    )
    monkeypatch.setattr(
        instance_commands.instance_handler,
        "clone_instance",
        lambda client, instance_uuid, **kwargs: CLONE_RECORD,
    )

    result = CliRunner().invoke(
        main,
        ["instance", "clone", CLONE_SOURCE_UUID, "--machine-id", CLONE_MACHINE_ID],
    )

    assert result.exit_code == 0, result.output
    assert f"Instance {CLONE_NEW_UUID} cloned from {CLONE_SOURCE_UUID} on machine {CLONE_MACHINE_ID}." in result.output
    assert "Check its status with `autodl instance list`." in result.output
    assert TOKEN not in result.output


def test_clone_rejects_machine_id_with_region_or_gpu(home: Path, monkeypatch) -> None:
    """Mixing the two selection modes is a clean usage error."""
    _seed_token()
    monkeypatch.setattr(
        instance_commands.instance_handler,
        "resolve_clone_source",
        lambda *args, **kwargs: pytest.fail("the handler must not run for mixed selection options"),
    )

    result = CliRunner().invoke(
        main,
        [
            "instance",
            "clone",
            CLONE_SOURCE_UUID,
            "--machine-id",
            CLONE_MACHINE_ID,
            "--region",
            "nm-B2",
        ],
    )

    assert result.exit_code == 1
    assert "Use either --machine-id or --region/--gpu, not both." in result.output
    assert "Traceback" not in result.output


@pytest.mark.parametrize(
    "selection",
    [
        [],
        ["--region", "nm-B2"],
        ["--gpu", "RTX 3090"],
    ],
)
def test_clone_requires_a_complete_selection(home: Path, monkeypatch, selection: list[str]) -> None:
    """Without a machine ID, both ``--region`` and ``--gpu`` are required."""
    _seed_token()
    monkeypatch.setattr(
        instance_commands.instance_handler,
        "resolve_clone_source",
        lambda *args, **kwargs: pytest.fail("the handler must not run without a complete selection"),
    )

    result = CliRunner().invoke(main, ["instance", "clone", CLONE_SOURCE_UUID, *selection])

    assert result.exit_code == 1
    assert "Pass --machine-id, or both --region and --gpu." in result.output
    assert "Traceback" not in result.output


def test_clone_requires_token(home: Path, monkeypatch) -> None:
    """A missing token fails cleanly with the paste hint."""
    monkeypatch.setattr(
        instance_commands.instance_handler,
        "resolve_clone_source",
        lambda *args, **kwargs: pytest.fail("the handler must not run without a token"),
    )

    result = CliRunner().invoke(
        main,
        ["instance", "clone", CLONE_SOURCE_UUID, "--machine-id", CLONE_MACHINE_ID],
    )

    assert result.exit_code == 1
    assert "autodl auth paste" in result.output
    assert "Traceback" not in result.output


def test_clone_api_failure_is_a_clean_click_exception(home: Path, monkeypatch) -> None:
    """An API failure exits 1 without a traceback."""
    _seed_token()

    def failing_resolve_clone_source(client, instance_uuid):
        raise AuthError("token expired")

    monkeypatch.setattr(instance_commands.instance_handler, "resolve_clone_source", failing_resolve_clone_source)

    result = CliRunner().invoke(
        main,
        ["instance", "clone", CLONE_SOURCE_UUID, "--machine-id", CLONE_MACHINE_ID],
    )

    assert result.exit_code == 1
    assert "token expired" in result.output
    assert "Traceback" not in result.output


def test_clone_value_error_is_a_clean_click_exception(home: Path, monkeypatch) -> None:
    """A validation error from the handler exits 1 without a traceback."""
    _seed_token()
    monkeypatch.setattr(
        instance_commands.instance_handler,
        "resolve_clone_source",
        lambda client, instance_uuid: CLONE_SOURCE,
    )

    def failing_clone_instance(client, instance_uuid, **kwargs):
        raise ValueError("instance_uuid must not be empty")

    monkeypatch.setattr(instance_commands.instance_handler, "clone_instance", failing_clone_instance)

    result = CliRunner().invoke(
        main,
        ["instance", "clone", CLONE_SOURCE_UUID, "--machine-id", CLONE_MACHINE_ID],
    )

    assert result.exit_code == 1
    assert "instance_uuid must not be empty" in result.output
    assert "Traceback" not in result.output


SCHEDULE_INSTANCE_UUID = "9b384da211-e57974ef"
SHUTDOWN_WIRE_TIME = "2026-11-13 00:00"


def test_schedule_shutdown_at_parses_naive_time_as_beijing(home: Path, monkeypatch) -> None:
    """``--at`` without an offset reaches the handler as UTC+8."""
    _seed_token()
    captured: dict[str, object] = {}

    def fake_schedule_shutdown(client, instance_id, *, shutdown_at):
        captured["instance_id"] = instance_id
        captured["shutdown_at"] = shutdown_at
        return {
            "instance_uuid": instance_id,
            "shutdown_at": shutdown_at.strftime("%Y-%m-%d %H:%M"),
        }

    monkeypatch.setattr(instance_commands.instance_handler, "schedule_shutdown", fake_schedule_shutdown)

    result = CliRunner().invoke(
        main,
        ["--json", "instance", "schedule-shutdown", SCHEDULE_INSTANCE_UUID, "--at", "2026-11-13 00:00"],
    )

    assert result.exit_code == 0, result.output
    assert captured["instance_id"] == SCHEDULE_INSTANCE_UUID
    assert captured["shutdown_at"].isoformat() == "2026-11-13T00:00:00+08:00"
    assert json.loads(result.output) == {
        "instance_uuid": SCHEDULE_INSTANCE_UUID,
        "shutdown_at": SHUTDOWN_WIRE_TIME,
    }
    assert TOKEN not in result.output


def test_schedule_shutdown_at_with_offset_converts_to_utc_plus_8(home: Path, monkeypatch) -> None:
    """An explicit offset is converted to Beijing time before reaching the handler."""
    _seed_token()
    captured: dict[str, object] = {}

    def fake_schedule_shutdown(client, instance_id, *, shutdown_at):
        captured["shutdown_at"] = shutdown_at
        return {
            "instance_uuid": instance_id,
            "shutdown_at": shutdown_at.strftime("%Y-%m-%d %H:%M"),
        }

    monkeypatch.setattr(instance_commands.instance_handler, "schedule_shutdown", fake_schedule_shutdown)

    result = CliRunner().invoke(
        main,
        ["--json", "instance", "schedule-shutdown", SCHEDULE_INSTANCE_UUID, "--at", "2026-11-12T18:00:00Z"],
    )

    assert result.exit_code == 0, result.output
    assert captured["shutdown_at"].isoformat() == "2026-11-13T02:00:00+08:00"
    assert json.loads(result.output)["shutdown_at"] == "2026-11-13 02:00"


def test_schedule_shutdown_in_uses_the_frozen_clock(home: Path, monkeypatch) -> None:
    """``--in 90m`` adds 90 minutes to the monkeypatched Beijing clock."""
    _seed_token()
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        instance_commands,
        "_now_beijing",
        lambda: datetime(2026, 11, 12, 10, 0, tzinfo=timezone(timedelta(hours=8))),
    )

    def fake_schedule_shutdown(client, instance_id, *, shutdown_at):
        captured["shutdown_at"] = shutdown_at
        return {
            "instance_uuid": instance_id,
            "shutdown_at": shutdown_at.strftime("%Y-%m-%d %H:%M"),
        }

    monkeypatch.setattr(instance_commands.instance_handler, "schedule_shutdown", fake_schedule_shutdown)

    result = CliRunner().invoke(
        main,
        ["instance", "schedule-shutdown", SCHEDULE_INSTANCE_UUID, "--in", "90m"],
    )

    assert result.exit_code == 0, result.output
    assert captured["shutdown_at"].isoformat() == "2026-11-12T11:30:00+08:00"
    assert f"Scheduled shutdown for instance {SCHEDULE_INSTANCE_UUID} at 2026-11-12 11:30 (UTC+8)." in result.output


def test_schedule_shutdown_rerun_modifies_the_time(home: Path, monkeypatch) -> None:
    """Running the command again is the documented way to change the schedule."""
    _seed_token()
    calls: list[str] = []

    monkeypatch.setattr(
        instance_commands,
        "_now_beijing",
        lambda: datetime(2026, 11, 12, 10, 0, tzinfo=timezone(timedelta(hours=8))),
    )

    def fake_schedule_shutdown(client, instance_id, *, shutdown_at):
        calls.append(shutdown_at.strftime("%Y-%m-%d %H:%M"))
        return {"instance_uuid": instance_id, "shutdown_at": calls[-1]}

    monkeypatch.setattr(instance_commands.instance_handler, "schedule_shutdown", fake_schedule_shutdown)

    first = CliRunner().invoke(
        main, ["instance", "schedule-shutdown", SCHEDULE_INSTANCE_UUID, "--at", "2026-11-13 00:00"]
    )
    second = CliRunner().invoke(main, ["instance", "schedule-shutdown", SCHEDULE_INSTANCE_UUID, "--in", "2h"])

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    assert calls == ["2026-11-13 00:00", "2026-11-12 12:00"]


def test_schedule_shutdown_requires_exactly_one_time_option(home: Path, monkeypatch) -> None:
    """Neither or both of ``--at``/``--in`` is a clean error."""
    _seed_token()
    monkeypatch.setattr(
        instance_commands.instance_handler,
        "schedule_shutdown",
        lambda *args, **kwargs: pytest.fail("the handler must not run without exactly one time option"),
    )

    missing = CliRunner().invoke(main, ["instance", "schedule-shutdown", SCHEDULE_INSTANCE_UUID])
    both = CliRunner().invoke(
        main,
        ["instance", "schedule-shutdown", SCHEDULE_INSTANCE_UUID, "--at", "2026-11-13 00:00", "--in", "1h"],
    )

    for result in (missing, both):
        assert result.exit_code == 1
        assert "Pass exactly one of --at and --in." in result.output
        assert "Traceback" not in result.output


def test_schedule_shutdown_rejects_past_time(home: Path, monkeypatch) -> None:
    """An ``--at`` in the past is a clean error."""
    _seed_token()
    monkeypatch.setattr(
        instance_commands,
        "_now_beijing",
        lambda: datetime(2026, 11, 12, 10, 0, tzinfo=timezone(timedelta(hours=8))),
    )
    monkeypatch.setattr(
        instance_commands.instance_handler,
        "schedule_shutdown",
        lambda *args, **kwargs: pytest.fail("the handler must not run for a past time"),
    )

    result = CliRunner().invoke(
        main,
        ["instance", "schedule-shutdown", SCHEDULE_INSTANCE_UUID, "--at", "2026-11-11 10:00"],
    )

    assert result.exit_code == 1
    assert "--at must be in the future" in result.output
    assert "Traceback" not in result.output


def test_schedule_shutdown_rejects_invalid_values(home: Path, monkeypatch) -> None:
    """Malformed ``--at`` and ``--in`` values are clean errors."""
    _seed_token()
    monkeypatch.setattr(
        instance_commands.instance_handler,
        "schedule_shutdown",
        lambda *args, **kwargs: pytest.fail("the handler must not run for invalid input"),
    )

    bad_at = CliRunner().invoke(main, ["instance", "schedule-shutdown", SCHEDULE_INSTANCE_UUID, "--at", "tomorrow"])
    bad_in = CliRunner().invoke(main, ["instance", "schedule-shutdown", SCHEDULE_INSTANCE_UUID, "--in", "soon"])
    zero_in = CliRunner().invoke(main, ["instance", "schedule-shutdown", SCHEDULE_INSTANCE_UUID, "--in", "0m"])

    for result in (bad_at, bad_in, zero_in):
        assert result.exit_code == 1
        assert "Traceback" not in result.output
    assert "Invalid --at" in bad_at.output
    assert "Invalid --in" in bad_in.output
    assert "--in must be positive" in zero_in.output


def test_schedule_shutdown_requires_token(home: Path, monkeypatch) -> None:
    """A missing token fails cleanly with the paste hint."""
    monkeypatch.setattr(
        instance_commands,
        "_now_beijing",
        lambda: datetime(2026, 11, 12, 10, 0, tzinfo=timezone(timedelta(hours=8))),
    )
    monkeypatch.setattr(
        instance_commands.instance_handler,
        "schedule_shutdown",
        lambda *args, **kwargs: pytest.fail("the handler must not run without a token"),
    )

    result = CliRunner().invoke(
        main,
        ["instance", "schedule-shutdown", SCHEDULE_INSTANCE_UUID, "--at", "2026-11-13 00:00"],
    )

    assert result.exit_code == 1
    assert "autodl auth paste" in result.output
    assert "Traceback" not in result.output


def test_schedule_shutdown_api_failure_is_a_clean_click_exception(home: Path, monkeypatch) -> None:
    """An API failure exits 1 without a traceback."""
    _seed_token()
    monkeypatch.setattr(
        instance_commands,
        "_now_beijing",
        lambda: datetime(2026, 11, 12, 10, 0, tzinfo=timezone(timedelta(hours=8))),
    )

    def failing_schedule_shutdown(client, instance_id, *, shutdown_at):
        raise AuthError("token expired")

    monkeypatch.setattr(instance_commands.instance_handler, "schedule_shutdown", failing_schedule_shutdown)

    result = CliRunner().invoke(
        main,
        ["instance", "schedule-shutdown", SCHEDULE_INSTANCE_UUID, "--at", "2026-11-13 00:00"],
    )

    assert result.exit_code == 1
    assert "token expired" in result.output
    assert "Traceback" not in result.output


def test_cancel_shutdown_forwards_instance_and_returns_json(home: Path, monkeypatch) -> None:
    """The UUID reaches the handler and JSON is passed through, without a prompt."""
    _seed_token()
    captured: dict[str, object] = {}
    record = {"instance_uuid": SCHEDULE_INSTANCE_UUID, "shutdown_scheduled": False}

    def fake_cancel_scheduled_shutdown(client, instance_id):
        captured["instance_id"] = instance_id
        return record

    monkeypatch.setattr(
        instance_commands.instance_handler,
        "cancel_scheduled_shutdown",
        fake_cancel_scheduled_shutdown,
    )

    result = CliRunner().invoke(main, ["--json", "instance", "cancel-shutdown", SCHEDULE_INSTANCE_UUID])

    assert result.exit_code == 0, result.output
    assert captured == {"instance_id": SCHEDULE_INSTANCE_UUID}
    assert json.loads(result.output) == record
    assert TOKEN not in result.output


def test_cancel_shutdown_human_output_reports_success(home: Path, monkeypatch) -> None:
    """The human view confirms the cancelled schedule."""
    _seed_token()
    monkeypatch.setattr(
        instance_commands.instance_handler,
        "cancel_scheduled_shutdown",
        lambda client, instance_id: {"instance_uuid": instance_id, "shutdown_scheduled": False},
    )

    result = CliRunner().invoke(main, ["instance", "cancel-shutdown", SCHEDULE_INSTANCE_UUID])

    assert result.exit_code == 0, result.output
    assert f"Cancelled the scheduled shutdown for instance {SCHEDULE_INSTANCE_UUID}." in result.output
    assert TOKEN not in result.output


def test_cancel_shutdown_requires_token(home: Path, monkeypatch) -> None:
    """A missing token fails cleanly with the paste hint."""
    monkeypatch.setattr(
        instance_commands.instance_handler,
        "cancel_scheduled_shutdown",
        lambda *args, **kwargs: pytest.fail("the handler must not run without a token"),
    )

    result = CliRunner().invoke(main, ["instance", "cancel-shutdown", SCHEDULE_INSTANCE_UUID])

    assert result.exit_code == 1
    assert "autodl auth paste" in result.output
    assert "Traceback" not in result.output


def test_cancel_shutdown_api_failure_is_a_clean_click_exception(home: Path, monkeypatch) -> None:
    """An API failure exits 1 without a traceback."""
    _seed_token()

    def failing_cancel_scheduled_shutdown(client, instance_id):
        raise AuthError("token expired")

    monkeypatch.setattr(
        instance_commands.instance_handler,
        "cancel_scheduled_shutdown",
        failing_cancel_scheduled_shutdown,
    )

    result = CliRunner().invoke(main, ["instance", "cancel-shutdown", SCHEDULE_INSTANCE_UUID])

    assert result.exit_code == 1
    assert "token expired" in result.output
    assert "Traceback" not in result.output


WAIT_RECORD = {
    "instance_uuid": INSTANCE_UUID,
    "status": "running",
    "waited_seconds": 5.0,
    "instance": {"uuid": INSTANCE_UUID, "status": "running"},
}

IMAGE_WAIT_RECORD = {
    "image_uuid": "image-new",
    "image_id": 9001,
    "name": "save-image-test1",
    "status": "finished",
    "waited_seconds": 5.0,
    "image": {"id": 9001, "status": "finished", "name": "save-image-test1"},
}


def test_wait_forwards_options_and_returns_json(home: Path, monkeypatch) -> None:
    """``--until``, ``--interval``, ``--timeout``, and ``--retry`` reach the handler."""
    _seed_token()
    captured: dict[str, object] = {}

    def fake_wait_for_instance(client, instance_uuid, **kwargs):
        captured["instance_uuid"] = instance_uuid
        captured.update(kwargs)
        return WAIT_RECORD

    monkeypatch.setattr(instance_commands.instance_handler, "wait_for_instance", fake_wait_for_instance)

    result = CliRunner().invoke(
        main,
        [
            "--json",
            "instance",
            "wait",
            INSTANCE_UUID,
            "--until",
            "shutdown",
            "--interval",
            "5",
            "--timeout",
            "30",
            "--retry",
            "2",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured == {
        "instance_uuid": INSTANCE_UUID,
        "until": "shutdown",
        "interval": 5.0,
        "timeout": 30.0,
        "retry": 2,
        "on_event": None,
    }
    assert json.loads(result.output) == WAIT_RECORD
    assert TOKEN not in result.output


def test_wait_human_output_renders_events_and_final_status(home: Path, monkeypatch) -> None:
    """Progress events are printed in text mode, then a final success line."""

    def fake_wait_for_instance(client, instance_uuid, **kwargs):
        callback = kwargs["on_event"]
        callback({"event": "instance_status", "instance_uuid": instance_uuid, "status": "not found"})
        callback({"event": "instance_status", "instance_uuid": instance_uuid, "status": "creating"})
        callback({"event": "poll_failed", "error": "boom", "retries": 1, "limit": 1})
        callback({"event": "instance_status", "instance_uuid": instance_uuid, "status": "running"})
        callback({"event": "running", "instance_uuid": instance_uuid})
        return WAIT_RECORD

    _seed_token()
    monkeypatch.setattr(instance_commands.instance_handler, "wait_for_instance", fake_wait_for_instance)

    result = CliRunner().invoke(main, ["instance", "wait", INSTANCE_UUID])

    assert result.exit_code == 0, result.output
    assert "Instance status: not visible yet." in result.output
    assert "Instance status: creating." in result.output
    assert "Poll failed: boom; retrying (1/1)." in result.output
    assert f"Instance {INSTANCE_UUID} is running." in result.output
    assert f"Instance {INSTANCE_UUID} reached status 'running' after 5s." in result.output


def test_wait_timeout_is_a_clean_click_exception(home: Path, monkeypatch) -> None:
    """A handler timeout exits 1 without a traceback."""
    _seed_token()

    def failing_wait(client, instance_uuid, **kwargs):
        raise TimeoutError("Timed out after 1s waiting for instance")

    monkeypatch.setattr(instance_commands.instance_handler, "wait_for_instance", failing_wait)

    result = CliRunner().invoke(main, ["instance", "wait", INSTANCE_UUID, "--timeout", "1"])

    assert result.exit_code == 1
    assert "Timed out after 1s waiting for instance" in result.output
    assert "Traceback" not in result.output


def test_power_on_wait_merges_json_and_uses_defaults(home: Path, monkeypatch) -> None:
    """``--wait`` resolves the tuning defaults and merges the wait result into JSON."""
    _seed_token()
    captured: dict[str, object] = {}
    record = {"instance_uuid": INSTANCE_UUID, "powered_on": True, "non_gpu": False}

    monkeypatch.setattr(
        instance_commands.instance_handler,
        "power_on",
        lambda client, instance_id, *, non_gpu=False: record,
    )

    def fake_wait(client, instance_uuid, **kwargs):
        captured["instance_uuid"] = instance_uuid
        captured.update(kwargs)
        return WAIT_RECORD

    monkeypatch.setattr(instance_commands.instance_handler, "wait_for_instance", fake_wait)

    result = CliRunner().invoke(main, ["--json", "instance", "power-on", INSTANCE_UUID, "--wait"])

    assert result.exit_code == 0, result.output
    assert captured == {
        "instance_uuid": INSTANCE_UUID,
        "interval": 10.0,
        "timeout": 0.0,
        "retry": 0,
        "on_event": None,
    }
    assert json.loads(result.output) == {
        **record,
        "status": "running",
        "waited_seconds": 5.0,
        "instance": {"uuid": INSTANCE_UUID, "status": "running"},
    }


def test_power_on_wait_human_output_keeps_messages(home: Path, monkeypatch) -> None:
    """The existing power-on success message stays, followed by the final status."""
    _seed_token()
    monkeypatch.setattr(
        instance_commands.instance_handler,
        "power_on",
        lambda client, instance_id, *, non_gpu=False: {
            "instance_uuid": instance_id,
            "powered_on": True,
            "non_gpu": non_gpu,
        },
    )

    def fake_wait(client, instance_uuid, **kwargs):
        kwargs["on_event"]({"event": "running", "instance_uuid": instance_uuid})
        return WAIT_RECORD

    monkeypatch.setattr(instance_commands.instance_handler, "wait_for_instance", fake_wait)

    result = CliRunner().invoke(main, ["instance", "power-on", INSTANCE_UUID, "--wait"])

    assert result.exit_code == 0, result.output
    assert f"Power-on requested for instance {INSTANCE_UUID}." in result.output
    assert f"Instance {INSTANCE_UUID} is running." in result.output
    assert f"Instance {INSTANCE_UUID} reached status 'running' after 5s." in result.output


def test_power_on_without_wait_does_not_poll(home: Path, monkeypatch) -> None:
    """Without ``--wait`` the handler is called once and no wait loop starts."""
    _seed_token()
    record = {"instance_uuid": INSTANCE_UUID, "powered_on": True, "non_gpu": False}
    monkeypatch.setattr(
        instance_commands.instance_handler,
        "power_on",
        lambda client, instance_id, *, non_gpu=False: record,
    )
    monkeypatch.setattr(
        instance_commands.instance_handler,
        "wait_for_instance",
        lambda *args, **kwargs: pytest.fail("the wait loop must not start without --wait"),
    )

    result = CliRunner().invoke(main, ["--json", "instance", "power-on", INSTANCE_UUID])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == record


@pytest.mark.parametrize("option", [["--interval", "5"], ["--timeout", "10"], ["--retry", "2"]])
def test_wait_tuning_options_require_wait(home: Path, monkeypatch, option: list[str]) -> None:
    """A tuning option without ``--wait`` is a usage error."""
    _seed_token()
    monkeypatch.setattr(
        instance_commands.instance_handler,
        "power_on",
        lambda *args, **kwargs: pytest.fail("the handler must not run for a usage error"),
    )

    result = CliRunner().invoke(main, ["instance", "power-on", INSTANCE_UUID, *option])

    assert result.exit_code == 2
    assert "--interval/--timeout/--retry require --wait." in result.output


def test_create_wait_merges_json_and_forwards_resolved_options(home: Path, monkeypatch) -> None:
    """``create --wait`` waits for the new instance and merges its status."""
    _seed_token()
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        instance_commands.instance_handler,
        "create_instance",
        lambda client, **kwargs: CREATE_RECORD,
    )

    def fake_wait(client, instance_uuid, **kwargs):
        captured["instance_uuid"] = instance_uuid
        captured.update(kwargs)
        return WAIT_RECORD

    monkeypatch.setattr(instance_commands.instance_handler, "wait_for_instance", fake_wait)

    result = CliRunner().invoke(
        main,
        [
            "--json",
            "instance",
            "create",
            "--machine-id",
            CREATE_MACHINE_ID,
            "--image",
            CREATE_BASE_IMAGE_UUID,
            "--wait",
            "--interval",
            "3",
            "--timeout",
            "60",
            "--retry",
            "1",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured == {
        "instance_uuid": CREATE_INSTANCE_UUID,
        "interval": 3.0,
        "timeout": 60.0,
        "retry": 1,
        "on_event": None,
    }
    assert json.loads(result.output) == {
        **CREATE_RECORD,
        "status": "running",
        "waited_seconds": 5.0,
        "instance": {"uuid": INSTANCE_UUID, "status": "running"},
    }


def test_clone_wait_merges_json_and_forwards_events(home: Path, monkeypatch) -> None:
    """``clone --wait`` waits for the clone and passes the text-mode callback."""
    _seed_token()
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        instance_commands.instance_handler,
        "resolve_clone_source",
        lambda client, instance_uuid: CLONE_SOURCE,
    )
    monkeypatch.setattr(
        instance_commands.instance_handler,
        "clone_instance",
        lambda client, instance_uuid, **kwargs: CLONE_RECORD,
    )

    def fake_wait(client, instance_uuid, **kwargs):
        captured["instance_uuid"] = instance_uuid
        captured.update(kwargs)
        return WAIT_RECORD

    monkeypatch.setattr(instance_commands.instance_handler, "wait_for_instance", fake_wait)

    result = CliRunner().invoke(
        main,
        [
            "--json",
            "instance",
            "clone",
            CLONE_SOURCE_UUID,
            "--machine-id",
            CLONE_MACHINE_ID,
            "--wait",
            "--retry",
            "2",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["instance_uuid"] == CLONE_NEW_UUID
    assert captured["interval"] == 10.0
    assert captured["timeout"] == 0.0
    assert captured["retry"] == 2
    assert captured["on_event"] is None
    assert json.loads(result.output)["status"] == "running"
    assert json.loads(result.output)["instance"] == {"uuid": INSTANCE_UUID, "status": "running"}


def test_save_image_wait_snapshots_before_saving(home: Path, monkeypatch) -> None:
    """The previous-status snapshot is taken before the save request."""
    _seed_token()
    order: list[tuple[str, object]] = []

    def fake_snapshot(client, instance_uuid, image_name):
        order.append(("snapshot", (instance_uuid, image_name)))
        return {9001: "saving"}

    def fake_save_image(client, instance_id, image_name, *, try_again):
        order.append(("save", (instance_id, image_name, try_again)))
        return {
            "instance_uuid": instance_id,
            "image_name": image_name,
            "try_again": try_again,
            "saved": True,
        }

    def fake_wait(client, **kwargs):
        order.append(("wait", kwargs["previous_statuses"]))
        return IMAGE_WAIT_RECORD

    monkeypatch.setattr(instance_commands.image_handler, "private_image_status_snapshot", fake_snapshot)
    monkeypatch.setattr(instance_commands.instance_handler, "save_image", fake_save_image)
    monkeypatch.setattr(instance_commands.image_handler, "wait_for_private_image", fake_wait)

    result = CliRunner().invoke(
        main,
        ["--json", "instance", "save-image", INSTANCE_UUID, "save-image-test1", "--try-again", "--wait"],
    )

    assert result.exit_code == 0, result.output
    assert order == [
        ("snapshot", (INSTANCE_UUID, "save-image-test1")),
        ("save", (INSTANCE_UUID, "save-image-test1", True)),
        ("wait", {9001: "saving"}),
    ]
    payload = json.loads(result.output)
    assert payload["saved"] is True
    assert payload["status"] == "finished"
    assert payload["waited_seconds"] == 5.0
    assert payload["image"] == IMAGE_WAIT_RECORD["image"]


def test_save_image_wait_timeout_is_a_clean_click_exception(home: Path, monkeypatch) -> None:
    """A timeout while waiting for the image exits 1 without a traceback."""
    _seed_token()
    monkeypatch.setattr(
        instance_commands.image_handler,
        "private_image_status_snapshot",
        lambda client, instance_uuid, image_name: {},
    )
    monkeypatch.setattr(
        instance_commands.instance_handler,
        "save_image",
        lambda client, instance_id, image_name, *, try_again: {
            "instance_uuid": instance_id,
            "image_name": image_name,
            "try_again": try_again,
            "saved": True,
        },
    )

    def failing_wait(client, **kwargs):
        raise TimeoutError("Timed out after 1s waiting for image")

    monkeypatch.setattr(instance_commands.image_handler, "wait_for_private_image", failing_wait)

    result = CliRunner().invoke(
        main,
        ["instance", "save-image", INSTANCE_UUID, "save-image-test1", "--wait", "--timeout", "1"],
    )

    assert result.exit_code == 1
    assert "Timed out after 1s waiting for image" in result.output
    assert "Traceback" not in result.output
