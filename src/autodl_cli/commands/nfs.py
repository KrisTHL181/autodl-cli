"""``autodl nfs`` — network disk (NFS) storage commands.

``regions`` lists the per-region volumes from ``GET /api/v1/file_storage/list``.
``ls`` reads one directory from the region's ``file_storage/dir/v2`` endpoint,
``rm`` deletes one file, and ``upload`` reproduces the web console's chunked
uploader: 5 MiB multipart chunks posted to the region host, with the MD5 of the
file's first 1 MiB sent with every chunk. Storage is regional, so ``--region``
is required.
"""

from __future__ import annotations

from pathlib import Path

import click

from autodl_cli import output
from autodl_cli.commands._helpers import build_client, require_token
from autodl_cli.config import load_config
from autodl_cli.errors import AutoDLError
from autodl_cli.handlers import nfs as nfs_handler


@click.group(help="Manage files on AutoDL network disk (NFS) storage.")
def nfs() -> None:
    """Manage files on AutoDL network disk (NFS) storage."""


@nfs.command("regions", help="List the NFS storage volumes available to the account.")
@click.pass_context
def regions_command(ctx: click.Context) -> None:
    """List every NFS volume, its region sign, address, and quota.

    :param ctx: Click context; ``ctx.obj["json"]`` selects JSON output.
    :raises click.ClickException: When no token is configured or the API call
        fails.
    """
    config = load_config()
    token = require_token(config)

    try:
        with build_client(token, config) as client:
            regions = nfs_handler.list_regions(client)
    except AutoDLError as exc:
        raise click.ClickException(str(exc)) from exc

    if ctx.obj and ctx.obj.get("json"):
        output.render_json(regions)
        return

    output.render_nfs_regions(regions)


@nfs.command("ls", help="List files in one NFS directory.")
@click.argument("path", default="/")
@click.option(
    "--region",
    "region",
    required=True,
    metavar="SIGN",
    help="Region sign shown by `autodl nfs regions`, for example bj-B1.",
)
@click.pass_context
def ls_command(ctx: click.Context, path: str, region: str) -> None:
    """List the files and directories in one NFS directory.

    :param ctx: Click context; ``ctx.obj["json"]`` selects JSON output.
    :param path: Remote directory to list, ``"/"`` by default.
    :param region: Region sign, for example ``bj-B1``.
    :raises click.ClickException: When no token is configured or the API call
        fails.
    """
    config = load_config()
    token = require_token(config)

    try:
        with build_client(token, config) as client:
            listing = nfs_handler.list_files(client, region=region, dir_path=path)
    except AutoDLError as exc:
        raise click.ClickException(str(exc)) from exc

    if ctx.obj and ctx.obj.get("json"):
        output.render_json(listing)
        return

    output.render_nfs_files(listing)


@nfs.command("rm", help="Delete one file from NFS storage.")
@click.argument("path")
@click.option(
    "--region",
    "region",
    required=True,
    metavar="SIGN",
    help="Region sign shown by `autodl nfs regions`, for example bj-B1.",
)
@click.option("--yes", "-y", is_flag=True, help="Delete without asking for confirmation.")
@click.pass_context
def rm_command(ctx: click.Context, path: str, region: str, yes: bool) -> None:
    """Delete one remote file.

    The path is split into a directory and a file name, so ``/data/a.txt`` and
    ``a.txt`` both work. Deletion is irreversible, so the command asks for
    confirmation unless ``--yes`` is passed; use ``--yes`` in scripts.

    :param ctx: Click context; ``ctx.obj["json"]`` selects JSON output.
    :param path: Remote file path.
    :param region: Region sign, for example ``bj-B1``.
    :param yes: Whether to skip the confirmation prompt.
    :raises click.ClickException: When no token is configured, the path is
        invalid, or the API call fails.
    :raises click.Abort: When the user declines the confirmation prompt.
    """
    config = load_config()
    token = require_token(config)
    if not yes:
        click.confirm(f"Delete {path} from NFS region {region}?", abort=True)

    try:
        with build_client(token, config) as client:
            result = nfs_handler.delete_file(client, path, region=region)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    except AutoDLError as exc:
        raise click.ClickException(str(exc)) from exc

    if ctx.obj and ctx.obj.get("json"):
        output.render_json(result)
        return

    output.success(f"Deleted {result['remote_path']} (region {result['region']}).")


@nfs.command("upload", help="Upload a local file to NFS storage.")
@click.argument(
    "local_path",
    type=click.Path(exists=True, dir_okay=False, readable=True, path_type=Path),
)
@click.option(
    "--region",
    "region",
    required=True,
    metavar="SIGN",
    help="Region sign shown by `autodl nfs regions`, for example bj-B1.",
)
@click.option(
    "--dir-path", default="/", show_default=True, metavar="PATH", help="Remote directory that receives the file."
)
@click.option("--filename", default=None, metavar="NAME", help="Remote file name; defaults to the local file name.")
@click.pass_context
def upload_command(
    ctx: click.Context,
    local_path: Path,
    region: str,
    dir_path: str,
    filename: str | None,
) -> None:
    """Upload one local file in 5 MiB chunks and print where it landed.

    :param ctx: Click context; ``ctx.obj["json"]`` selects JSON output.
    :param local_path: Local file to upload.
    :param region: Region sign, for example ``bj-B1``.
    :param dir_path: Remote directory that receives the file.
    :param filename: Remote file name; the local name is used when ``None``.
    :raises click.ClickException: When no token is configured, the file cannot
        be read, or the API call fails.
    """
    config = load_config()
    token = require_token(config)

    try:
        with build_client(token, config) as client:
            if ctx.obj and ctx.obj.get("json"):
                result = nfs_handler.upload_file(
                    client,
                    local_path,
                    region=region,
                    dir_path=dir_path,
                    filename=filename,
                )
            else:
                total = local_path.stat().st_size
                with output.upload_progress(local_path.name, total) as update:
                    result = nfs_handler.upload_file(
                        client,
                        local_path,
                        region=region,
                        dir_path=dir_path,
                        filename=filename,
                        on_progress=update,
                    )
    except (OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    except AutoDLError as exc:
        raise click.ClickException(str(exc)) from exc

    if ctx.obj and ctx.obj.get("json"):
        output.render_json(result)
        return

    output.render_nfs_upload(result)


def register_nfs(main_group: click.Group) -> click.Group:
    """Register the ``nfs`` command group on ``main_group``.

    :param main_group: Root Click group.
    :returns: The same group, for chaining.
    """
    main_group.add_command(nfs)
    return main_group
