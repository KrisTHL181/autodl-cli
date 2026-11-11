"""``autodl nfs`` — network disk (NFS) storage commands.

``regions`` lists the per-region volumes from ``GET /api/v1/file_storage/list``.
``ls`` reads one directory from the region's ``file_storage/dir/v2`` endpoint,
``rm`` deletes one file (or, with ``-r``, one directory), and ``df`` reads live
usage from each created region's ``/detail`` endpoint. ``upload`` reproduces
the web console's chunked
uploader: 5 MiB multipart chunks posted to the region host, with the MD5 of the
file's first 1 MiB sent with every chunk. ``download`` asks the region host for
a download token and then fetches the raw file with a browser-style GET, so the
token travels in the query string and no ``Authorization`` header is sent.
Storage is regional, so ``--region`` is required except for ``df``, which can
show every region.
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


@nfs.command("rm", help="Delete a file or directory from NFS storage.")
@click.argument("path")
@click.option(
    "--region",
    "region",
    required=True,
    metavar="SIGN",
    help="Region sign shown by `autodl nfs regions`, for example bj-B1.",
)
@click.option("--recursive", "-r", is_flag=True, help="Delete a directory and its contents.")
@click.option("--yes", "-y", is_flag=True, help="Delete without asking for confirmation.")
@click.pass_context
def rm_command(ctx: click.Context, path: str, region: str, recursive: bool, yes: bool) -> None:
    """Delete one remote file, or a directory when ``--recursive`` is set.

    The path is split into a directory and a name, so ``/data/a.txt`` and
    ``a.txt`` both work. Deletion is irreversible, so the command asks for
    confirmation unless ``--yes`` is passed; use ``--yes`` in scripts. With
    ``--recursive`` it targets the console's directory endpoint and warns that
    the directory's contents go with it.

    :param ctx: Click context; ``ctx.obj["json"]`` selects JSON output.
    :param path: Remote file or directory path.
    :param region: Region sign, for example ``bj-B1``.
    :param recursive: Whether to delete a directory rather than a file.
    :param yes: Whether to skip the confirmation prompt.
    :raises click.ClickException: When no token is configured, the path is
        invalid, or the API call fails.
    :raises click.Abort: When the user declines the confirmation prompt.
    """
    config = load_config()
    token = require_token(config)
    if not yes:
        if recursive:
            click.confirm(f"Delete directory {path} and its contents from NFS region {region}?", abort=True)
        else:
            click.confirm(f"Delete {path} from NFS region {region}?", abort=True)

    try:
        with build_client(token, config) as client:
            if recursive:
                result = nfs_handler.delete_directory(client, path, region=region)
            else:
                result = nfs_handler.delete_file(client, path, region=region)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    except AutoDLError as exc:
        raise click.ClickException(str(exc)) from exc

    if ctx.obj and ctx.obj.get("json"):
        output.render_json(result)
        return

    if recursive:
        output.success(f"Deleted directory {result['remote_path']} and its contents (region {result['region']}).")
    else:
        output.success(f"Deleted {result['remote_path']} (region {result['region']}).")


@nfs.command("df", help="Show live NFS storage usage by region.")
@click.option(
    "--region",
    "region",
    default=None,
    metavar="SIGN",
    help="Only show this region sign, for example bj-B1.",
)
@click.pass_context
def df_command(ctx: click.Context, region: str | None) -> None:
    """Show live capacity, used space, and inode usage for the NFS volumes.

    Each created volume is queried through its region host's ``/detail``
    endpoint. Regions whose status is not ``created`` are listed with ``"-"``
    usage, because the server rejects the detail request for them.

    :param ctx: Click context; ``ctx.obj["json"]`` selects JSON output.
    :param region: Optional region sign to show; every region when ``None``.
    :raises click.ClickException: When no token is configured, the region is
        unknown, or the API call fails.
    """
    config = load_config()
    token = require_token(config)

    try:
        with build_client(token, config) as client:
            rows = nfs_handler.storage_usage(client, region=region)
    except AutoDLError as exc:
        raise click.ClickException(str(exc)) from exc

    if ctx.obj and ctx.obj.get("json"):
        output.render_json(rows)
        return

    output.render_nfs_df(rows)


@nfs.command("download", help="Download a file from NFS storage.")
@click.argument("remote_path")
@click.option(
    "--region",
    "region",
    required=True,
    metavar="SIGN",
    help="Region sign shown by `autodl nfs regions`, for example bj-B1.",
)
@click.option(
    "--output",
    "-o",
    "output_path",
    default=None,
    type=click.Path(path_type=Path),
    metavar="PATH",
    help="Destination file or existing directory; defaults to the remote file name in the current directory.",
)
@click.option("--force", is_flag=True, help="Overwrite an existing local file.")
@click.pass_context
def download_command(
    ctx: click.Context,
    remote_path: str,
    region: str,
    output_path: Path | None,
    force: bool,
) -> None:
    """Download one remote file and print where it landed.

    The destination defaults to the remote file name in the current directory.
    When ``--output`` names an existing directory, the remote file name is
    appended to it. An existing destination is rejected unless ``--force`` is
    passed.

    :param ctx: Click context; ``ctx.obj["json"]`` selects JSON output.
    :param remote_path: Remote file path, for example ``"/data/notes.txt"``.
    :param region: Region sign, for example ``bj-B1``.
    :param output_path: Destination file or existing directory.
    :param force: Whether to overwrite an existing local file.
    :raises click.ClickException: When no token is configured, the path is
        invalid, the destination cannot be written, or the API call fails.
    """
    config = load_config()
    token = require_token(config)

    remote_name = Path(remote_path).name
    if output_path is None:
        destination = Path(remote_name)
    elif output_path.is_dir():
        destination = output_path / remote_name
    else:
        destination = output_path

    if destination.exists() and not force:
        raise click.ClickException(f"Local file already exists: {destination} (pass --force to replace it)")

    try:
        with build_client(token, config) as client:
            if ctx.obj and ctx.obj.get("json"):
                result = nfs_handler.download_file(
                    client,
                    remote_path,
                    region=region,
                    local_path=destination,
                    overwrite=force,
                )
            else:
                with output.download_progress(remote_name or remote_path) as update:
                    result = nfs_handler.download_file(
                        client,
                        remote_path,
                        region=region,
                        local_path=destination,
                        overwrite=force,
                        on_progress=update,
                    )
    except (OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    except AutoDLError as exc:
        raise click.ClickException(str(exc)) from exc

    if ctx.obj and ctx.obj.get("json"):
        output.render_json(result)
        return

    output.render_nfs_download(result)


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
