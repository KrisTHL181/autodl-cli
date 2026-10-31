"""NFS (network disk) storage handlers.

AutoDL gives every region its own NFS volume. The account-wide list of volumes
comes from ``GET /api/v1/file_storage/list`` on the main site; ordinary file
operations go to the matching region host instead::

    https://{export_addr_1}:{port}/api/v1/file_storage/...

Directory listings use ``GET /dir/v2`` for ``autofs`` volumes. Uploads mirror
the web console's WebUploader configuration: a multipart ``POST /file`` per
5 MiB chunk, with ``chunk_offset`` carrying the zero-based chunk index,
``is_last`` set on the final chunk, and ``md5`` holding the MD5 of the first
1 MiB of the file. Files split into more than one chunk also carry
WebUploader's ``chunks`` total and ``chunk`` index. ``file_uuid`` is the
upload's epoch-millisecond identifier.
"""

from __future__ import annotations

import hashlib
import mimetypes
import re
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from autodl_cli.errors import APIError
from autodl_cli.handlers._common import require_success_any, require_success_list

if TYPE_CHECKING:
    from collections.abc import Callable

    from autodl_cli.client import AutoDLClient

#: Chunk size used by the web console's WebUploader.
CHUNK_SIZE = 5 * 1024 * 1024

#: The console hashes only this prefix of the file rather than all of it.
HASH_LIMIT = 1024 * 1024

#: Per-chunk timeout, generous enough for a 5 MiB upload on a slow link.
UPLOAD_TIMEOUT = 300.0

#: Collapse accidental duplicate slashes in a remote directory path.
_MULTIPLE_SLASHES = re.compile("/{2,}")


def _as_text(value: object) -> str:
    """Return *value* when it is a string, otherwise an empty string.

    :param value: Raw field from an API response.
    :returns: The string value, or ``""``.
    """
    return value if isinstance(value, str) else ""


def _as_int(value: object) -> int | None:
    """Return *value* when it is an integer that is not a boolean.

    :param value: Raw field from an API response.
    :returns: The integer value, or ``None``.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def list_regions(client: AutoDLClient) -> list[dict[str, object]]:
    """Return the NFS volumes attached to the account.

    :param client: Authenticated API client.
    :returns: One mapping per region with ``sign``, ``name``, ``status``,
        ``export_addr``, ``port``, ``fs_type``, ``default_size``,
        ``free_size``, and ``max_size``.
    :raises autodl_cli.errors.AutoDLError: When the API rejects the request.
    """
    payload = client.request("GET", "/api/v1/file_storage/list")
    entries = require_success_list(payload, action="NFS region list")

    regions: list[dict[str, object]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        sign = entry.get("sign")
        if not isinstance(sign, str) or not sign:
            continue
        regions.append(
            {
                "sign": sign,
                "name": _as_text(entry.get("name")),
                "status": _as_text(entry.get("status")),
                "export_addr": _as_text(entry.get("export_addr_1")),
                "port": _as_int(entry.get("port")),
                "fs_type": _as_text(entry.get("fs_type")),
                "default_size": _as_int(entry.get("default_size")),
                "free_size": _as_int(entry.get("free_size")),
                "max_size": _as_int(entry.get("max_size")),
            }
        )
    return regions


def get_region(client: AutoDLClient, sign: str) -> dict[str, object]:
    """Resolve a region sign such as ``bj-B1`` to its storage volume.

    The comparison is exact first and case-insensitive as a fallback, so
    ``BJ-B1`` works too.

    :param client: Authenticated API client.
    :param sign: Region sign as shown by :func:`list_regions`.
    :returns: The matching region mapping.
    :raises autodl_cli.errors.APIError: When the sign is unknown or the
        matching volume is not in the ``created`` state.
    """
    regions = list_regions(client)
    requested = sign.strip()

    chosen: dict[str, object] | None = None
    for region in regions:
        if region.get("sign") == requested:
            chosen = region
            break
    if chosen is None:
        lowered = requested.lower()
        for region in regions:
            current = region.get("sign")
            if isinstance(current, str) and current.lower() == lowered:
                chosen = region
                break
    if chosen is None:
        available = ", ".join(str(region["sign"]) for region in regions) or "none"
        raise APIError(f"Unknown NFS region {sign!r}; available regions: {available}")

    status = chosen.get("status")
    if status != "created":
        state = status if isinstance(status, str) and status else "not ready"
        raise APIError(f"NFS region {chosen['sign']!r} is {state}; choose a region whose status is 'created'")
    return chosen


def region_base_url(region: dict[str, object]) -> str:
    """Build the ``/api/v1/file_storage`` base URL for one region.

    The web console rewrites legacy ``seetacloud`` and ``autodl.pro`` hosts to
    their ``autodl.com`` equivalents before calling them, so this does too.

    :param region: Region mapping returned by :func:`get_region`.
    :returns: The region's storage API base URL.
    :raises autodl_cli.errors.APIError: When the region has no address or port.
    """
    address = region.get("export_addr")
    port = region.get("port")
    if not isinstance(address, str) or not address or not isinstance(port, int) or isinstance(port, bool):
        raise APIError(f"NFS region {region.get('sign')!r} has no export address")

    host = address.replace("seetacloud", "autodl").replace("autodl.pro", "autodl.com")
    return f"https://{host}:{port}/api/v1/file_storage"


def normalize_dir_path(value: str) -> str:
    """Normalise a remote directory path.

    :param value: Path supplied by the caller, for example ``"data/"``.
    :returns: An absolute path with no duplicate or trailing slashes, or ``"/"``.
    """
    path = _MULTIPLE_SLASHES.sub("/", value.strip() or "/")
    if not path.startswith("/"):
        path = f"/{path}"
    if path != "/":
        path = path.rstrip("/") or "/"
    return path


def _remote_path(dir_path: str, filename: str) -> str:
    """Join a remote directory and file name.

    :param dir_path: Normalised remote directory.
    :param filename: Remote file name.
    :returns: The full remote path.
    """
    return f"/{filename}" if dir_path == "/" else f"{dir_path}/{filename}"


def list_files(client: AutoDLClient, *, region: str, dir_path: str = "/") -> dict[str, object]:
    """List one NFS directory.

    ``autofs`` volumes use ``/dir/v2``; other volume types use ``/dir``.

    :param client: Authenticated API client.
    :param region: Region sign, for example ``bj-B1``.
    :param dir_path: Remote directory to list, ``"/"`` by default.
    :returns: A mapping with ``region``, ``dir_path``, and ``entries``. Each
        entry has ``name``, ``size``, ``updated_at``, and ``is_dir``.
    :raises autodl_cli.errors.AutoDLError: When the API rejects the request.
    """
    volume = get_region(client, region)
    base = region_base_url(volume)
    path = normalize_dir_path(dir_path)
    endpoint = "/dir/v2" if volume.get("fs_type") == "autofs" else "/dir"

    payload = client.request("GET", f"{base}{endpoint}", params={"dir_path": path})
    entries = require_success_list(payload, action=f"NFS directory {path}")

    files: list[dict[str, object]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            name = _as_text(entry.get("filename"))
        files.append(
            {
                "name": name,
                "size": _as_int(entry.get("size")),
                "updated_at": _as_text(entry.get("updated_at")),
                "is_dir": entry.get("is_dir") is True,
            }
        )

    return {"region": str(volume["sign"]), "dir_path": path, "entries": files}


def _md5_prefix(path: Path, limit: int) -> str:
    """Hash at most *limit* bytes from the start of a file.

    :param path: Local file to read.
    :param limit: Maximum number of bytes to include.
    :returns: The lowercase hexadecimal MD5 digest.
    :raises ValueError: When the file cannot be read.
    """
    hasher = hashlib.md5()
    try:
        with path.open("rb") as handle:
            hasher.update(handle.read(limit))
    except OSError as exc:
        raise ValueError(f"Cannot read {path}: {exc}") from exc
    return hasher.hexdigest()


def _last_modified(value: float) -> str:
    """Format a modification timestamp the way the web console does.

    :param value: POSIX timestamp from the local file.
    :returns: A string such as ``"8/20/2026, 7:31:44 PM"``.
    """
    moment = datetime.fromtimestamp(value)
    hour = moment.hour % 12 or 12
    meridiem = "AM" if moment.hour < 12 else "PM"
    return f"{moment.month}/{moment.day}/{moment.year}, {hour}:{moment.minute:02d}:{moment.second:02d} {meridiem}"


def _validate_filename(filename: str) -> str:
    """Validate a remote file name.

    :param filename: Candidate name.
    :returns: The name unchanged.
    :raises ValueError: When the name is empty or contains a path separator.
    """
    if not filename or filename in (".", "..") or "/" in filename or "\\" in filename or "\0" in filename:
        raise ValueError("Remote filename must be a plain file name without path separators")
    return filename


def split_remote_path(value: str) -> tuple[str, str]:
    """Split a full remote path into its directory and file name.

    :param value: Remote path such as ``"/data/notes.txt"`` or ``"notes.txt"``.
    :returns: The normalised directory and the file name.
    :raises ValueError: When the path is the NFS root or the file name is
        invalid.
    """
    path = normalize_dir_path(value)
    if path == "/":
        raise ValueError("Refusing to delete the NFS root directory")
    dir_path, _, filename = path.rpartition("/")
    return dir_path or "/", _validate_filename(filename)


def delete_file(client: AutoDLClient, remote_path: str, *, region: str) -> dict[str, object]:
    """Delete one file from an NFS volume.

    Deletion is immediate and irreversible. Directories are not handled by
    this call; the web console uses a separate ``DELETE /dir`` endpoint for
    them.

    :param client: Authenticated API client.
    :param remote_path: Remote file path, for example ``"/data/notes.txt"``.
    :param region: Region sign, for example ``bj-B1``.
    :returns: A mapping with ``region``, ``region_name``, ``dir_path``,
        ``filename``, ``remote_path``, and ``deleted``.
    :raises ValueError: When the remote path is invalid.
    :raises autodl_cli.errors.AutoDLError: When the API rejects the request.
    """
    dir_path, filename = split_remote_path(remote_path)
    volume = get_region(client, region)
    url = f"{region_base_url(volume)}/file"

    payload = client.request("DELETE", url, json={"filename": filename, "dir_path": dir_path})
    require_success_any(payload, action=f"NFS delete of {filename!r}")

    return {
        "region": str(volume["sign"]),
        "region_name": _as_text(volume.get("name")),
        "dir_path": dir_path,
        "filename": filename,
        "remote_path": _remote_path(dir_path, filename),
        "deleted": True,
    }


def upload_file(
    client: AutoDLClient,
    local_path: Path | str,
    *,
    region: str,
    dir_path: str = "/",
    filename: str | None = None,
    chunk_size: int = CHUNK_SIZE,
    on_progress: Callable[[int], None] | None = None,
) -> dict[str, object]:
    """Upload a local file to an NFS volume in chunks.

    The request layout reproduces the web console's uploader, including its
    quirk of hashing only the first MiB of the file. Chunks are sent in order
    and the next one is only read after the previous one succeeds, so a
    failure leaves a partial file behind rather than corrupting it silently.

    :param client: Authenticated API client.
    :param local_path: Local file to upload.
    :param region: Region sign, for example ``bj-B1``.
    :param dir_path: Remote directory that receives the file, ``"/"`` by
        default.
    :param filename: Remote file name; the local name is used when ``None``.
    :param chunk_size: Upload chunk size in bytes.
    :param on_progress: Optional callback receiving the number of bytes sent
        after each successful chunk.
    :returns: A mapping with ``region``, ``region_name``, ``dir_path``,
        ``filename``, ``remote_path``, ``size``, ``chunks``, ``file_uuid``,
        and ``md5``.
    :raises ValueError: When the local file or the remote name is invalid.
    :raises autodl_cli.errors.AutoDLError: When the API rejects a chunk.
    """
    path = Path(local_path).expanduser()
    if not path.is_file():
        raise ValueError(f"Local file not found: {path}")
    if isinstance(chunk_size, bool) or chunk_size < 1:
        raise ValueError("chunk_size must be at least 1")

    try:
        stat_result = path.stat()
    except OSError as exc:
        raise ValueError(f"Cannot read {path}: {exc}") from exc

    file_size = stat_result.st_size
    remote_name = _validate_filename(filename if filename is not None else path.name)
    remote_dir = normalize_dir_path(dir_path)

    volume = get_region(client, region)
    url = f"{region_base_url(volume)}/file"
    file_uuid = str(int(time.time() * 1000))
    digest = _md5_prefix(path, HASH_LIMIT)
    content_type = mimetypes.guess_type(remote_name)[0] or "application/octet-stream"
    modified = _last_modified(stat_result.st_mtime)

    chunk_count = max(1, (file_size + chunk_size - 1) // chunk_size)
    try:
        with path.open("rb") as handle:
            for index in range(chunk_count):
                chunk = handle.read(chunk_size)
                is_last = index == chunk_count - 1
                fields = {
                    "id": "0",
                    "chunk_offset": str(index),
                    "md5": digest,
                    "is_last": "1" if is_last else "0",
                    "dir_path": remote_dir,
                    "filename": remote_name,
                    "file_uuid": file_uuid,
                    "name": remote_name,
                    "type": content_type,
                    "lastModifiedDate": modified,
                    "size": str(file_size),
                }
                # WebUploader only adds these two for files split into more
                # than one chunk; the console relies on that behaviour.
                if chunk_count > 1:
                    fields["chunks"] = str(chunk_count)
                    fields["chunk"] = str(index)
                payload = client.request(
                    "POST",
                    url,
                    data=fields,
                    files={"file": (remote_name, chunk, content_type)},
                    timeout=UPLOAD_TIMEOUT,
                )
                require_success_any(payload, action=f"NFS upload of {remote_name!r}")
                if on_progress is not None:
                    on_progress(min((index + 1) * chunk_size, file_size))
    except OSError as exc:
        raise ValueError(f"Cannot read {path}: {exc}") from exc

    return {
        "region": str(volume["sign"]),
        "region_name": _as_text(volume.get("name")),
        "dir_path": remote_dir,
        "filename": remote_name,
        "remote_path": _remote_path(remote_dir, remote_name),
        "size": file_size,
        "chunks": chunk_count,
        "file_uuid": file_uuid,
        "md5": digest,
    }
