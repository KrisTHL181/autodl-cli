"""Tests for ``autodl nfs`` commands through the real Click entry point."""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path

import pytest
from click.testing import CliRunner
from rich.console import Console

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

DELETE_DIRECTORY_RESULT = {
    "region": "bj-B1",
    "region_name": "北京B区",
    "dir_path": "/data",
    "dir_name": "old",
    "remote_path": "/data/old",
    "deleted": True,
}

DF_ROWS = [
    {
        "sign": "bj-B1",
        "name": "北京B区",
        "status": "created",
        "total_space": 214748364800,
        "used_space": 16305467392,
        "free_space": 198442897408,
        "used_percent": 7.6,
        "total_inodes": 200000,
        "used_inodes": 46,
        "free_inodes": 199954,
        "free_allowance": 21474836480,
        "max_size": 54975581388800,
        "usage_error": None,
    }
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


@contextmanager
def _no_download_progress(filename: str):
    """Stand-in for the download progress bar.

    :param filename: File name, ignored.
    :yields: A no-op update callback.
    """
    yield lambda written, total: None


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


def test_rm_recursive_sends_the_directory_body(home: Path, monkeypatch) -> None:
    """``-r --yes`` deletes the directory without a prompt."""
    _seed_token()
    captured: dict[str, object] = {}

    def fake_delete_directory(client, remote_path, *, region):
        captured.update(remote_path=remote_path, region=region)
        return DELETE_DIRECTORY_RESULT

    _patch(monkeypatch, "delete_directory", fake_delete_directory)
    _patch(monkeypatch, "delete_file", lambda *args, **kwargs: pytest.fail("file delete must not run"))

    result = CliRunner().invoke(main, ["nfs", "rm", "/data/old", "--region", "bj-B1", "-r", "--yes"])

    assert result.exit_code == 0, result.output
    assert captured == {"remote_path": "/data/old", "region": "bj-B1"}
    assert "Deleted directory /data/old and its contents (region bj-B1)." in result.output


def test_rm_recursive_prompts_with_the_directory_warning(home: Path, monkeypatch) -> None:
    """The recursive confirmation mentions the contents."""
    _seed_token()
    _patch(monkeypatch, "delete_directory", lambda *args, **kwargs: pytest.fail("handler must not run"))

    result = CliRunner().invoke(
        main,
        ["nfs", "rm", "/data/old", "--region", "bj-B1", "-r"],
        input="n\n",
    )

    assert result.exit_code == 1
    assert "Delete directory /data/old and its contents from NFS region bj-B1?" in result.output
    assert "Aborted" in result.output


def test_rm_without_recursive_still_uses_the_file_endpoint(home: Path, monkeypatch) -> None:
    """The default ``rm`` keeps deleting a single file."""
    _seed_token()
    _patch(monkeypatch, "delete_file", lambda *args, **kwargs: DELETE_RESULT)
    _patch(monkeypatch, "delete_directory", lambda *args, **kwargs: pytest.fail("directory delete must not run"))

    result = CliRunner().invoke(main, ["nfs", "rm", "/data/notes.txt", "--region", "bj-B1", "--yes"])

    assert result.exit_code == 0, result.output
    assert "Deleted /data/notes.txt (region bj-B1)." in result.output


def test_download_writes_the_file_and_renders_summary(home: Path, monkeypatch, tmp_path: Path) -> None:
    """The destination receives the bytes and the summary names both paths."""
    _seed_token()
    target = tmp_path / "notes.txt"
    captured: dict[str, object] = {}

    def fake_download(client, remote_path, *, region, local_path, overwrite, on_progress=None):
        captured.update(
            remote_path=remote_path,
            region=region,
            local_path=local_path,
            overwrite=overwrite,
            progress=on_progress is not None,
        )
        Path(local_path).write_bytes(b"hello nfs")
        return {
            "region": region,
            "region_name": "北京B区",
            "dir_path": "/data",
            "filename": "notes.txt",
            "remote_path": "/data/notes.txt",
            "local_path": str(local_path),
            "size": 9,
            "total": 9,
        }

    _patch(monkeypatch, "download_file", fake_download)
    monkeypatch.setattr(output_module, "download_progress", _no_download_progress)

    result = CliRunner().invoke(
        main,
        ["nfs", "download", "/data/notes.txt", "--region", "bj-B1", "-o", str(target)],
    )

    assert result.exit_code == 0, result.output
    assert target.read_bytes() == b"hello nfs"
    assert captured == {
        "remote_path": "/data/notes.txt",
        "region": "bj-B1",
        "local_path": target,
        "overwrite": False,
        "progress": True,
    }
    assert "Downloaded" in result.output
    assert str(target) in result.output


def test_download_output_directory_keeps_the_remote_name(home: Path, monkeypatch, tmp_path: Path) -> None:
    """An existing ``--output`` directory receives the remote file name."""
    _seed_token()
    destination = tmp_path / "out"
    destination.mkdir()
    captured: dict[str, object] = {}

    def fake_download(client, remote_path, *, region, local_path, overwrite, on_progress=None):
        captured["local_path"] = local_path
        Path(local_path).write_bytes(b"x")
        return {
            "region": region,
            "filename": "notes.txt",
            "local_path": str(local_path),
            "remote_path": remote_path,
            "size": 1,
        }

    _patch(monkeypatch, "download_file", fake_download)
    monkeypatch.setattr(output_module, "download_progress", _no_download_progress)

    result = CliRunner().invoke(
        main,
        ["nfs", "download", "/data/notes.txt", "--region", "bj-B1", "--output", str(destination)],
    )

    assert result.exit_code == 0, result.output
    assert captured["local_path"] == destination / "notes.txt"
    assert (destination / "notes.txt").read_bytes() == b"x"


def test_download_json_skips_progress_and_prints_result(home: Path, monkeypatch, tmp_path: Path) -> None:
    """``--json`` emits the handler result without starting a progress bar."""
    _seed_token()
    target = tmp_path / "notes.txt"
    result_payload = {
        "region": "bj-B1",
        "region_name": "北京B区",
        "dir_path": "/data",
        "filename": "notes.txt",
        "remote_path": "/data/notes.txt",
        "local_path": str(target),
        "size": 9,
        "total": 9,
    }
    _patch(monkeypatch, "download_file", lambda *args, **kwargs: result_payload)
    monkeypatch.setattr(
        output_module,
        "download_progress",
        lambda *args, **kwargs: pytest.fail("progress must not start in JSON mode"),
    )

    result = CliRunner().invoke(
        main,
        ["--json", "nfs", "download", "/data/notes.txt", "--region", "bj-B1", "-o", str(target)],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == result_payload


def test_download_value_errors_become_click_exceptions(home: Path, monkeypatch, tmp_path: Path) -> None:
    """Local validation failures are reported without a traceback."""
    _seed_token()
    target = tmp_path / "notes.txt"

    def fail(*args, **kwargs):
        raise ValueError("Local file already exists")

    _patch(monkeypatch, "download_file", fail)
    monkeypatch.setattr(output_module, "download_progress", _no_download_progress)

    result = CliRunner().invoke(
        main,
        ["nfs", "download", "/data/notes.txt", "--region", "bj-B1", "-o", str(target)],
    )

    assert result.exit_code == 1
    assert "already exists" in result.output
    assert "Traceback" not in result.output


def test_download_existing_file_without_force_fails_before_any_call(home: Path, monkeypatch, tmp_path: Path) -> None:
    """The CLI refuses an existing destination and points at ``--force``."""
    _seed_token()
    target = tmp_path / "notes.txt"
    target.write_bytes(b"keep me")
    _patch(monkeypatch, "download_file", lambda *args, **kwargs: pytest.fail("handler must not run"))
    monkeypatch.setattr(
        output_module,
        "download_progress",
        lambda *args, **kwargs: pytest.fail("progress must not start"),
    )

    result = CliRunner().invoke(
        main,
        ["nfs", "download", "/data/notes.txt", "--region", "bj-B1", "-o", str(target)],
    )

    assert result.exit_code == 1
    assert f"Local file already exists: {target} (pass --force to replace it)" in result.output
    assert target.read_bytes() == b"keep me"


def test_download_force_passes_overwrite_to_the_handler(home: Path, monkeypatch, tmp_path: Path) -> None:
    """``--force`` bypasses the CLI pre-check and sets ``overwrite``."""
    _seed_token()
    target = tmp_path / "notes.txt"
    target.write_bytes(b"old")
    captured: dict[str, object] = {}

    def fake_download(client, remote_path, *, region, local_path, overwrite, on_progress=None):
        captured["overwrite"] = overwrite
        Path(local_path).write_bytes(b"new")
        return {
            "region": region,
            "filename": "notes.txt",
            "local_path": str(local_path),
            "remote_path": remote_path,
            "size": 3,
        }

    _patch(monkeypatch, "download_file", fake_download)
    monkeypatch.setattr(output_module, "download_progress", _no_download_progress)

    result = CliRunner().invoke(
        main,
        ["nfs", "download", "/data/notes.txt", "--region", "bj-B1", "-o", str(target), "--force"],
    )

    assert result.exit_code == 0, result.output
    assert captured == {"overwrite": True}
    assert target.read_bytes() == b"new"


def test_df_human_table(home: Path, monkeypatch) -> None:
    """``df`` renders live usage columns and passes the region filter through."""
    _seed_token()
    captured: dict[str, object] = {}

    def fake_usage(client, *, region=None):
        captured["region"] = region
        return DF_ROWS

    _patch(monkeypatch, "storage_usage", fake_usage)
    monkeypatch.setattr(output_module, "console", Console(width=140, highlight=False))

    result = CliRunner().invoke(main, ["nfs", "df", "--region", "bj-B1"])

    assert result.exit_code == 0, result.output
    assert captured == {"region": "bj-B1"}
    assert "北京B区" in result.output
    assert "bj-B1" in result.output
    for header in ("Region", "Sign", "Status", "Total", "Used", "Free", "Use%", "Inodes", "Max"):
        assert header in result.output
    assert "7.6%" in result.output
    assert "46 / 200000" in result.output


def test_df_warns_when_one_detail_call_fails(home: Path, monkeypatch) -> None:
    """A failed detail call is shown as unavailable after the table."""
    _seed_token()
    unavailable = {
        **DF_ROWS[0],
        "total_space": None,
        "used_space": None,
        "free_space": None,
        "used_percent": None,
        "total_inodes": None,
        "used_inodes": None,
        "free_inodes": None,
        "usage_error": "detail exploded",
    }
    uninitialised = {
        "sign": "west-X",
        "name": "西北企业区",
        "status": "uninitialized",
        "total_space": None,
        "used_space": None,
        "free_space": None,
        "used_percent": None,
        "total_inodes": None,
        "used_inodes": None,
        "free_inodes": None,
        "free_allowance": 21474836480,
        "max_size": 54975581388800,
        "usage_error": None,
    }
    _patch(monkeypatch, "storage_usage", lambda client, *, region=None: [unavailable, uninitialised])
    monkeypatch.setattr(output_module, "console", Console(width=140, highlight=False))

    result = CliRunner().invoke(main, ["nfs", "df"])

    assert result.exit_code == 0, result.output
    assert "Usage unavailable for bj-B1: detail exploded" in result.output
    assert "west-X" in result.output


def test_df_json(home: Path, monkeypatch) -> None:
    """``--json`` emits the usage rows unchanged."""
    _seed_token()
    _patch(monkeypatch, "storage_usage", lambda client, *, region=None: DF_ROWS)

    result = CliRunner().invoke(main, ["--json", "nfs", "df"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == DF_ROWS


def test_df_empty_result_is_muted_message(home: Path, monkeypatch) -> None:
    """An empty region list explains that there is nothing to show."""
    _seed_token()
    _patch(monkeypatch, "storage_usage", lambda client, *, region=None: [])

    result = CliRunner().invoke(main, ["nfs", "df"])

    assert result.exit_code == 0, result.output
    assert "No NFS regions found." in result.output
