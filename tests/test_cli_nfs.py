"""Tests for ``autodl nfs`` commands through the real Click entry point."""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path

import pytest
from click.testing import CliRunner

from autodl_cli import config as config_module
from autodl_cli import output as output_module
from autodl_cli.commands import nfs as nfs_commands
from autodl_cli.errors import APIError
from autodl_cli.main import main

TOKEN = "fake-token"

REGIONS = [
    {
        "sign": "bj-B1",
        "name": "北京B区",
        "status": "created",
        "export_addr": "region-bjb1-fs-2.autodl.com",
        "port": 7007,
        "fs_type": "autofs",
        "default_size": 214748364800,
        "free_size": 21474836480,
        "max_size": 54975581388800,
    }
]

LISTING = {
    "region": "bj-B1",
    "dir_path": "/data",
    "entries": [
        {"name": "notes.txt", "size": 2035, "updated_at": "2026-10-31T19:58:19.788Z", "is_dir": False},
        {"name": "datasets", "size": 4096, "updated_at": "0001-01-01T00:00:00Z", "is_dir": True},
    ],
}

DELETE_RESULT = {
    "region": "bj-B1",
    "region_name": "北京B区",
    "dir_path": "/data",
    "filename": "notes.txt",
    "remote_path": "/data/notes.txt",
    "deleted": True,
}

UPLOAD_RESULT = {
    "region": "bj-B1",
    "region_name": "北京B区",
    "dir_path": "/data",
    "filename": "renamed.txt",
    "remote_path": "/data/renamed.txt",
    "size": 9,
    "chunks": 1,
    "file_uuid": "1793476699563",
    "md5": "842dd44fde7f0201f90460d2acd4b283",
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
    """Store a token so a command can run."""
    config_module.save_config({"token": TOKEN})


def _patch(monkeypatch, name: str, value: object) -> None:
    """Replace one handler function on the nfs command module.

    :param monkeypatch: pytest's monkeypatch fixture.
    :param name: Handler function name.
    :param value: Replacement callable.
    """
    monkeypatch.setattr(nfs_commands.nfs_handler, name, value)


@contextmanager
def _no_progress(filename: str, total: int):
    """Stand-in for the Rich progress bar.

    :param filename: File name, ignored.
    :param total: File size, ignored.
    :yields: A no-op update callback.
    """
    yield lambda sent: None


def test_regions_json(home: Path, monkeypatch) -> None:
    """``--json`` emits the normalised region list."""
    _seed_token()
    _patch(monkeypatch, "list_regions", lambda client: REGIONS)

    result = CliRunner().invoke(main, ["--json", "nfs", "regions"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == REGIONS


def test_regions_human_table(home: Path, monkeypatch) -> None:
    """The default output is a table naming the region and its sign."""
    _seed_token()
    _patch(monkeypatch, "list_regions", lambda client: REGIONS)

    result = CliRunner().invoke(main, ["nfs", "regions"])

    assert result.exit_code == 0, result.output
    assert "北京B区" in result.output
    assert "bj-B1" in result.output
    assert "created" in result.output


def test_regions_without_token_fails_with_hint(home: Path) -> None:
    """An unauthenticated run explains how to authenticate."""
    result = CliRunner().invoke(main, ["nfs", "regions"])

    assert result.exit_code == 1
    assert "autodl auth paste" in result.output


def test_ls_passes_region_and_path(home: Path, monkeypatch) -> None:
    """The region and the directory reach the handler unchanged."""
    _seed_token()
    captured: dict[str, object] = {}

    def fake_list_files(client, *, region: str, dir_path: str):
        captured.update(region=region, dir_path=dir_path)
        return LISTING

    _patch(monkeypatch, "list_files", fake_list_files)

    result = CliRunner().invoke(main, ["--json", "nfs", "ls", "/data/", "--region", "bj-B1"])

    assert result.exit_code == 0, result.output
    assert captured == {"region": "bj-B1", "dir_path": "/data/"}
    assert json.loads(result.output) == LISTING


def test_ls_defaults_to_the_root(home: Path, monkeypatch) -> None:
    """The path argument is optional and defaults to ``/``."""
    _seed_token()
    captured: dict[str, object] = {}

    def fake_list_files(client, *, region: str, dir_path: str):
        captured.update(region=region, dir_path=dir_path)
        return LISTING

    _patch(monkeypatch, "list_files", fake_list_files)

    result = CliRunner().invoke(main, ["nfs", "ls", "--region", "bj-B1"])

    assert result.exit_code == 0, result.output
    assert captured["dir_path"] == "/"
    assert "notes.txt" in result.output
    assert "datasets/" in result.output


def test_ls_requires_a_region(home: Path, monkeypatch) -> None:
    """Region selection is mandatory."""
    _seed_token()
    _patch(monkeypatch, "list_files", lambda *args, **kwargs: pytest.fail("handler must not run"))

    result = CliRunner().invoke(main, ["nfs", "ls"])

    assert result.exit_code == 2
    assert "--region" in result.output


def test_rm_yes_skips_confirmation_and_renders_success(home: Path, monkeypatch) -> None:
    """``--yes`` deletes immediately and names the remote path."""
    _seed_token()
    captured: dict[str, object] = {}

    def fake_delete(client, remote_path, *, region):
        captured.update(remote_path=remote_path, region=region)
        return DELETE_RESULT

    _patch(monkeypatch, "delete_file", fake_delete)

    result = CliRunner().invoke(main, ["nfs", "rm", "/data/notes.txt", "--region", "bj-B1", "--yes"])

    assert result.exit_code == 0, result.output
    assert captured == {"remote_path": "/data/notes.txt", "region": "bj-B1"}
    assert "Deleted /data/notes.txt (region bj-B1)." in result.output


def test_rm_prompts_and_aborts_when_declined(home: Path, monkeypatch) -> None:
    """Declining the prompt leaves the file alone."""
    _seed_token()
    _patch(monkeypatch, "delete_file", lambda *args, **kwargs: pytest.fail("handler must not run"))

    result = CliRunner().invoke(
        main,
        ["nfs", "rm", "/data/notes.txt", "--region", "bj-B1"],
        input="n\n",
    )

    assert result.exit_code == 1
    assert "Delete /data/notes.txt from NFS region bj-B1?" in result.output
    assert "Aborted" in result.output


def test_rm_proceeds_when_confirmed(home: Path, monkeypatch) -> None:
    """Answering ``y`` deletes the file."""
    _seed_token()
    _patch(monkeypatch, "delete_file", lambda *args, **kwargs: DELETE_RESULT)

    result = CliRunner().invoke(
        main,
        ["nfs", "rm", "/data/notes.txt", "--region", "bj-B1"],
        input="y\n",
    )

    assert result.exit_code == 0, result.output
    assert "Deleted /data/notes.txt" in result.output


def test_rm_json(home: Path, monkeypatch) -> None:
    """``--json`` emits the deletion result."""
    _seed_token()
    _patch(monkeypatch, "delete_file", lambda *args, **kwargs: DELETE_RESULT)

    result = CliRunner().invoke(main, ["--json", "nfs", "rm", "/data/notes.txt", "--region", "bj-B1", "--yes"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == DELETE_RESULT


def test_rm_requires_a_region(home: Path, monkeypatch) -> None:
    """Region selection is mandatory."""
    _seed_token()
    _patch(monkeypatch, "delete_file", lambda *args, **kwargs: pytest.fail("handler must not run"))

    result = CliRunner().invoke(main, ["nfs", "rm", "/data/notes.txt", "--yes"])

    assert result.exit_code == 2
    assert "--region" in result.output


def test_rm_value_errors_become_click_exceptions(home: Path, monkeypatch) -> None:
    """An invalid path is reported without a traceback."""
    _seed_token()

    def fail(*args, **kwargs):
        raise ValueError("Refusing to delete the NFS root directory")

    _patch(monkeypatch, "delete_file", fail)

    result = CliRunner().invoke(main, ["nfs", "rm", "/", "--region", "bj-B1", "--yes"])

    assert result.exit_code == 1
    assert "root directory" in result.output
    assert "Traceback" not in result.output


def test_upload_passes_options_and_renders_summary(home: Path, monkeypatch, tmp_path: Path) -> None:
    """Upload options reach the handler and the summary names the remote path."""
    _seed_token()
    source = tmp_path / "sample.txt"
    source.write_bytes(b"hello nfs")
    captured: dict[str, object] = {}

    def fake_upload(client, local_path, *, region, dir_path, filename, on_progress=None):
        captured.update(
            local_path=local_path,
            region=region,
            dir_path=dir_path,
            filename=filename,
            progress=on_progress is not None,
        )
        return UPLOAD_RESULT

    _patch(monkeypatch, "upload_file", fake_upload)
    monkeypatch.setattr(output_module, "upload_progress", _no_progress)

    result = CliRunner().invoke(
        main,
        [
            "nfs",
            "upload",
            str(source),
            "--region",
            "bj-B1",
            "--dir-path",
            "/data",
            "--filename",
            "renamed.txt",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured == {
        "local_path": source,
        "region": "bj-B1",
        "dir_path": "/data",
        "filename": "renamed.txt",
        "progress": True,
    }
    assert "Uploaded" in result.output
    assert "/data/renamed.txt" in result.output


def test_upload_json_skips_progress_and_prints_result(home: Path, monkeypatch, tmp_path: Path) -> None:
    """``--json`` does not start a progress bar and emits the result."""
    _seed_token()
    source = tmp_path / "sample.txt"
    source.write_bytes(b"hello nfs")

    _patch(monkeypatch, "upload_file", lambda *args, **kwargs: UPLOAD_RESULT)
    monkeypatch.setattr(
        output_module,
        "upload_progress",
        lambda *args, **kwargs: pytest.fail("progress must not start in JSON mode"),
    )

    result = CliRunner().invoke(main, ["--json", "nfs", "upload", str(source), "--region", "bj-B1"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == UPLOAD_RESULT


def test_upload_requires_a_region(home: Path, monkeypatch, tmp_path: Path) -> None:
    """Upload cannot guess which regional volume to use."""
    _seed_token()
    source = tmp_path / "sample.txt"
    source.write_bytes(b"hello nfs")
    _patch(monkeypatch, "upload_file", lambda *args, **kwargs: pytest.fail("handler must not run"))

    result = CliRunner().invoke(main, ["nfs", "upload", str(source)])

    assert result.exit_code == 2
    assert "--region" in result.output


def test_upload_missing_local_file_is_a_usage_error(home: Path) -> None:
    """Click rejects a path that does not exist before the handler runs."""
    _seed_token()

    result = CliRunner().invoke(main, ["nfs", "upload", "/definitely/not/here", "--region", "bj-B1"])

    assert result.exit_code == 2
    assert "does not exist" in result.output


def test_handler_errors_become_click_exceptions(home: Path, monkeypatch) -> None:
    """API failures are reported without a traceback."""
    _seed_token()

    def fail(client):
        raise APIError("AutoDL API returned HTTP 401")

    _patch(monkeypatch, "list_regions", fail)

    result = CliRunner().invoke(main, ["nfs", "regions"])

    assert result.exit_code == 1
    assert "HTTP 401" in result.output
    assert "Traceback" not in result.output


def test_upload_value_errors_become_click_exceptions(home: Path, monkeypatch, tmp_path: Path) -> None:
    """Local validation failures are reported without a traceback."""
    _seed_token()
    source = tmp_path / "sample.txt"
    source.write_bytes(b"hello nfs")

    def fail(*args, **kwargs):
        raise ValueError("Remote filename must be a plain file name")

    _patch(monkeypatch, "upload_file", fail)
    monkeypatch.setattr(output_module, "upload_progress", _no_progress)

    result = CliRunner().invoke(main, ["nfs", "upload", str(source), "--region", "bj-B1"])

    assert result.exit_code == 1
    assert "plain file name" in result.output
    assert "Traceback" not in result.output
