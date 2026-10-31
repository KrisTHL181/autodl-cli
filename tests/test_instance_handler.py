"""Tests for :mod:`autodl_cli.handlers.instance`, all offline."""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from autodl_cli.client import APP_VERSION, AutoDLClient
from autodl_cli.errors import APIError, AuthError
from autodl_cli.handlers import instance as instance_handler

TOKEN = "fake-token"
INSTANCES = [
    {
        "uuid": "cs1a2b3c4d5e6f7g8h",
        "name": "",
        "status": "running",
        "region_name": "内蒙B区",
        "snapshot_gpu_alias_name": "RTX 3090",
    },
    {
        "uuid": "cs9z8y7x6w5v4u3t2s",
        "name": "trainer",
        "status": "shutdown",
        "region_name": "西北B区",
        "snapshot_gpu_alias_name": "RTX 3080 Ti",
    },
]

Handler = Callable[[httpx.Request], httpx.Response]


def _page(
    entries: list[dict[str, object]],
    *,
    page_index: int = 1,
    max_page: int = 1,
) -> dict[str, object]:
    """Build the ``data`` object of an instance-list response.

    :param entries: Instances on this page.
    :param page_index: One-based page number.
    :param max_page: Total number of pages reported by the server.
    :returns: A page mapping shaped like the real API response.
    """
    return {
        "list": entries,
        "page_index": page_index,
        "page_size": len(entries),
        "offset": 0,
        "max_page": max_page,
        "result_total": len(entries),
        "page": page_index,
    }


def _success(data: object) -> httpx.Response:
    """Build a successful API envelope.

    :param data: The ``data`` value to wrap.
    :returns: A mock HTTP response.
    """
    return httpx.Response(200, json={"code": "Success", "msg": "", "data": data, "request_id": "req-1"})


def test_list_instances_posts_expected_body() -> None:
    """The handler sends an authenticated POST with the default filter body."""
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["authorization"] = request.headers.get("Authorization")
        seen["app_version"] = request.headers.get("AppVersion")
        seen["body"] = json.loads(request.content)
        return _success(_page(INSTANCES))

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        assert instance_handler.list_instances(client) == INSTANCES

    assert seen == {
        "method": "POST",
        "path": "/api/v1/instance",
        "authorization": TOKEN,
        "app_version": APP_VERSION,
        "body": {
            "page_index": 1,
            "page_size": 100,
            "status": [],
            "charge_type": [],
            "sub_name": "",
            "unbind_sub_user": False,
        },
    }


def test_list_instances_walks_all_pages() -> None:
    """Every page up to ``max_page`` is fetched and concatenated in order."""
    seen: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page_index = json.loads(request.content)["page_index"]
        seen.append(page_index)
        if page_index == 1:
            return _success(_page(INSTANCES[:1], page_index=1, max_page=2))
        return _success(_page(INSTANCES[1:], page_index=2, max_page=2))

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        assert instance_handler.list_instances(client, page_size=1) == INSTANCES

    assert seen == [1, 2]


def test_list_instances_stops_when_server_clamps_page_index() -> None:
    """A server that clamps every page index to page 1 must not loop forever."""
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content)["page_index"])
        return _success(_page(INSTANCES, page_index=1, max_page=1))

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        assert instance_handler.list_instances(client) == INSTANCES

    assert calls == [1]


def test_list_instances_forwards_filters_on_every_page() -> None:
    """Filters reach every request, including when the caller passes iterators."""
    bodies: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        page_index = body["page_index"]
        entries = INSTANCES[:1] if page_index == 1 else INSTANCES[1:]
        return _success(_page(entries, page_index=page_index, max_page=2))

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        result = instance_handler.list_instances(
            client,
            page_size=25,
            statuses=iter(["running"]),
            charge_types=iter(["payg"]),
            sub_name="alice",
            unbind_sub_user=True,
        )

    assert result == INSTANCES
    assert [body["page_index"] for body in bodies] == [1, 2]
    for body in bodies:
        assert body["page_size"] == 25
        assert body["status"] == ["running"]
        assert body["charge_type"] == ["payg"]
        assert body["sub_name"] == "alice"
        assert body["unbind_sub_user"] is True


def test_list_instances_empty_result() -> None:
    """An empty list is returned instead of an error."""
    seen: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content)["page_index"])
        return _success(_page([], max_page=0))

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        assert instance_handler.list_instances(client) == []

    assert seen == [1]


def test_list_instances_rejects_non_positive_page_size() -> None:
    """A non-positive page size fails before any request is sent."""

    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("no request must be sent for an invalid page size")

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match="page_size"):
            instance_handler.list_instances(client, page_size=0)


def test_list_instances_auth_failure_raises_auth_error() -> None:
    """An ``AuthorizeFailed`` envelope becomes an :class:`AuthError` with context."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"code": "AuthorizeFailed", "msg": "login timed out", "data": None, "request_id": "req-9"},
        )

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AuthError) as excinfo:
            instance_handler.list_instances(client)

    assert "login timed out" in str(excinfo.value)
    assert "req-9" in str(excinfo.value)


@pytest.mark.parametrize("list_value", [None, "not-a-list", {"uuid": "x"}])
def test_list_instances_malformed_list_raises_api_error(list_value: object) -> None:
    """A successful envelope without a ``list`` array is malformed."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _success({"list": list_value, "max_page": 1})

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(APIError, match="malformed data"):
            instance_handler.list_instances(client)


def test_list_instances_non_object_entry_raises_api_error() -> None:
    """A ``list`` containing something other than an object is malformed."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _success({"list": ["not-an-instance"], "max_page": 1})

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(APIError, match="non-object entry"):
            instance_handler.list_instances(client)


def test_list_instances_missing_max_page_stops_after_one_page() -> None:
    """Without a usable ``max_page`` the handler returns the first page only."""
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content)["page_index"])
        return _success({"list": INSTANCES})

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        assert instance_handler.list_instances(client) == INSTANCES

    assert calls == [1]


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("CS1A2B", ["cs1a2b3c4d5e6f7g8h"]),
        ("TRAIN", ["cs9z8y7x6w5v4u3t2s"]),
        ("rtx 3080", ["cs9z8y7x6w5v4u3t2s"]),
        ("内蒙", ["cs1a2b3c4d5e6f7g8h"]),
        ("  trainer  ", ["cs9z8y7x6w5v4u3t2s"]),
        ("nobody", []),
        ("   ", ["cs1a2b3c4d5e6f7g8h", "cs9z8y7x6w5v4u3t2s"]),
    ],
)
def test_list_instances_query_filters_locally_without_reaching_the_body(
    query: str,
    expected: list[str],
) -> None:
    """The query matches UUID, name, GPU, or region, case-insensitively."""
    bodies: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return _success(_page(INSTANCES))

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        result = instance_handler.list_instances(client, query=query)

    assert [instance["uuid"] for instance in result] == expected
    assert bodies
    assert all("query" not in body for body in bodies)


def test_list_instances_query_ignores_non_string_and_missing_fields() -> None:
    """Non-string values and missing search fields never match on their own."""
    entries = [{"uuid": 123, "name": None, "region_name": "西北B区"}]

    def handler(request: httpx.Request) -> httpx.Response:
        return _success(_page(entries))

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        assert instance_handler.list_instances(client, query="123") == []

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        assert instance_handler.list_instances(client, query="西北") == entries
