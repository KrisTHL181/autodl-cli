"""Tests for ``autodl gpu`` commands through the real Click entry point."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from rich.console import Console

from autodl_cli import config as config_module
from autodl_cli import output as output_module
from autodl_cli.commands import gpu as gpu_commands
from autodl_cli.errors import AuthError
from autodl_cli.main import main

TOKEN = "fake-token"

GPU_REGIONS = [
    {
        "data_center": "westDC3",
        "region_name": "西北B区",
        "region_signs": ["west-B", "west-C", "west-D", "west-E"],
        "visible": "all",
        "used_for": "all",
    },
    {
        "data_center": "foshanDC1",
        "region_name": "佛山区",
        "region_signs": ["foshan-A"],
        "visible": "all",
        "used_for": "all",
    },
]

GPU_AVAILABILITY = [
    {
        "data_center": "westDC3",
        "region_name": "西北B区",
        "region_signs": ["west-B", "west-C", "west-D", "west-E"],
        "gpus": [
            {
                "region_name": "西北B区",
                "data_center": "westDC3",
                "region_signs": ["west-B", "west-C", "west-D", "west-E"],
                "gpu_type": "A100",
                "total_gpu_num": 80,
                "idle_gpu_num": 5,
                "chip_corp": "nvidia",
                "cpu_arch": "x86",
            },
            {
                "region_name": "西北B区",
                "data_center": "westDC3",
                "region_signs": ["west-B", "west-C", "west-D", "west-E"],
                "gpu_type": "RTX 4090",
                "total_gpu_num": 735,
                "idle_gpu_num": 1,
                "chip_corp": "nvidia",
                "cpu_arch": "x86",
            },
        ],
    },
    {
        "data_center": "foshanDC1",
        "region_name": "佛山区",
        "region_signs": ["foshan-A"],
        "gpus": [],
    },
]

GPU_MATCHES = [
    {
        "region_name": "西北B区",
        "data_center": "westDC3",
        "region_signs": ["west-B", "west-C", "west-D", "west-E"],
        "gpu_type": "RTX 4090",
        "total_gpu_num": 735,
        "idle_gpu_num": 1,
        "chip_corp": "nvidia",
        "cpu_arch": "x86",
    },
    {
        "region_name": "佛山区",
        "data_center": "foshanDC1",
        "region_signs": ["foshan-A"],
        "gpu_type": "RTX 4090",
        "total_gpu_num": 12,
        "idle_gpu_num": 0,
        "chip_corp": "nvidia",
        "cpu_arch": "x86",
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
    """Store a token so the GPU commands can run."""
    config_module.save_config({"token": TOKEN})


def _patch_gpu_handler(monkeypatch, captured: dict[str, object]) -> None:
    """Replace the GPU availability handlers with offline fakes.

    :param monkeypatch: pytest's monkeypatch fixture.
    :param captured: Mapping filled with the arguments the command forwards.
    """

    def fake_list_gpu_availability(client, regions, *, available_only=False):
        captured["regions"] = regions
        captured["available_only"] = available_only
        return GPU_AVAILABILITY

    monkeypatch.setattr(gpu_commands.gpu_handler, "list_regions", lambda client: GPU_REGIONS)
    monkeypatch.setattr(gpu_commands.gpu_handler, "list_gpu_availability", fake_list_gpu_availability)


def _patch_find_handler(monkeypatch, captured: dict[str, object]) -> None:
    """Replace the GPU search handlers with offline fakes.

    :param monkeypatch: pytest's monkeypatch fixture.
    :param captured: Mapping filled with the arguments the command forwards.
    """

    def fake_find_gpu(client, regions, model, *, available_only=False):
        captured["regions"] = regions
        captured["model"] = model
        captured["available_only"] = available_only
        return GPU_MATCHES

    monkeypatch.setattr(gpu_commands.gpu_handler, "list_regions", lambda client: GPU_REGIONS)
    monkeypatch.setattr(gpu_commands.gpu_handler, "find_gpu", fake_find_gpu)


def test_gpu_list_without_region_lists_available_regions(home: Path, monkeypatch) -> None:
    """Omitting ``--region`` prints the catalogue without querying GPU stock."""
    _seed_token()
    monkeypatch.setattr(gpu_commands.gpu_handler, "list_regions", lambda client: GPU_REGIONS)
    monkeypatch.setattr(
        gpu_commands.gpu_handler,
        "list_gpu_availability",
        lambda *args, **kwargs: pytest.fail("the GPU endpoint must not run without --region"),
    )
    monkeypatch.setattr(output_module, "console", Console(width=120))

    result = CliRunner().invoke(main, ["gpu", "list"])

    assert result.exit_code == 0, result.output
    assert "Available regions" in result.output
    assert "西北B区" in result.output
    assert "westDC3" in result.output
    assert "west-B, west-C, west-D, west-E" in result.output
    assert "佛山区" in result.output
    assert "Pick a sign from the Signs column and pass it to -r/--region." in result.output
    assert TOKEN not in result.output


def test_gpu_list_without_region_json_returns_region_catalogue(home: Path, monkeypatch) -> None:
    """``--json`` without ``--region`` emits the grouped region catalogue."""
    _seed_token()
    monkeypatch.setattr(gpu_commands.gpu_handler, "list_regions", lambda client: GPU_REGIONS)
    monkeypatch.setattr(
        gpu_commands.gpu_handler,
        "list_gpu_availability",
        lambda *args, **kwargs: pytest.fail("the GPU endpoint must not run without --region"),
    )

    result = CliRunner().invoke(main, ["--json", "gpu", "list"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == GPU_REGIONS


def test_gpu_list_json_forwards_selection_and_returns_raw_result(home: Path, monkeypatch) -> None:
    """``--json`` emits the handler result and forwards identifiers and flags."""
    _seed_token()
    captured: dict[str, object] = {}
    _patch_gpu_handler(monkeypatch, captured)

    result = CliRunner().invoke(
        main,
        ["--json", "gpu", "list", "-r", "west-B", "-r", "佛山区", "--available"],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == GPU_AVAILABILITY
    assert [region["data_center"] for region in captured["regions"]] == ["westDC3", "foshanDC1"]
    assert captured["available_only"] is True
    assert TOKEN not in result.output


def test_gpu_list_human_output_shows_table(home: Path, monkeypatch) -> None:
    """The human view shows every column and a dash row for an empty region."""
    _seed_token()
    captured: dict[str, object] = {}
    _patch_gpu_handler(monkeypatch, captured)
    monkeypatch.setattr(output_module, "console", Console(width=120))

    result = CliRunner().invoke(main, ["gpu", "list", "-r", "west-B", "-r", "foshan-A"])

    assert result.exit_code == 0, result.output
    assert "GPU availability" in result.output
    for header in ("Region", "GPU", "Idle", "Total", "Chip"):
        assert header in result.output
    assert "西北B区" in result.output
    assert "A100" in result.output
    assert "RTX 4090" in result.output
    assert "5" in result.output
    assert "735" in result.output
    assert "nvidia" in result.output
    assert "佛山区" in result.output
    empty_region_line = next(line for line in result.output.splitlines() if "佛山区" in line)
    assert empty_region_line.count("-") >= 4
    assert TOKEN not in result.output


def test_gpu_list_unknown_region_is_a_clean_error(home: Path, monkeypatch) -> None:
    """An unknown identifier exits 1 and lists the known regions."""
    _seed_token()
    monkeypatch.setattr(gpu_commands.gpu_handler, "list_regions", lambda client: GPU_REGIONS)
    monkeypatch.setattr(
        gpu_commands.gpu_handler,
        "list_gpu_availability",
        lambda *args, **kwargs: pytest.fail("the GPU endpoint must not run for an unknown region"),
    )

    result = CliRunner().invoke(main, ["gpu", "list", "-r", "nowhere"])

    assert result.exit_code == 1
    assert "Known regions" in result.output
    assert "西北B区 (west-B, west-C, west-D, west-E)" in result.output
    assert "Traceback" not in result.output


def test_gpu_list_requires_token(home: Path, monkeypatch) -> None:
    """A missing token fails cleanly with the paste hint."""
    monkeypatch.setattr(
        gpu_commands.gpu_handler,
        "list_regions",
        lambda *args, **kwargs: pytest.fail("the handler must not run without a token"),
    )

    result = CliRunner().invoke(main, ["gpu", "list", "-r", "west-B"])

    assert result.exit_code == 1
    assert "autodl auth paste" in result.output
    assert "Traceback" not in result.output


def test_gpu_list_api_failure_is_a_clean_click_exception(home: Path, monkeypatch) -> None:
    """An API failure exits 1 without a traceback."""
    _seed_token()

    def failing_list_regions(client):
        raise AuthError("token expired")

    monkeypatch.setattr(gpu_commands.gpu_handler, "list_regions", failing_list_regions)

    result = CliRunner().invoke(main, ["gpu", "list", "-r", "west-B"])

    assert result.exit_code == 1
    assert "token expired" in result.output
    assert "Traceback" not in result.output


def test_find_without_region_searches_every_region(home: Path, monkeypatch) -> None:
    """Omitting ``--region`` searches every region and forwards model and flag."""
    _seed_token()
    captured: dict[str, object] = {}
    _patch_find_handler(monkeypatch, captured)

    result = CliRunner().invoke(main, ["--json", "gpu", "find", "4090", "--available"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == GPU_MATCHES
    assert [region["data_center"] for region in captured["regions"]] == ["westDC3", "foshanDC1"]
    assert captured["model"] == "4090"
    assert captured["available_only"] is True
    assert TOKEN not in result.output


def test_find_json_forwards_selected_regions(home: Path, monkeypatch) -> None:
    """``--region`` identifiers are resolved before the handler is called."""
    _seed_token()
    captured: dict[str, object] = {}
    _patch_find_handler(monkeypatch, captured)

    result = CliRunner().invoke(main, ["--json", "gpu", "find", "4090", "-r", "west-B"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == GPU_MATCHES
    assert [region["data_center"] for region in captured["regions"]] == ["westDC3"]
    assert captured["available_only"] is False


def test_find_human_output_shows_flat_matches(home: Path, monkeypatch) -> None:
    """The flat result is rendered with the region as a column."""
    _seed_token()
    captured: dict[str, object] = {}
    _patch_find_handler(monkeypatch, captured)
    monkeypatch.setattr(output_module, "console", Console(width=120))

    result = CliRunner().invoke(main, ["gpu", "find", "4090", "-r", "west-B"])

    assert result.exit_code == 0, result.output
    assert "Matching GPUs (2)" in result.output
    for header in ("Region", "GPU", "Idle", "Total", "Chip"):
        assert header in result.output
    assert "西北B区" in result.output
    assert "佛山区" in result.output
    assert "RTX 4090" in result.output
    assert "735" in result.output
    assert "nvidia" in result.output
    assert TOKEN not in result.output


def test_find_empty_result_prints_message(home: Path, monkeypatch) -> None:
    """No matches print a short message instead of an empty table."""
    _seed_token()
    monkeypatch.setattr(gpu_commands.gpu_handler, "list_regions", lambda client: GPU_REGIONS)
    monkeypatch.setattr(gpu_commands.gpu_handler, "find_gpu", lambda *args, **kwargs: [])

    result = CliRunner().invoke(main, ["gpu", "find", "H100"])

    assert result.exit_code == 0, result.output
    assert "No matching GPUs found." in result.output


def test_find_unknown_region_is_a_clean_error(home: Path, monkeypatch) -> None:
    """An unknown identifier exits 1 before any stock request is sent."""
    _seed_token()
    monkeypatch.setattr(gpu_commands.gpu_handler, "list_regions", lambda client: GPU_REGIONS)
    monkeypatch.setattr(
        gpu_commands.gpu_handler,
        "find_gpu",
        lambda *args, **kwargs: pytest.fail("the stock endpoint must not run for an unknown region"),
    )

    result = CliRunner().invoke(main, ["gpu", "find", "4090", "-r", "nowhere"])

    assert result.exit_code == 1
    assert "Known regions" in result.output
    assert "西北B区 (west-B, west-C, west-D, west-E)" in result.output
    assert "Traceback" not in result.output


def test_find_requires_token(home: Path, monkeypatch) -> None:
    """A missing token fails cleanly with the paste hint."""
    monkeypatch.setattr(
        gpu_commands.gpu_handler,
        "list_regions",
        lambda *args, **kwargs: pytest.fail("the handler must not run without a token"),
    )

    result = CliRunner().invoke(main, ["gpu", "find", "4090"])

    assert result.exit_code == 1
    assert "autodl auth paste" in result.output
    assert "Traceback" not in result.output


def test_find_api_failure_is_a_clean_click_exception(home: Path, monkeypatch) -> None:
    """An API failure exits 1 without a traceback."""
    _seed_token()

    def failing_find_gpu(client, regions, model, *, available_only=False):
        raise AuthError("token expired")

    monkeypatch.setattr(gpu_commands.gpu_handler, "list_regions", lambda client: GPU_REGIONS)
    monkeypatch.setattr(gpu_commands.gpu_handler, "find_gpu", failing_find_gpu)

    result = CliRunner().invoke(main, ["gpu", "find", "4090", "-r", "west-B"])

    assert result.exit_code == 1
    assert "token expired" in result.output
    assert "Traceback" not in result.output


MACHINE_PAGE = {
    "machines": [
        {
            "machine_id": "m1",
            "machine_name": "a***1",
            "machine_alias": "A03机",
            "region_name": "西北B区",
            "region_sign": "west-B",
            "gpu_name": "vGPU-32GB",
            "gpu_number": 8,
            "gpu_idle_num": 1,
            "gpu_used": 7,
            "gpu_memory": 34359738368,
            "chip_corp": "nvidia",
            "cpu_arch": "x86",
            "cpu_per_gpu": 12,
            "mem_per_gpu": 66571993088,
            "cpu_num": 96,
            "memory": 540642230272,
            "disk_size": 15360594018304,
            "max_instance_disk_size": 53687091200,
            "max_instance_num": 180,
            "binding_instance_num": 96,
            "highest_cuda_version": "13.0",
            "driver_version": "580.105.08",
            "disk_type": "SSD",
            "on_line": 2,
            "health_status": 0,
            "mount_net_disk": False,
            "enable_container_pro": True,
            "machine_tags": [],
            "payg_price": 1.66,
            "daily_price": 38.65,
            "weekly_price": 262.0,
            "monthly_price": 867.0,
            "yearly_price": 0.0,
            "description": "",
            "rent_deadline": "2027-10-01T00:00:00+08:00",
        }
    ],
    "page_index": 1,
    "page_size": 20,
    "max_page": 4,
    "result_total": 73,
    "all_pages": False,
}


def _patch_machines_handler(monkeypatch, captured: dict[str, object]) -> None:
    """Replace the machine handlers with offline fakes.

    :param monkeypatch: pytest's monkeypatch fixture.
    :param captured: Mapping filled with the arguments the command forwards.
    """

    def fake_list_machines(client, **kwargs):
        captured.update(kwargs)
        return MACHINE_PAGE

    monkeypatch.setattr(gpu_commands.gpu_handler, "list_regions", lambda client: GPU_REGIONS)
    monkeypatch.setattr(gpu_commands.gpu_handler, "list_machines", fake_list_machines)


def test_machines_json_forwards_full_filter_set(home: Path, monkeypatch) -> None:
    """Every option is forwarded and the handler result is emitted as JSON."""
    _seed_token()
    captured: dict[str, object] = {}
    _patch_machines_handler(monkeypatch, captured)

    result = CliRunner().invoke(
        main,
        [
            "--json",
            "gpu",
            "machines",
            "-r",
            "west-B",
            "-r",
            "佛山区",
            "-g",
            "RTX 4090",
            "-t",
            "tag-a",
            "--idle",
            "2",
            "--charge-type",
            "daily",
            "--chip",
            "nvidia",
            "--cpu-arch",
            "x86",
            "--mount-net-disk",
            "--machine-id",
            "m9",
            "--date-range",
            "custom",
            "--date-from",
            "2026-11-01",
            "--date-to",
            "2026-11-02",
            "--sort",
            "price",
            "--order",
            "desc",
            "--page",
            "2",
            "--page-size",
            "5",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == MACHINE_PAGE
    assert captured == {
        "charge_type": "daily",
        "region_signs": ["west-B", "west-C", "west-D", "west-E", "foshan-A"],
        "gpu_types": ("RTX 4090",),
        "machine_tags": ("tag-a",),
        "gpu_idle_num": 2,
        "mount_net_disk": True,
        "cpu_archs": ("x86",),
        "chip_corps": ("nvidia",),
        "machine_id": "m9",
        "date_range": "custom",
        "date_from": "2026-11-01",
        "date_to": "2026-11-02",
        "sort_field": "price",
        "sort_order": "desc",
        "page_index": 2,
        "page_size": 5,
        "all_pages": False,
    }
    assert TOKEN not in result.output


def test_machines_defaults_without_region_or_sort(home: Path, monkeypatch) -> None:
    """Omitting ``--region`` searches everywhere and leaves sort ordering default."""
    _seed_token()
    captured: dict[str, object] = {}
    _patch_machines_handler(monkeypatch, captured)

    result = CliRunner().invoke(main, ["--json", "gpu", "machines"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == MACHINE_PAGE
    assert captured["region_signs"] == []
    assert captured["charge_type"] == "payg"
    assert captured["gpu_idle_num"] == 1
    assert captured["sort_field"] is None
    assert captured["sort_order"] == "asc"
    assert captured["page_index"] == 1
    assert captured["page_size"] == gpu_commands.gpu_handler.DEFAULT_MACHINE_PAGE_SIZE
    assert captured["all_pages"] is False


def test_machines_all_fetches_every_page(home: Path, monkeypatch) -> None:
    """``--all`` is forwarded as ``all_pages``."""
    _seed_token()
    captured: dict[str, object] = {}
    _patch_machines_handler(monkeypatch, captured)

    result = CliRunner().invoke(main, ["--json", "gpu", "machines", "--all"])

    assert result.exit_code == 0, result.output
    assert captured["all_pages"] is True
    assert captured["page_index"] == 1


def test_machines_page_with_all_is_a_usage_error(home: Path, monkeypatch) -> None:
    """Combining ``--page`` with ``--all`` is rejected before any request."""
    monkeypatch.setattr(
        gpu_commands.gpu_handler,
        "list_machines",
        lambda *args, **kwargs: pytest.fail("the handler must not run for a usage error"),
    )

    result = CliRunner().invoke(main, ["gpu", "machines", "--all", "--page", "2"])

    assert result.exit_code == 2
    assert "--page cannot be combined with --all" in result.output
    assert "Traceback" not in result.output


def test_machines_human_output_shows_table_and_page_footer(home: Path, monkeypatch) -> None:
    """The human view shows the machine columns and pagination summary."""
    _seed_token()
    captured: dict[str, object] = {}
    _patch_machines_handler(monkeypatch, captured)
    monkeypatch.setattr(output_module, "console", Console(width=120))

    result = CliRunner().invoke(main, ["gpu", "machines"])

    assert result.exit_code == 0, result.output
    assert "GPU machines (1)" in result.output
    for header in ("Region", "Machine", "GPU", "Idle", "¥/h", "¥/day", "CPU/RAM", "Disk", "CUDA"):
        assert header in result.output
    for value in (
        "西北B区",
        "west-B",
        "A03机",
        "m1",
        "vGPU-32GB",
        "1/8",
        "¥1.660",
        "¥38.650",
        "12c/62G",
        "50G",
        "13.0",
    ):
        assert value in result.output
    assert "Page 1/4 · 73 machines" in result.output
    assert TOKEN not in result.output


def test_machines_all_human_output_reports_every_page(home: Path, monkeypatch) -> None:
    """The footer changes when every page was fetched."""
    _seed_token()
    page = dict(MACHINE_PAGE, all_pages=True)
    monkeypatch.setattr(gpu_commands.gpu_handler, "list_regions", lambda client: GPU_REGIONS)
    monkeypatch.setattr(gpu_commands.gpu_handler, "list_machines", lambda client, **kwargs: page)
    monkeypatch.setattr(output_module, "console", Console(width=120))

    result = CliRunner().invoke(main, ["gpu", "machines", "--all"])

    assert result.exit_code == 0, result.output
    assert "Showing every page (73 machines)." in result.output


def test_machines_empty_result_prints_message(home: Path, monkeypatch) -> None:
    """No matching machines print a short message instead of an empty table."""
    _seed_token()
    page = dict(MACHINE_PAGE, machines=[])
    monkeypatch.setattr(gpu_commands.gpu_handler, "list_regions", lambda client: GPU_REGIONS)
    monkeypatch.setattr(gpu_commands.gpu_handler, "list_machines", lambda client, **kwargs: page)

    result = CliRunner().invoke(main, ["gpu", "machines"])

    assert result.exit_code == 0, result.output
    assert "No matching machines found." in result.output


def test_machines_unknown_region_is_a_clean_error(home: Path, monkeypatch) -> None:
    """An unknown identifier exits 1 and lists the known regions."""
    _seed_token()
    monkeypatch.setattr(gpu_commands.gpu_handler, "list_regions", lambda client: GPU_REGIONS)
    monkeypatch.setattr(
        gpu_commands.gpu_handler,
        "list_machines",
        lambda *args, **kwargs: pytest.fail("the machine endpoint must not run for an unknown region"),
    )

    result = CliRunner().invoke(main, ["gpu", "machines", "-r", "nowhere"])

    assert result.exit_code == 1
    assert "Known regions" in result.output
    assert "西北B区 (west-B, west-C, west-D, west-E)" in result.output
    assert "Traceback" not in result.output


def test_machines_requires_token(home: Path, monkeypatch) -> None:
    """A missing token fails cleanly with the paste hint."""
    monkeypatch.setattr(
        gpu_commands.gpu_handler,
        "list_machines",
        lambda *args, **kwargs: pytest.fail("the handler must not run without a token"),
    )

    result = CliRunner().invoke(main, ["gpu", "machines"])

    assert result.exit_code == 1
    assert "autodl auth paste" in result.output
    assert "Traceback" not in result.output


def test_machines_api_failure_is_a_clean_click_exception(home: Path, monkeypatch) -> None:
    """An API failure exits 1 without a traceback."""
    _seed_token()

    def failing_list_machines(client, **kwargs):
        raise AuthError("token expired")

    monkeypatch.setattr(gpu_commands.gpu_handler, "list_regions", lambda client: GPU_REGIONS)
    monkeypatch.setattr(gpu_commands.gpu_handler, "list_machines", failing_list_machines)

    result = CliRunner().invoke(main, ["gpu", "machines"])

    assert result.exit_code == 1
    assert "token expired" in result.output
    assert "Traceback" not in result.output


def test_machines_narrow_output_stacks_details_without_truncation(home: Path, monkeypatch) -> None:
    """A narrow terminal stacks every field instead of ellipsising cells."""
    _seed_token()
    captured: dict[str, object] = {}
    _patch_machines_handler(monkeypatch, captured)
    monkeypatch.setattr(output_module, "console", Console(width=60))

    result = CliRunner().invoke(main, ["gpu", "machines"])

    assert result.exit_code == 0, result.output
    assert "GPU machines (1)" in result.output
    for value in ("西北B区 (west-B)", "A03机 (m1)", "vGPU-32GB ×8", "Idle 1/8", "CUDA 13.0", "¥1.660/h", "12c/62G"):
        assert value in result.output
    assert "…" not in result.output
    assert "Page 1/4 · 73 machines" in result.output
