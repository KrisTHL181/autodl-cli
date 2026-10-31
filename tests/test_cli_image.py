"""Tests for ``autodl image`` commands through the real Click entry point."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from rich.console import Console

from autodl_cli import config as config_module
from autodl_cli import output as output_module
from autodl_cli.commands import image as image_commands
from autodl_cli.errors import AuthError
from autodl_cli.main import main

TOKEN = "fake-token"

IMAGES = [
    {
        "framework_name": "PyTorch",
        "framework_version": "2.12.1",
        "python_version": "3.12(ubuntu22.04)",
        "cuda_version": "13.0",
        "image_uuid": "base-image-ee43618uo7",
        "chip_corp": "nvidia",
        "cpu_arch": "x86",
        "is_desktop": False,
    },
    {
        "framework_name": "Miniconda",
        "framework_version": "conda3",
        "python_version": "3.8(ubuntu18.04)",
        "cuda_version": "11.3",
        "image_uuid": "base-image-7bn8iqhkb5",
        "chip_corp": "nvidia",
        "cpu_arch": "x86",
        "is_desktop": False,
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
    """Store a token so the image commands can run."""
    config_module.save_config({"token": TOKEN})


def _patch_handler(monkeypatch, captured: dict[str, object], images: list[dict[str, object]] | None = None) -> None:
    """Replace the image handler with an offline fake.

    :param monkeypatch: pytest's monkeypatch fixture.
    :param captured: Mapping filled with the arguments the command forwards.
    :param images: Result to return; defaults to :data:`IMAGES`.
    """

    def fake_list_images(client, **filters):
        captured.update(filters)
        return IMAGES if images is None else images

    monkeypatch.setattr(image_commands.image_handler, "list_images", fake_list_images)


def test_image_list_human_output_shows_table(home: Path, monkeypatch) -> None:
    """The human view shows every column and the image UUIDs."""
    _seed_token()
    captured: dict[str, object] = {}
    _patch_handler(monkeypatch, captured)
    monkeypatch.setattr(output_module, "console", Console(width=160))

    result = CliRunner().invoke(main, ["image", "list"])

    assert result.exit_code == 0, result.output
    assert "Base images (2)" in result.output
    for header in ("Image", "Python", "CUDA", "Chip", "Arch", "UUID"):
        assert header in result.output
    assert "PyTorch 2.12.1" in result.output
    assert "3.12(ubuntu22.04)" in result.output
    assert "13.0" in result.output
    assert "nvidia" in result.output
    assert "x86" in result.output
    assert "base-image-ee43618uo7" in result.output
    assert "Miniconda conda3" in result.output
    assert TOKEN not in result.output


def test_image_list_stacks_fields_on_a_narrow_terminal(home: Path, monkeypatch) -> None:
    """A narrow terminal gets the stacked details instead of a truncated table."""
    _seed_token()
    captured: dict[str, object] = {}
    _patch_handler(monkeypatch, captured)
    monkeypatch.setattr(output_module, "console", Console(width=60))

    result = CliRunner().invoke(main, ["image", "list"])

    assert result.exit_code == 0, result.output
    assert "Details" in result.output
    assert "PyTorch 2.12.1" in result.output
    assert "Python 3.12(ubuntu22.04) · CUDA 13.0" in result.output
    assert "nvidia · x86 · base-image-ee43618uo7" in result.output
    assert TOKEN not in result.output


def test_image_list_json_returns_the_handler_result(home: Path, monkeypatch) -> None:
    """``--json`` emits the flat image list untouched."""
    _seed_token()
    captured: dict[str, object] = {}
    _patch_handler(monkeypatch, captured)

    result = CliRunner().invoke(main, ["--json", "image", "list"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == IMAGES
    assert TOKEN not in result.output


def test_image_list_forwards_every_filter(home: Path, monkeypatch) -> None:
    """Each CLI filter is forwarded to the handler under its handler name."""
    _seed_token()
    captured: dict[str, object] = {}
    _patch_handler(monkeypatch, captured)

    result = CliRunner().invoke(
        main,
        [
            "--json",
            "image",
            "list",
            "-f",
            "torch",
            "--framework-version",
            "2.12",
            "--python",
            "3.12",
            "--cuda",
            "13",
            "--chip",
            "nvidia",
            "--cpu-arch",
            "x86",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured == {
        "frameworks": ("torch",),
        "framework_versions": ("2.12",),
        "python_versions": ("3.12",),
        "cuda_versions": ("13",),
        "chip_corps": ("nvidia",),
        "cpu_archs": ("x86",),
    }


def test_image_list_empty_filter_is_a_clean_error(home: Path, monkeypatch) -> None:
    """A filter rejected by the handler exits 1 without a traceback."""
    _seed_token()

    def failing_list_images(client, **filters):
        raise ValueError("framework filter must not be empty")

    monkeypatch.setattr(image_commands.image_handler, "list_images", failing_list_images)

    result = CliRunner().invoke(main, ["image", "list", "-f", " "])

    assert result.exit_code == 1
    assert "framework filter must not be empty" in result.output
    assert "Traceback" not in result.output


def test_image_list_no_matches_reports_cleanly(home: Path, monkeypatch) -> None:
    """An empty result prints a hint instead of an empty table."""
    _seed_token()
    captured: dict[str, object] = {}
    _patch_handler(monkeypatch, captured, images=[])

    result = CliRunner().invoke(main, ["image", "list", "-f", "nowhere"])

    assert result.exit_code == 0, result.output
    assert "No images found." in result.output
    assert "Base images" not in result.output


def test_image_list_requires_token(home: Path, monkeypatch) -> None:
    """A missing token fails cleanly with the paste hint."""
    monkeypatch.setattr(
        image_commands.image_handler,
        "list_images",
        lambda *args, **kwargs: pytest.fail("the handler must not run without a token"),
    )

    result = CliRunner().invoke(main, ["image", "list"])

    assert result.exit_code == 1
    assert "autodl auth paste" in result.output
    assert "Traceback" not in result.output


def test_image_list_api_failure_is_a_clean_click_exception(home: Path, monkeypatch) -> None:
    """An API failure exits 1 without a traceback."""
    _seed_token()

    def failing_list_images(client, **filters):
        raise AuthError("token expired")

    monkeypatch.setattr(image_commands.image_handler, "list_images", failing_list_images)

    result = CliRunner().invoke(main, ["image", "list"])

    assert result.exit_code == 1
    assert "token expired" in result.output
    assert "Traceback" not in result.output
