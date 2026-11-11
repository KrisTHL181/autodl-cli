"""Tests for :mod:`autodl_cli.handlers.nfs`, all offline."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import httpx
import pytest

from autodl_cli.client import AutoDLClient
from autodl_cli.errors import APIError, AuthError
from autodl_cli.handlers import nfs as nfs_handler

TOKEN = "fake-token"
REGION_HOST = "region-bjb1-fs-2.autodl.com"
REGION_PORT = 7007

#: Two volumes: one usable ``autofs`` region and one uninitialised legacy one.
REGIONS = [
    {
        "sign": "bj-B1",
        "name": "北京B区",
        "export_addr_1": REGION_HOST,
        "export_addr_2": "10.200.3.254",
        "status": "created",
        "port": REGION_PORT,
        "fs_type": "autofs",
        "free_size": 21474836480,
        "max_size": 54975581388800,
        "default_size": 214748364800,
        "initialized_at": "2025-08-30T11:17:45+08:00",
    },
    {
        "sign": "west-X",
        "name": "西北企业区",
        "export_addr_1": "region-westx.seetacloud.com",
        "export_addr_2": "172.51.0.228",
        "status": "uninitialized",
        "port": 7007,
        "fs_type": "autofs",
        "free_size": 21474836480,
        "max_size": 54975581388800,
        "default_size": 214748364800,
        "initialized_at": None,
    },
]

#: A directory listing shaped like ``GET /file_storage/dir/v2``.
DIRECTORY = [
    {
        "name": "notes.txt",
        "size": 2035,
        "updated_at": "2026-10-31T19:58:19.788Z",
        "is_dir": False,
    },
    {"name": "datasets", "size": 4096, "updated_at": "0001-01-01T00:00:00Z", "is_dir": True},
    {"filename": "legacy.bin", "size": 10, "updated_at": "2026-09-01T00:00:00Z", "is_dir": False},
]

#: Live usage reported by ``GET /file_storage/detail`` for a created volume.
DETAIL = {
    "total_space": 214748364800,
    "total_inodes": 200000,
    "used_space": 16305467392,
    "used_inodes": 46,
}


def _success(data: object) -> httpx.Response:
    """Build a successful API envelope.

    :param data: Value for the ``data`` field.
    :returns: The response.
    """
    return httpx.Response(200, json={"code": "Success", "data": data, "msg": "", "request_id": ""})


def _router(directory: object = DIRECTORY, *, seen: list[httpx.Request] | None = None):
    """Build a transport handler serving the catalogue, detail, and a directory.

    :param directory: Payload for the directory listing.
    :param seen: Optional list that receives every request.
    :returns: A function suitable for :class:`httpx.MockTransport`.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if request.url.host == "www.autodl.com" and request.url.path == "/api/v1/file_storage/list":
            return _success(REGIONS)
        if request.url.path == "/api/v1/file_storage/detail":
            return _success(DETAIL)
        if request.url.path.endswith(("/dir/v2", "/dir")):
            return _success(directory)
        return _success(1)

    return handler


def _client(handler) -> AutoDLClient:
    """Build a client backed by *handler*.

    :param handler: Mock transport handler.
    :returns: The client.
    """
    return AutoDLClient(TOKEN, transport=httpx.MockTransport(handler))


def _multipart_fields(body: bytes) -> dict[str, str]:
    """Extract the scalar fields of a multipart body.

    :param body: Raw request body.
    :returns: Field name to ASCII value.
    """
    text = body.decode("utf-8", errors="replace")
    return dict(re.findall(r'name="([^"]+)"\r\n\r\n(.*?)\r\n', text, re.S))


def _multipart_file(body: bytes) -> bytes:
    """Extract the ``file`` part of a multipart body.

    :param body: Raw request body.
    :returns: The uploaded bytes.
    """
    match = re.search(rb'name="file"; filename="[^"]*"\r\nContent-Type: [^\r]+\r\n\r\n(.*?)\r\n--', body, re.S)
    assert match is not None
    return match.group(1)


def test_list_regions_reads_the_catalogue_and_normalises_fields() -> None:
    """The catalogue is fetched from the main site and trimmed to used fields."""
    seen: list[httpx.Request] = []

    with _client(_router(seen=seen)) as client:
        regions = nfs_handler.list_regions(client)

    assert [(request.method, str(request.url)) for request in seen] == [
        ("GET", "https://www.autodl.com/api/v1/file_storage/list")
    ]
    assert seen[0].headers["authorization"] == TOKEN
    assert regions[0] == {
        "sign": "bj-B1",
        "name": "北京B区",
        "status": "created",
        "export_addr": REGION_HOST,
        "port": REGION_PORT,
        "fs_type": "autofs",
        "default_size": 214748364800,
        "free_size": 21474836480,
        "max_size": 54975581388800,
    }


def test_list_regions_skips_entries_without_a_sign() -> None:
    """Malformed catalogue entries are ignored instead of crashing the listing."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _success([{"name": "no sign"}, REGIONS[0], "junk"])

    with _client(handler) as client:
        regions = nfs_handler.list_regions(client)

    assert [region["sign"] for region in regions] == ["bj-B1"]


def test_list_regions_maps_authorize_failure() -> None:
    """An ``AuthorizeFailed`` envelope becomes an :class:`AuthError`."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": "AuthorizeFailed", "msg": "login timed out", "data": None})

    with _client(handler) as client:
        with pytest.raises(AuthError, match="login timed out"):
            nfs_handler.list_regions(client)


def test_get_region_matches_case_insensitively() -> None:
    """Region signs can be typed in any case."""

    with _client(_router()) as client:
        region = nfs_handler.get_region(client, " bj-b1 ")

    assert region["sign"] == "bj-B1"


def test_get_region_rejects_unknown_sign() -> None:
    """An unknown sign lists the available ones."""

    with _client(_router()) as client:
        with pytest.raises(APIError, match="Unknown NFS region 'nowhere'.*bj-B1, west-X"):
            nfs_handler.get_region(client, "nowhere")


def test_get_region_rejects_uninitialised_volume() -> None:
    """A volume that is not ``created`` cannot be used."""

    with _client(_router()) as client:
        with pytest.raises(APIError, match="uninitialized"):
            nfs_handler.get_region(client, "west-X")


def test_region_base_url_rewrites_legacy_hosts() -> None:
    """``seetacloud`` hosts are rewritten the way the web console does."""
    assert (
        nfs_handler.region_base_url({"sign": "west-X", "export_addr": "region-westx.seetacloud.com", "port": 8093})
        == "https://region-westx.autodl.com:8093/api/v1/file_storage"
    )


def test_region_base_url_requires_an_address() -> None:
    """A volume without an address is an API error."""
    with pytest.raises(APIError, match="no export address"):
        nfs_handler.region_base_url({"sign": "x", "export_addr": "", "port": 7007})


def test_list_files_queries_the_region_host() -> None:
    """The listing goes to the region's ``dir/v2`` endpoint with the right path."""
    seen: list[httpx.Request] = []

    with _client(_router(seen=seen)) as client:
        listing = nfs_handler.list_files(client, region="bj-B1", dir_path="data/")

    directory_request = seen[-1]
    assert directory_request.url.host == REGION_HOST
    assert directory_request.url.port == REGION_PORT
    assert directory_request.url.path == "/api/v1/file_storage/dir/v2"
    assert directory_request.url.params["dir_path"] == "/data"
    assert directory_request.headers["authorization"] == TOKEN
    assert listing == {
        "region": "bj-B1",
        "dir_path": "/data",
        "entries": [
            {"name": "notes.txt", "size": 2035, "updated_at": "2026-10-31T19:58:19.788Z", "is_dir": False},
            {"name": "datasets", "size": 4096, "updated_at": "0001-01-01T00:00:00Z", "is_dir": True},
            {"name": "legacy.bin", "size": 10, "updated_at": "2026-09-01T00:00:00Z", "is_dir": False},
        ],
    }


def test_list_files_uses_the_plain_dir_endpoint_for_other_volume_types() -> None:
    """Non-``autofs`` volumes use ``/dir`` rather than ``/dir/v2``."""
    regions = [dict(REGIONS[0], fs_type="nfs")]
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "www.autodl.com":
            return _success(regions)
        return _success([])

    with _client(handler) as client:
        nfs_handler.list_files(client, region="bj-B1")

    assert seen[-1].url.path == "/api/v1/file_storage/dir"


def test_normalize_dir_path() -> None:
    """Paths become absolute without duplicate or trailing slashes."""
    assert nfs_handler.normalize_dir_path("") == "/"
    assert nfs_handler.normalize_dir_path("data") == "/data"
    assert nfs_handler.normalize_dir_path("//data//sets//") == "/data/sets"
    assert nfs_handler.normalize_dir_path("/") == "/"


def test_split_remote_path() -> None:
    """A remote path becomes a directory and a file name."""
    assert nfs_handler.split_remote_path("/data/notes.txt") == ("/data", "notes.txt")
    assert nfs_handler.split_remote_path("notes.txt") == ("/", "notes.txt")
    assert nfs_handler.split_remote_path("//data//sets//notes.txt") == ("/data/sets", "notes.txt")


def test_split_remote_path_rejects_invalid_paths() -> None:
    """The root and traversal names cannot be deleted."""
    with pytest.raises(ValueError, match="root directory"):
        nfs_handler.split_remote_path("/")
    with pytest.raises(ValueError, match="plain file name"):
        nfs_handler.split_remote_path("/data/..")


def test_delete_file_sends_the_delete_body_to_the_region_host() -> None:
    """Delete targets ``/file`` on the region host with the split path."""
    seen: list[httpx.Request] = []

    with _client(_router(seen=seen)) as client:
        result = nfs_handler.delete_file(client, "/data/notes.txt", region="bj-B1")

    request = seen[-1]
    assert request.method == "DELETE"
    assert request.url.host == REGION_HOST
    assert request.url.port == REGION_PORT
    assert request.url.path == "/api/v1/file_storage/file"
    assert request.headers["authorization"] == TOKEN
    assert json.loads(request.content) == {"filename": "notes.txt", "dir_path": "/data"}
    assert result == {
        "region": "bj-B1",
        "region_name": "北京B区",
        "dir_path": "/data",
        "filename": "notes.txt",
        "remote_path": "/data/notes.txt",
        "deleted": True,
    }


def test_delete_file_accepts_a_bare_file_name() -> None:
    """A name without slashes deletes from the root."""
    seen: list[httpx.Request] = []

    with _client(_router(seen=seen)) as client:
        result = nfs_handler.delete_file(client, "notes.txt", region="bj-B1")

    assert json.loads(seen[-1].content) == {"filename": "notes.txt", "dir_path": "/"}
    assert result["remote_path"] == "/notes.txt"


def test_delete_file_reports_a_rejected_delete() -> None:
    """A non-success envelope from the delete endpoint is raised."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.autodl.com":
            return _success(REGIONS)
        return httpx.Response(200, json={"code": "AuthorizeFailed", "msg": "expired", "data": None})

    with _client(handler) as client:
        with pytest.raises(AuthError, match="expired"):
            nfs_handler.delete_file(client, "/notes.txt", region="bj-B1")


def _upload_router(seen: list[httpx.Request]):
    """Build a transport that accepts the catalogue and every upload chunk.

    :param seen: List that receives every request.
    :returns: A function suitable for :class:`httpx.MockTransport`.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "www.autodl.com":
            return _success(REGIONS)
        return _success(1)

    return handler


def test_upload_file_sends_the_web_console_multipart_protocol(tmp_path: Path) -> None:
    """A small file is sent as one multipart chunk with the console's fields."""
    source = tmp_path / "sample.txt"
    source.write_bytes(b"hello nfs")
    seen: list[httpx.Request] = []
    progress: list[int] = []

    with _client(_upload_router(seen)) as client:
        result = nfs_handler.upload_file(
            client,
            source,
            region="bj-B1",
            dir_path="data/",
            on_progress=progress.append,
        )

    upload = seen[-1]
    assert upload.method == "POST"
    assert upload.url.host == REGION_HOST
    assert upload.url.port == REGION_PORT
    assert upload.url.path == "/api/v1/file_storage/file"
    assert upload.headers["authorization"] == TOKEN
    assert upload.headers["content-type"].startswith("multipart/form-data; boundary=")

    fields = _multipart_fields(upload.content)
    assert fields["id"] == "0"
    assert fields["chunk_offset"] == "0"
    assert fields["is_last"] == "1"
    assert fields["md5"] == hashlib.md5(b"hello nfs").hexdigest()
    assert fields["dir_path"] == "/data"
    assert fields["filename"] == "sample.txt"
    assert fields["name"] == "sample.txt"
    assert fields["size"] == "9"
    assert fields["type"] == "text/plain"
    assert fields["file_uuid"].isdigit()
    assert fields["lastModifiedDate"]
    assert "chunks" not in fields
    assert "chunk" not in fields
    assert _multipart_file(upload.content) == b"hello nfs"

    assert result["filename"] == "sample.txt"
    assert result["remote_path"] == "/data/sample.txt"
    assert result["size"] == 9
    assert result["chunks"] == 1
    assert result["md5"] == hashlib.md5(b"hello nfs").hexdigest()
    assert progress == [9]


def test_upload_file_splits_large_files_into_ordered_chunks(tmp_path: Path) -> None:
    """Each chunk carries its index, and only the last one is marked."""
    source = tmp_path / "chunks.bin"
    source.write_bytes(b"abcdefghij")
    seen: list[httpx.Request] = []
    progress: list[int] = []

    with _client(_upload_router(seen)) as client:
        result = nfs_handler.upload_file(
            client,
            source,
            region="bj-B1",
            chunk_size=4,
            on_progress=progress.append,
        )

    uploads = [request for request in seen if request.method == "POST"]
    assert len(uploads) == 3
    fields = [_multipart_fields(upload.content) for upload in uploads]
    assert [field["chunk_offset"] for field in fields] == ["0", "1", "2"]
    assert [field["chunk"] for field in fields] == ["0", "1", "2"]
    assert [field["chunks"] for field in fields] == ["3", "3", "3"]
    assert [field["is_last"] for field in fields] == ["0", "0", "1"]
    assert [_multipart_file(upload.content) for upload in uploads] == [b"abcd", b"efgh", b"ij"]
    assert progress == [4, 8, 10]
    assert result["chunks"] == 3


def test_upload_file_hashes_only_the_first_mebibyte(tmp_path: Path) -> None:
    """The MD5 covers the prefix the web console hashes, not the whole file."""
    source = tmp_path / "big.bin"
    source.write_bytes(b"a" * nfs_handler.HASH_LIMIT + b"tail")
    seen: list[httpx.Request] = []

    with _client(_upload_router(seen)) as client:
        result = nfs_handler.upload_file(
            client, source, region="bj-B1", chunk_size=len(b"a") * 2 * nfs_handler.HASH_LIMIT
        )

    expected = hashlib.md5(b"a" * nfs_handler.HASH_LIMIT).hexdigest()
    assert _multipart_fields(seen[-1].content)["md5"] == expected
    assert result["md5"] == expected
    assert expected != hashlib.md5(source.read_bytes()).hexdigest()


def test_upload_file_sends_an_empty_chunk_for_an_empty_file(tmp_path: Path) -> None:
    """An empty file still produces one ``is_last`` chunk."""
    source = tmp_path / "empty.txt"
    source.write_bytes(b"")
    seen: list[httpx.Request] = []

    with _client(_upload_router(seen)) as client:
        result = nfs_handler.upload_file(client, source, region="bj-B1")

    fields = _multipart_fields(seen[-1].content)
    assert fields["size"] == "0"
    assert fields["is_last"] == "1"
    assert fields["md5"] == hashlib.md5(b"").hexdigest()
    assert result["chunks"] == 1


def test_upload_file_validates_local_input(tmp_path: Path) -> None:
    """Missing files, bad names, and bad chunk sizes are rejected locally."""
    source = tmp_path / "sample.txt"
    source.write_bytes(b"x")

    with _client(_upload_router([])) as client:
        with pytest.raises(ValueError, match="Local file not found"):
            nfs_handler.upload_file(client, tmp_path / "missing.txt", region="bj-B1")
        with pytest.raises(ValueError, match="plain file name"):
            nfs_handler.upload_file(client, source, region="bj-B1", filename="../escape")
        with pytest.raises(ValueError, match="chunk_size"):
            nfs_handler.upload_file(client, source, region="bj-B1", chunk_size=0)


def test_upload_file_reports_a_rejected_chunk(tmp_path: Path) -> None:
    """A non-success envelope from the upload endpoint is raised."""
    source = tmp_path / "sample.txt"
    source.write_bytes(b"x")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.autodl.com":
            return _success(REGIONS)
        return httpx.Response(200, json={"code": "AuthorizeFailed", "msg": "expired", "data": None})

    with _client(handler) as client:
        with pytest.raises(AuthError, match="expired"):
            nfs_handler.upload_file(client, source, region="bj-B1")


def _download_router(
    seen: list[httpx.Request],
    *,
    content: bytes = b"hello nfs",
    download_token: object = "5153303f-c4c9-41e0-a550-d0e3ec2556e7",
):
    """Build a transport serving the catalogue, the token, and the raw file.

    :param seen: List that receives every request.
    :param content: Raw bytes returned by the download endpoint.
    :param download_token: ``data`` value returned by the token endpoint.
    :returns: A function suitable for :class:`httpx.MockTransport`.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "www.autodl.com":
            return _success(REGIONS)
        if request.url.path.endswith("/download_token"):
            return _success(download_token)
        if "/download/file/" in request.url.path:
            return httpx.Response(200, content=content, headers={"Content-Length": str(len(content))})
        return _success(1)

    return handler


def test_download_file_uses_a_token_and_an_unauthenticated_get(tmp_path: Path) -> None:
    """The token POST is authenticated; the raw GET carries ``auth`` only."""
    seen: list[httpx.Request] = []
    progress: list[tuple[int, int | None]] = []
    target = tmp_path / "notes.txt"

    with _client(_download_router(seen)) as client:
        result = nfs_handler.download_file(
            client,
            "/data/notes.txt",
            region="bj-B1",
            local_path=target,
            on_progress=lambda written, total: progress.append((written, total)),
        )

    token_request = next(request for request in seen if request.url.path.endswith("/download_token"))
    assert token_request.method == "POST"
    assert token_request.url.host == REGION_HOST
    assert token_request.url.port == REGION_PORT
    assert token_request.url.path == "/api/v1/file_storage/file/download_token"
    assert token_request.headers["authorization"] == TOKEN
    assert json.loads(token_request.content) == {"filename": "notes.txt", "dir_path": "/data"}

    download = next(request for request in seen if "/download/file/" in request.url.path)
    assert download.method == "GET"
    assert download.url.path == "/api/v1/file_storage/download/file/5153303f-c4c9-41e0-a550-d0e3ec2556e7"
    assert download.url.params["auth"] == TOKEN
    assert "authorization" not in download.headers

    assert target.read_bytes() == b"hello nfs"
    assert result == {
        "region": "bj-B1",
        "region_name": "北京B区",
        "dir_path": "/data",
        "filename": "notes.txt",
        "remote_path": "/data/notes.txt",
        "local_path": str(target),
        "size": 9,
        "total": 9,
    }
    assert progress
    assert progress[-1] == (9, 9)
    assert all(written == 9 and total == 9 for written, total in progress)


def test_download_file_reports_progress_for_an_empty_file(tmp_path: Path) -> None:
    """A zero-byte file still produces one final progress callback."""
    progress: list[tuple[int, int | None]] = []
    target = tmp_path / "empty.bin"

    with _client(_download_router([], content=b"")) as client:
        result = nfs_handler.download_file(
            client,
            "/empty.bin",
            region="bj-B1",
            local_path=target,
            on_progress=lambda written, total: progress.append((written, total)),
        )

    assert target.read_bytes() == b""
    assert progress == [(0, 0)]
    assert result["size"] == 0
    assert result["total"] == 0


def test_download_file_refuses_to_overwrite_before_any_request(tmp_path: Path) -> None:
    """An existing destination is rejected locally."""
    target = tmp_path / "notes.txt"
    target.write_bytes(b"keep me")
    seen: list[httpx.Request] = []

    with _client(_download_router(seen)) as client:
        with pytest.raises(ValueError) as excinfo:
            nfs_handler.download_file(client, "/notes.txt", region="bj-B1", local_path=target)

    assert str(excinfo.value) == f"Local file already exists: {target}"
    assert seen == []
    assert target.read_bytes() == b"keep me"


def test_download_file_accepts_overwrite(tmp_path: Path) -> None:
    """``overwrite=True`` replaces the existing destination."""
    target = tmp_path / "notes.txt"
    target.write_bytes(b"old")

    with _client(_download_router([])) as client:
        nfs_handler.download_file(
            client,
            "/notes.txt",
            region="bj-B1",
            local_path=target,
            overwrite=True,
        )

    assert target.read_bytes() == b"hello nfs"


def test_download_file_requires_an_existing_parent(tmp_path: Path) -> None:
    """A missing destination directory is rejected before any request."""
    seen: list[httpx.Request] = []
    target = tmp_path / "missing" / "notes.txt"

    with _client(_download_router(seen)) as client:
        with pytest.raises(ValueError, match="directory"):
            nfs_handler.download_file(client, "/notes.txt", region="bj-B1", local_path=target)

    assert seen == []
    assert not target.exists()


def test_download_file_rejects_malformed_token_data(tmp_path: Path) -> None:
    """A token reply without a non-empty string is an API error."""
    target = tmp_path / "notes.txt"

    with _client(_download_router([], download_token=None)) as client:
        with pytest.raises(APIError, match="malformed data"):
            nfs_handler.download_file(client, "/notes.txt", region="bj-B1", local_path=target)

    assert not target.exists()


def test_download_file_rejects_the_root_path(tmp_path: Path) -> None:
    """The shared path splitter rejects the volume root."""
    with _client(_download_router([])) as client:
        with pytest.raises(ValueError, match="root directory"):
            nfs_handler.download_file(client, "/", region="bj-B1", local_path=tmp_path / "x")


def test_delete_directory_sends_the_dir_body_to_the_region_host() -> None:
    """Delete targets ``/dir`` with the split directory name."""
    seen: list[httpx.Request] = []

    with _client(_router(seen=seen)) as client:
        result = nfs_handler.delete_directory(client, "/data/old", region="bj-B1")

    request = seen[-1]
    assert request.method == "DELETE"
    assert request.url.host == REGION_HOST
    assert request.url.port == REGION_PORT
    assert request.url.path == "/api/v1/file_storage/dir"
    assert request.headers["authorization"] == TOKEN
    assert json.loads(request.content) == {"dir_name": "old", "dir_path": "/data"}
    assert result == {
        "region": "bj-B1",
        "region_name": "北京B区",
        "dir_path": "/data",
        "dir_name": "old",
        "remote_path": "/data/old",
        "deleted": True,
    }


def test_storage_usage_reads_live_detail_for_created_regions() -> None:
    """Created volumes report live space and inode usage from ``/detail``."""
    seen: list[httpx.Request] = []

    with _client(_router(seen=seen)) as client:
        rows = nfs_handler.storage_usage(client)

    detail_requests = [request for request in seen if request.url.path == "/api/v1/file_storage/detail"]
    assert len(detail_requests) == 1
    detail_request = detail_requests[0]
    assert detail_request.method == "GET"
    assert detail_request.url.host == REGION_HOST
    assert detail_request.url.port == REGION_PORT
    assert detail_request.headers["authorization"] == TOKEN

    assert rows[0] == {
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

    # An uninitialised volume is listed, never queried, and shows no usage.
    assert rows[1]["sign"] == "west-X"
    assert rows[1]["status"] == "uninitialized"
    assert rows[1]["total_space"] is None
    assert rows[1]["used_space"] is None
    assert rows[1]["free_space"] is None
    assert rows[1]["used_percent"] is None
    assert rows[1]["total_inodes"] is None
    assert rows[1]["used_inodes"] is None
    assert rows[1]["free_inodes"] is None
    assert rows[1]["usage_error"] is None
    assert rows[1]["free_allowance"] == 21474836480
    assert rows[1]["max_size"] == 54975581388800


def test_storage_usage_continues_when_one_detail_call_fails() -> None:
    """A rejected detail call is recorded without hiding the other regions."""
    regions = [
        REGIONS[0],
        {
            **REGIONS[0],
            "sign": "sh-A1",
            "name": "上海A区",
            "export_addr_1": "region-sha1-fs.autodl.com",
        },
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.autodl.com":
            return _success(regions)
        if request.url.path == "/api/v1/file_storage/detail":
            if request.url.host == REGION_HOST:
                return httpx.Response(200, json={"code": "BadRequest", "data": None, "msg": "detail exploded"})
            return _success(DETAIL)
        return _success(1)

    with _client(handler) as client:
        rows = nfs_handler.storage_usage(client)

    assert rows[0]["sign"] == "bj-B1"
    assert rows[0]["usage_error"] is not None
    assert "detail exploded" in str(rows[0]["usage_error"])
    assert rows[0]["total_space"] is None
    assert rows[0]["used_percent"] is None
    assert rows[0]["free_allowance"] == 21474836480

    assert rows[1]["sign"] == "sh-A1"
    assert rows[1]["usage_error"] is None
    assert rows[1]["total_space"] == DETAIL["total_space"]
    assert rows[1]["used_space"] == DETAIL["used_space"]
    assert rows[1]["used_percent"] == 7.6


def test_storage_usage_filters_by_region_case_insensitively() -> None:
    """A region filter keeps only the matching volume."""
    seen: list[httpx.Request] = []

    with _client(_router(seen=seen)) as client:
        rows = nfs_handler.storage_usage(client, region=" bj-b1 ")

    assert [row["sign"] for row in rows] == ["bj-B1"]
    assert rows[0]["total_space"] == DETAIL["total_space"]
    assert len([request for request in seen if request.url.path.endswith("/detail")]) == 1


def test_storage_usage_rejects_an_unknown_region() -> None:
    """An unknown filter lists the available signs."""
    with _client(_router()) as client:
        with pytest.raises(APIError, match="Unknown NFS region 'nowhere'.*bj-B1, west-X"):
            nfs_handler.storage_usage(client, region="nowhere")
