"""Tests for :mod:`autodl_cli.handlers.instance`, all offline."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone

import httpx
import pytest

from autodl_cli.client import APP_VERSION, AutoDLClient
from autodl_cli.errors import APIError, AuthError
from autodl_cli.handlers import _poll
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

INSTANCE_UUID = "9b384da211-e57974ef"

SNAPSHOT = {
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
    "payg_price": 1480,
    "origin_pay_price": 1560,
    "snapshot_gpu_alias_name": "RTX 3090",
    "user_define_gpu_name": "",
    "chip_corp": "nvidia",
    "machine_info_snapshot": {
        "region_name": "内蒙B区",
        "region_sign": "nm-B2",
        "gpu_type": {"name": "RTX 3090", "memory": 25769803776},
    },
}
SNAPSHOT_YUAN = {**SNAPSHOT, "payg_price": 1.48, "origin_pay_price": 1.56}

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


def test_list_instances_converts_price_fields_to_yuan() -> None:
    """Integer price fields become yuan floats; the API response is not mutated."""
    entry = {**INSTANCES[0], "payg_price": 1480, "daily_price": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        return _success(_page([entry]))

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        result = instance_handler.list_instances(client)

    assert result[0]["payg_price"] == 1.48
    assert result[0]["daily_price"] == 0.0
    assert result[0]["uuid"] == INSTANCES[0]["uuid"]
    assert entry["payg_price"] == 1480


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


def test_get_instance_requests_snapshot_endpoint() -> None:
    """The handler sends an authenticated GET with the instance UUID as a query parameter."""
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        seen["authorization"] = request.headers.get("Authorization")
        seen["app_version"] = request.headers.get("AppVersion")
        seen["body"] = request.content
        return _success(SNAPSHOT)

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        assert instance_handler.get_instance(client, INSTANCE_UUID) == SNAPSHOT_YUAN

    assert seen == {
        "method": "GET",
        "path": "/api/v1/instance/snapshot",
        "params": {"instance_uuid": INSTANCE_UUID},
        "authorization": TOKEN,
        "app_version": APP_VERSION,
        "body": b"",
    }


def test_get_instance_auth_failure_raises_auth_error() -> None:
    """An ``AuthorizeFailed`` envelope becomes an :class:`AuthError`."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"code": "AuthorizeFailed", "msg": "login timed out", "data": None, "request_id": "req-7"},
        )

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AuthError) as excinfo:
            instance_handler.get_instance(client, INSTANCE_UUID)

    assert "login timed out" in str(excinfo.value)
    assert "req-7" in str(excinfo.value)


@pytest.mark.parametrize("data", [None, [], "not-an-object"])
def test_get_instance_malformed_data_raises_api_error(data: object) -> None:
    """A successful envelope whose ``data`` is not an object is malformed."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _success(data)

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(APIError, match="malformed data"):
            instance_handler.get_instance(client, INSTANCE_UUID)


def test_list_instances_query_ignores_non_string_and_missing_fields() -> None:
    """Non-string values and missing search fields never match on their own."""
    entries = [{"uuid": 123, "name": None, "region_name": "西北B区"}]

    def handler(request: httpx.Request) -> httpx.Response:
        return _success(_page(entries))

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        assert instance_handler.list_instances(client, query="123") == []

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        assert instance_handler.list_instances(client, query="西北") == entries


SAVE_INSTANCE_UUID = "wn8vt448yq-473b14de"


def test_save_image_posts_expected_body_and_tolerates_null_data() -> None:
    """The handler trims its inputs, POSTs the console body, and ignores null data."""
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["authorization"] = request.headers.get("Authorization")
        seen["app_version"] = request.headers.get("AppVersion")
        seen["body"] = json.loads(request.content)
        return _success(None)

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        result = instance_handler.save_image(client, f" {SAVE_INSTANCE_UUID} ", " save-image-test1 ")

    assert seen == {
        "method": "POST",
        "path": "/api/v1/instance/image/save",
        "authorization": TOKEN,
        "app_version": APP_VERSION,
        "body": {
            "image_name": "save-image-test1",
            "instance_uuid": SAVE_INSTANCE_UUID,
            "try_again": False,
        },
    }
    assert result == {
        "instance_uuid": SAVE_INSTANCE_UUID,
        "image_name": "save-image-test1",
        "try_again": False,
        "saved": True,
    }


def test_save_image_forwards_try_again() -> None:
    """``try_again`` reaches the request body and the returned record."""
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return _success(None)

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        result = instance_handler.save_image(client, SAVE_INSTANCE_UUID, "retry-me", try_again=True)

    assert seen["body"] == {
        "image_name": "retry-me",
        "instance_uuid": SAVE_INSTANCE_UUID,
        "try_again": True,
    }
    assert result["try_again"] is True


@pytest.mark.parametrize(
    ("instance_id", "image_name", "message"),
    [
        ("", "name", "instance_id must not be empty"),
        ("   ", "name", "instance_id must not be empty"),
        (SAVE_INSTANCE_UUID, "", "image_name must not be empty"),
        (SAVE_INSTANCE_UUID, "  ", "image_name must not be empty"),
    ],
)
def test_save_image_rejects_blank_arguments(instance_id: str, image_name: str, message: str) -> None:
    """Blank inputs fail before any request is sent."""
    with pytest.raises(ValueError, match=message):
        with AutoDLClient(TOKEN, transport=httpx.MockTransport(lambda request: pytest.fail("no request"))) as client:
            instance_handler.save_image(client, instance_id, image_name)


def test_save_image_auth_failure_raises_auth_error() -> None:
    """An ``AuthorizeFailed`` envelope becomes an :class:`AuthError`."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"code": "AuthorizeFailed", "msg": "login timed out", "data": None, "request_id": "req-8"},
        )

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AuthError, match="login timed out"):
            instance_handler.save_image(client, SAVE_INSTANCE_UUID, "name")


def test_save_image_failure_raises_api_error() -> None:
    """A non-success envelope becomes an :class:`APIError`."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": "ImageNameExists", "msg": "duplicate name", "data": None})

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(APIError, match="duplicate name"):
            instance_handler.save_image(client, SAVE_INSTANCE_UUID, "name")


POWER_OFF_INSTANCE_UUID = "po8vt448yq-473b14de"


def test_power_off_posts_expected_body_and_tolerates_null_data() -> None:
    """The handler trims the UUID, POSTs the console body, and ignores null data."""
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["authorization"] = request.headers.get("Authorization")
        seen["app_version"] = request.headers.get("AppVersion")
        seen["body"] = json.loads(request.content)
        return _success(None)

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        result = instance_handler.power_off(client, f" {POWER_OFF_INSTANCE_UUID} ")

    assert seen == {
        "method": "POST",
        "path": "/api/v1/instance/power_off",
        "authorization": TOKEN,
        "app_version": APP_VERSION,
        "body": {"instance_uuid": POWER_OFF_INSTANCE_UUID},
    }
    assert result == {
        "instance_uuid": POWER_OFF_INSTANCE_UUID,
        "powered_off": True,
    }


@pytest.mark.parametrize("instance_id", ["", "   "])
def test_power_off_rejects_blank_instance_id(instance_id: str) -> None:
    """A blank UUID fails before any request is sent."""
    with pytest.raises(ValueError, match="instance_id must not be empty"):
        with AutoDLClient(TOKEN, transport=httpx.MockTransport(lambda request: pytest.fail("no request"))) as client:
            instance_handler.power_off(client, instance_id)


def test_power_off_auth_failure_raises_auth_error() -> None:
    """An ``AuthorizeFailed`` envelope becomes an :class:`AuthError`."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"code": "AuthorizeFailed", "msg": "login timed out", "data": None, "request_id": "req-10"},
        )

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AuthError, match="login timed out"):
            instance_handler.power_off(client, POWER_OFF_INSTANCE_UUID)


def test_power_off_failure_raises_api_error() -> None:
    """A non-success envelope becomes an :class:`APIError`."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": "InstanceNotRunning", "msg": "already stopped", "data": None})

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(APIError, match="already stopped"):
            instance_handler.power_off(client, POWER_OFF_INSTANCE_UUID)


SCHEDULE_INSTANCE_UUID = "sd2f81kqzv-7a35c9e1"


def test_schedule_shutdown_posts_expected_body_and_tolerates_null_data() -> None:
    """The handler trims the UUID, treats naive times as UTC+8, and ignores null data."""
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["authorization"] = request.headers.get("Authorization")
        seen["app_version"] = request.headers.get("AppVersion")
        seen["body"] = json.loads(request.content)
        return _success(None)

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        result = instance_handler.schedule_shutdown(
            client,
            f" {SCHEDULE_INSTANCE_UUID} ",
            shutdown_at=datetime(2026, 11, 13, 0, 0),
        )

    assert seen == {
        "method": "POST",
        "path": "/api/v1/instance/timed/shutdown",
        "authorization": TOKEN,
        "app_version": APP_VERSION,
        "body": {
            "instance_uuid": SCHEDULE_INSTANCE_UUID,
            "shutdown_at": "2026-11-13 00:00",
        },
    }
    assert result == {
        "instance_uuid": SCHEDULE_INSTANCE_UUID,
        "shutdown_at": "2026-11-13 00:00",
    }


def test_schedule_shutdown_converts_aware_time_to_utc_plus_8() -> None:
    """An aware time from another offset is converted to Beijing time."""
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return _success(None)

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        result = instance_handler.schedule_shutdown(
            client,
            SCHEDULE_INSTANCE_UUID,
            shutdown_at=datetime(2026, 11, 12, 18, 0, tzinfo=timezone.utc),
        )

    body = seen["body"]
    assert isinstance(body, dict)
    assert body["shutdown_at"] == "2026-11-13 02:00"
    assert result["shutdown_at"] == "2026-11-13 02:00"


@pytest.mark.parametrize("instance_id", ["", "   "])
def test_schedule_shutdown_rejects_blank_instance_id(instance_id: str) -> None:
    """A blank UUID fails before any request is sent."""
    with pytest.raises(ValueError, match="instance_id must not be empty"):
        with AutoDLClient(TOKEN, transport=httpx.MockTransport(lambda request: pytest.fail("no request"))) as client:
            instance_handler.schedule_shutdown(
                client,
                instance_id,
                shutdown_at=datetime(2026, 11, 13, 0, 0),
            )


def test_schedule_shutdown_auth_failure_raises_auth_error() -> None:
    """An ``AuthorizeFailed`` envelope becomes an :class:`AuthError`."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"code": "AuthorizeFailed", "msg": "login timed out", "data": None, "request_id": "req-16"},
        )

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AuthError, match="login timed out"):
            instance_handler.schedule_shutdown(
                client,
                SCHEDULE_INSTANCE_UUID,
                shutdown_at=datetime(2026, 11, 13, 0, 0),
            )


def test_schedule_shutdown_failure_raises_api_error() -> None:
    """A non-success envelope becomes an :class:`APIError`."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": "InstanceNotFound", "msg": "no such instance", "data": None})

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(APIError, match="no such instance"):
            instance_handler.schedule_shutdown(
                client,
                SCHEDULE_INSTANCE_UUID,
                shutdown_at=datetime(2026, 11, 13, 0, 0),
            )


def test_cancel_scheduled_shutdown_posts_null_body_and_tolerates_null_data() -> None:
    """Cancelling sends JSON null for ``shutdown_at`` and ignores null data."""
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["authorization"] = request.headers.get("Authorization")
        seen["app_version"] = request.headers.get("AppVersion")
        seen["body"] = json.loads(request.content)
        seen["content"] = request.content
        return _success(None)

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        result = instance_handler.cancel_scheduled_shutdown(client, f" {SCHEDULE_INSTANCE_UUID} ")

    assert b'"shutdown_at":null' in seen.pop("content")

    assert seen == {
        "method": "POST",
        "path": "/api/v1/instance/timed/shutdown",
        "authorization": TOKEN,
        "app_version": APP_VERSION,
        "body": {
            "instance_uuid": SCHEDULE_INSTANCE_UUID,
            "shutdown_at": None,
        },
    }
    assert result == {
        "instance_uuid": SCHEDULE_INSTANCE_UUID,
        "shutdown_scheduled": False,
    }


@pytest.mark.parametrize("instance_id", ["", "   "])
def test_cancel_scheduled_shutdown_rejects_blank_instance_id(instance_id: str) -> None:
    """A blank UUID fails before any request is sent."""
    with pytest.raises(ValueError, match="instance_id must not be empty"):
        with AutoDLClient(TOKEN, transport=httpx.MockTransport(lambda request: pytest.fail("no request"))) as client:
            instance_handler.cancel_scheduled_shutdown(client, instance_id)


def test_cancel_scheduled_shutdown_auth_failure_raises_auth_error() -> None:
    """An ``AuthorizeFailed`` envelope becomes an :class:`AuthError`."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"code": "AuthorizeFailed", "msg": "login timed out", "data": None, "request_id": "req-17"},
        )

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AuthError, match="login timed out"):
            instance_handler.cancel_scheduled_shutdown(client, SCHEDULE_INSTANCE_UUID)


def test_cancel_scheduled_shutdown_failure_raises_api_error() -> None:
    """A non-success envelope becomes an :class:`APIError`."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": "InstanceNotFound", "msg": "no such instance", "data": None})

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(APIError, match="no such instance"):
            instance_handler.cancel_scheduled_shutdown(client, SCHEDULE_INSTANCE_UUID)


RESET_INSTANCE_UUID = "rs5tb83nqk-2e71a4c9"


def test_reset_instance_posts_expected_body_and_tolerates_null_data() -> None:
    """The handler trims the UUID, POSTs the console body, and ignores null data."""
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["authorization"] = request.headers.get("Authorization")
        seen["app_version"] = request.headers.get("AppVersion")
        seen["body"] = json.loads(request.content)
        return _success(None)

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        result = instance_handler.reset_instance(client, f" {RESET_INSTANCE_UUID} ")

    assert seen == {
        "method": "POST",
        "path": "/api/v1/instance/init",
        "authorization": TOKEN,
        "app_version": APP_VERSION,
        "body": {"instance_uuid": RESET_INSTANCE_UUID},
    }
    assert result == {
        "instance_uuid": RESET_INSTANCE_UUID,
        "reset": True,
    }


@pytest.mark.parametrize("instance_id", ["", "   "])
def test_reset_instance_rejects_blank_instance_id(instance_id: str) -> None:
    """A blank UUID fails before any request is sent."""
    with pytest.raises(ValueError, match="instance_id must not be empty"):
        with AutoDLClient(TOKEN, transport=httpx.MockTransport(lambda request: pytest.fail("no request"))) as client:
            instance_handler.reset_instance(client, instance_id)


def test_reset_instance_auth_failure_raises_auth_error() -> None:
    """An ``AuthorizeFailed`` envelope becomes an :class:`AuthError`."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"code": "AuthorizeFailed", "msg": "login timed out", "data": None, "request_id": "req-11"},
        )

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AuthError, match="login timed out"):
            instance_handler.reset_instance(client, RESET_INSTANCE_UUID)


def test_reset_instance_failure_raises_api_error() -> None:
    """A non-success envelope becomes an :class:`APIError`."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": "InstanceNotFound", "msg": "no such instance", "data": None})

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(APIError, match="no such instance"):
            instance_handler.reset_instance(client, RESET_INSTANCE_UUID)


CHANGE_IMAGE_INSTANCE_UUID = "ch5mk72pqr-8c31f0d4"
CHANGE_IMAGE_UUID = "base-image-ec1e9vdbd3"


def test_change_image_posts_expected_body_and_tolerates_null_data() -> None:
    """The handler trims both UUIDs, POSTs the console body, and ignores null data."""
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["authorization"] = request.headers.get("Authorization")
        seen["app_version"] = request.headers.get("AppVersion")
        seen["body"] = json.loads(request.content)
        return _success(None)

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        result = instance_handler.change_image(
            client,
            f" {CHANGE_IMAGE_INSTANCE_UUID} ",
            f" {CHANGE_IMAGE_UUID} ",
        )

    assert seen == {
        "method": "POST",
        "path": "/api/v1/instance/change_image",
        "authorization": TOKEN,
        "app_version": APP_VERSION,
        "body": {
            "instance_uuid": CHANGE_IMAGE_INSTANCE_UUID,
            "base_image_uuid": CHANGE_IMAGE_UUID,
        },
    }
    assert result == {
        "instance_uuid": CHANGE_IMAGE_INSTANCE_UUID,
        "base_image_uuid": CHANGE_IMAGE_UUID,
        "image_changed": True,
    }


@pytest.mark.parametrize("instance_id", ["", "   "])
def test_change_image_rejects_blank_instance_id(instance_id: str) -> None:
    """A blank instance UUID fails before any request is sent."""
    with pytest.raises(ValueError, match="instance_id must not be empty"):
        with AutoDLClient(TOKEN, transport=httpx.MockTransport(lambda request: pytest.fail("no request"))) as client:
            instance_handler.change_image(client, instance_id, CHANGE_IMAGE_UUID)


@pytest.mark.parametrize("image_uuid", ["", "   "])
def test_change_image_rejects_blank_image_uuid(image_uuid: str) -> None:
    """A blank base-image UUID fails before any request is sent."""
    with pytest.raises(ValueError, match="base_image_uuid must not be empty"):
        with AutoDLClient(TOKEN, transport=httpx.MockTransport(lambda request: pytest.fail("no request"))) as client:
            instance_handler.change_image(client, CHANGE_IMAGE_INSTANCE_UUID, image_uuid)


def test_change_image_auth_failure_raises_auth_error() -> None:
    """An ``AuthorizeFailed`` envelope becomes an :class:`AuthError`."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"code": "AuthorizeFailed", "msg": "login timed out", "data": None, "request_id": "req-12"},
        )

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AuthError, match="login timed out"):
            instance_handler.change_image(client, CHANGE_IMAGE_INSTANCE_UUID, CHANGE_IMAGE_UUID)


def test_change_image_failure_raises_api_error() -> None:
    """A non-success envelope becomes an :class:`APIError`."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": "InstanceNotShutdown", "msg": "power off first", "data": None})

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(APIError, match="power off first"):
            instance_handler.change_image(client, CHANGE_IMAGE_INSTANCE_UUID, CHANGE_IMAGE_UUID)


RENAME_INSTANCE_UUID = "rn4me8k2qp-1b93c7d0"
RENAME_NAME = "AutoDL-CLI-Rename-Test"


def test_rename_instance_puts_expected_body_and_tolerates_null_data() -> None:
    """The handler trims both inputs, PUTs the console body, and ignores null data."""
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["authorization"] = request.headers.get("Authorization")
        seen["app_version"] = request.headers.get("AppVersion")
        seen["body"] = json.loads(request.content)
        return _success(None)

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        result = instance_handler.rename_instance(
            client,
            f" {RENAME_INSTANCE_UUID} ",
            f" {RENAME_NAME} ",
        )

    assert seen == {
        "method": "PUT",
        "path": "/api/v1/instance/name",
        "authorization": TOKEN,
        "app_version": APP_VERSION,
        "body": {
            "instance_name": RENAME_NAME,
            "instance_uuid": RENAME_INSTANCE_UUID,
        },
    }
    assert result == {
        "instance_uuid": RENAME_INSTANCE_UUID,
        "instance_name": RENAME_NAME,
        "renamed": True,
    }


@pytest.mark.parametrize("instance_id", ["", "   "])
def test_rename_instance_rejects_blank_instance_id(instance_id: str) -> None:
    """A blank instance UUID fails before any request is sent."""
    with pytest.raises(ValueError, match="instance_id must not be empty"):
        with AutoDLClient(TOKEN, transport=httpx.MockTransport(lambda request: pytest.fail("no request"))) as client:
            instance_handler.rename_instance(client, instance_id, RENAME_NAME)


@pytest.mark.parametrize("instance_name", ["", "   "])
def test_rename_instance_rejects_blank_instance_name(instance_name: str) -> None:
    """A blank instance name fails before any request is sent."""
    with pytest.raises(ValueError, match="instance_name must not be empty"):
        with AutoDLClient(TOKEN, transport=httpx.MockTransport(lambda request: pytest.fail("no request"))) as client:
            instance_handler.rename_instance(client, RENAME_INSTANCE_UUID, instance_name)


def test_rename_instance_auth_failure_raises_auth_error() -> None:
    """An ``AuthorizeFailed`` envelope becomes an :class:`AuthError`."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"code": "AuthorizeFailed", "msg": "login timed out", "data": None, "request_id": "req-14"},
        )

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AuthError, match="login timed out"):
            instance_handler.rename_instance(client, RENAME_INSTANCE_UUID, RENAME_NAME)


def test_rename_instance_failure_raises_api_error() -> None:
    """A non-success envelope becomes an :class:`APIError`."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": "InstanceNotFound", "msg": "no such instance", "data": None})

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(APIError, match="no such instance"):
            instance_handler.rename_instance(client, RENAME_INSTANCE_UUID, RENAME_NAME)


POWER_ON_INSTANCE_UUID = "on7kf92mzu-4a18b0c3"


def test_power_on_posts_expected_body_and_tolerates_null_data() -> None:
    """The handler trims the UUID, POSTs the console body, and ignores null data."""
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["authorization"] = request.headers.get("Authorization")
        seen["app_version"] = request.headers.get("AppVersion")
        seen["body"] = json.loads(request.content)
        return _success(None)

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        result = instance_handler.power_on(client, f" {POWER_ON_INSTANCE_UUID} ")

    assert seen == {
        "method": "POST",
        "path": "/api/v1/instance/power_on",
        "authorization": TOKEN,
        "app_version": APP_VERSION,
        "body": {"instance_uuid": POWER_ON_INSTANCE_UUID},
    }
    assert result == {
        "instance_uuid": POWER_ON_INSTANCE_UUID,
        "powered_on": True,
        "non_gpu": False,
    }


def test_power_on_non_gpu_sends_the_no_gpu_payload() -> None:
    """``non_gpu=True`` adds the console's CPU-only start payload."""
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return _success(None)

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        result = instance_handler.power_on(client, POWER_ON_INSTANCE_UUID, non_gpu=True)

    assert seen["body"] == {"instance_uuid": POWER_ON_INSTANCE_UUID, "payload": "non_gpu"}
    assert result == {
        "instance_uuid": POWER_ON_INSTANCE_UUID,
        "powered_on": True,
        "non_gpu": True,
    }


@pytest.mark.parametrize("instance_id", ["", "   "])
def test_power_on_rejects_blank_instance_id(instance_id: str) -> None:
    """A blank UUID fails before any request is sent."""
    with pytest.raises(ValueError, match="instance_id must not be empty"):
        with AutoDLClient(TOKEN, transport=httpx.MockTransport(lambda request: pytest.fail("no request"))) as client:
            instance_handler.power_on(client, instance_id)


def test_power_on_auth_failure_raises_auth_error() -> None:
    """An ``AuthorizeFailed`` envelope becomes an :class:`AuthError`."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"code": "AuthorizeFailed", "msg": "login timed out", "data": None, "request_id": "req-11"},
        )

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AuthError, match="login timed out"):
            instance_handler.power_on(client, POWER_ON_INSTANCE_UUID)


def test_power_on_failure_raises_api_error() -> None:
    """A non-success envelope becomes an :class:`APIError`."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": "InstanceNotStopped", "msg": "already running", "data": None})

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(APIError, match="already running"):
            instance_handler.power_on(client, POWER_ON_INSTANCE_UUID)


RELEASE_INSTANCE_UUID = "rl3qx71mer-9d05c2f8"


def test_release_instance_posts_expected_body_and_tolerates_null_data() -> None:
    """The handler trims the UUID, POSTs the console body, and ignores null data."""
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["authorization"] = request.headers.get("Authorization")
        seen["app_version"] = request.headers.get("AppVersion")
        seen["body"] = json.loads(request.content)
        return _success(None)

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        result = instance_handler.release_instance(client, f" {RELEASE_INSTANCE_UUID} ")

    assert seen == {
        "method": "POST",
        "path": "/api/v1/instance/release",
        "authorization": TOKEN,
        "app_version": APP_VERSION,
        "body": {"instance_uuid": RELEASE_INSTANCE_UUID},
    }
    assert result == {
        "instance_uuid": RELEASE_INSTANCE_UUID,
        "released": True,
    }


@pytest.mark.parametrize("instance_id", ["", "   "])
def test_release_instance_rejects_blank_instance_id(instance_id: str) -> None:
    """A blank UUID fails before any request is sent."""
    with pytest.raises(ValueError, match="instance_id must not be empty"):
        with AutoDLClient(TOKEN, transport=httpx.MockTransport(lambda request: pytest.fail("no request"))) as client:
            instance_handler.release_instance(client, instance_id)


def test_release_instance_auth_failure_raises_auth_error() -> None:
    """An ``AuthorizeFailed`` envelope becomes an :class:`AuthError`."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"code": "AuthorizeFailed", "msg": "login timed out", "data": None, "request_id": "req-12"},
        )

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AuthError, match="login timed out"):
            instance_handler.release_instance(client, RELEASE_INSTANCE_UUID)


def test_release_instance_failure_raises_api_error() -> None:
    """A non-success envelope becomes an :class:`APIError`."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": "InstanceNotFound", "msg": "no such instance", "data": None})

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(APIError, match="no such instance"):
            instance_handler.release_instance(client, RELEASE_INSTANCE_UUID)


MACHINE_ID = "1c0641804d"
BASE_IMAGE_UUID = "base-image-ee43618uo7"
PRIVATE_IMAGE_UUID = "image-abcd1234"
NEW_INSTANCE_UUID = "1c0641804d-de35343b"

CREATE_BODY = {
    "instance_info": {
        "machine_id": MACHINE_ID,
        "charge_type": "payg",
        "req_gpu_amount": 2,
        "base_image_uuid": BASE_IMAGE_UUID,
        "private_image_uuid": "",
        "reproduction_uuid": "",
        "cg_application_uuid": "",
        "cg_application_info": {
            "image_name": "",
            "current_version_id": 0,
            "current_version": "",
            "image_id": 0,
        },
        "instance_name": "trainer",
        "expand_data_disk": 50,
        "reproduction_id": 0,
    },
    "price_info": {
        "coupon_id_list": [],
        "machine_id": MACHINE_ID,
        "charge_type": "payg",
        "duration": 1,
        "num": 1,
        "expand_data_disk": 50,
    },
}


def test_create_instance_posts_console_body_and_unwraps_uuid() -> None:
    """The handler trims inputs, POSTs the captured body, and returns a flat record."""
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["authorization"] = request.headers.get("Authorization")
        seen["app_version"] = request.headers.get("AppVersion")
        seen["body"] = json.loads(request.content)
        return _success(NEW_INSTANCE_UUID)

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        result = instance_handler.create_instance(
            client,
            machine_id=f" {MACHINE_ID} ",
            base_image_uuid=BASE_IMAGE_UUID,
            gpu_amount=2,
            instance_name=" trainer ",
            expand_data_disk=50,
        )

    assert seen == {
        "method": "POST",
        "path": "/api/v1/order/instance/create/payg",
        "authorization": TOKEN,
        "app_version": APP_VERSION,
        "body": CREATE_BODY,
    }
    assert result == {
        "instance_uuid": NEW_INSTANCE_UUID,
        "machine_id": MACHINE_ID,
        "gpu_amount": 2,
        "charge_type": "payg",
        "base_image_uuid": BASE_IMAGE_UUID,
        "private_image_uuid": "",
        "instance_name": "trainer",
        "expand_data_disk": 50,
    }


def test_create_instance_private_image_variant() -> None:
    """A private-image order sends that UUID and leaves the base image blank."""
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return _success(NEW_INSTANCE_UUID)

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        result = instance_handler.create_instance(
            client,
            machine_id=MACHINE_ID,
            private_image_uuid=PRIVATE_IMAGE_UUID,
        )

    body = seen["body"]
    assert isinstance(body, dict)
    assert body["instance_info"]["base_image_uuid"] == ""
    assert body["instance_info"]["private_image_uuid"] == PRIVATE_IMAGE_UUID
    assert body["instance_info"]["req_gpu_amount"] == 1
    assert body["instance_info"]["instance_name"] == ""
    assert body["instance_info"]["expand_data_disk"] == 0
    assert body["price_info"]["duration"] == 1
    assert body["price_info"]["num"] == 1
    assert result["private_image_uuid"] == PRIVATE_IMAGE_UUID


@pytest.mark.parametrize("data", [None, 123, {"uuid": NEW_INSTANCE_UUID}, ["x"], "", "   "])
def test_create_instance_malformed_uuid_raises_api_error(data: object) -> None:
    """A successful envelope whose ``data`` is not a non-empty string is malformed."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _success(data)

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(APIError, match="malformed data"):
            instance_handler.create_instance(client, machine_id=MACHINE_ID, base_image_uuid=BASE_IMAGE_UUID)


def test_create_instance_failure_raises_api_error() -> None:
    """A non-success envelope becomes an :class:`APIError`."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": "MachineNotEnoughGpu", "msg": "no capacity", "data": None})

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(APIError, match="no capacity"):
            instance_handler.create_instance(client, machine_id=MACHINE_ID, base_image_uuid=BASE_IMAGE_UUID)


def test_create_instance_auth_failure_raises_auth_error() -> None:
    """An ``AuthorizeFailed`` envelope becomes an :class:`AuthError`."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"code": "AuthorizeFailed", "msg": "login timed out", "data": None, "request_id": "req-13"},
        )

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AuthError, match="login timed out"):
            instance_handler.create_instance(client, machine_id=MACHINE_ID, base_image_uuid=BASE_IMAGE_UUID)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"machine_id": "", "base_image_uuid": BASE_IMAGE_UUID}, "machine_id must not be empty"),
        ({"machine_id": "   ", "base_image_uuid": BASE_IMAGE_UUID}, "machine_id must not be empty"),
        (
            {"machine_id": MACHINE_ID, "base_image_uuid": BASE_IMAGE_UUID, "gpu_amount": 0},
            "gpu_amount must be at least 1",
        ),
        (
            {"machine_id": MACHINE_ID, "base_image_uuid": BASE_IMAGE_UUID, "gpu_amount": -2},
            "gpu_amount must be at least 1",
        ),
        (
            {"machine_id": MACHINE_ID, "base_image_uuid": BASE_IMAGE_UUID, "gpu_amount": True},
            "gpu_amount must be at least 1",
        ),
        (
            {"machine_id": MACHINE_ID, "base_image_uuid": BASE_IMAGE_UUID, "expand_data_disk": -1},
            "expand_data_disk must not be negative",
        ),
        (
            {"machine_id": MACHINE_ID, "base_image_uuid": BASE_IMAGE_UUID, "expand_data_disk": True},
            "expand_data_disk must not be negative",
        ),
        (
            {"machine_id": MACHINE_ID, "base_image_uuid": BASE_IMAGE_UUID, "private_image_uuid": PRIVATE_IMAGE_UUID},
            "exactly one of base_image_uuid and private_image_uuid must be set",
        ),
        (
            {"machine_id": MACHINE_ID, "base_image_uuid": "  ", "private_image_uuid": "  "},
            "exactly one of base_image_uuid and private_image_uuid must be set",
        ),
    ],
)
def test_create_instance_rejects_invalid_arguments(kwargs: dict[str, object], message: str) -> None:
    """Invalid order parameters fail before any request is sent."""
    with pytest.raises(ValueError, match=message):
        with AutoDLClient(TOKEN, transport=httpx.MockTransport(lambda request: pytest.fail("no request"))) as client:
            instance_handler.create_instance(client, **kwargs)


CLONE_SOURCE_UUID = "71f24fb92a-e99de0d2"
CLONE_MACHINE_ID = "eb534b8ca9"
CLONE_BASE_IMAGE_UUID = "base-image-ee43618uo7"
CLONE_PRIVATE_IMAGE_UUID = "image-abcd1234"
CLONE_NEW_UUID = "eb534b8ca9-0a1b2c3d"

CLONE_BODY = {
    "instance_uuid": CLONE_SOURCE_UUID,
    "instance_info": {
        "machine_id": CLONE_MACHINE_ID,
        "charge_type": "payg",
        "req_gpu_amount": 1,
        "base_image_uuid": CLONE_BASE_IMAGE_UUID,
        "instance_name": "",
        "private_image_uuid": "",
        "reproduction_uuid": "",
        "cg_application_uuid": "",
        "cg_application_info": {},
        "expand_data_disk": 0,
        "copy_data_disk_after_clone": True,
        "keep_src_user_service_address_after_clone": False,
        "reproduction_id": 0,
        "ft_sparse": True,
    },
    "price_info": {
        "coupon_id_list": [],
        "machine_id": CLONE_MACHINE_ID,
        "charge_type": "payg",
        "duration": 1,
        "num": 1,
        "expand_data_disk": 0,
    },
}


def test_clone_instance_posts_console_body_and_unwraps_uuid() -> None:
    """The handler trims inputs, POSTs the captured body, and returns a flat record."""
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["authorization"] = request.headers.get("Authorization")
        seen["app_version"] = request.headers.get("AppVersion")
        seen["body"] = json.loads(request.content)
        return _success(CLONE_NEW_UUID)

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        result = instance_handler.clone_instance(
            client,
            f" {CLONE_SOURCE_UUID} ",
            machine_id=f" {CLONE_MACHINE_ID} ",
            base_image_uuid=CLONE_BASE_IMAGE_UUID,
        )

    assert seen == {
        "method": "POST",
        "path": "/api/v1/order/instance/clone/payg",
        "authorization": TOKEN,
        "app_version": APP_VERSION,
        "body": CLONE_BODY,
    }
    assert result == {
        "instance_uuid": CLONE_NEW_UUID,
        "source_instance_uuid": CLONE_SOURCE_UUID,
        "machine_id": CLONE_MACHINE_ID,
        "gpu_amount": 1,
        "charge_type": "payg",
        "base_image_uuid": CLONE_BASE_IMAGE_UUID,
        "private_image_uuid": "",
        "instance_name": "",
        "expand_data_disk": 0,
        "copy_data_disk": True,
        "keep_src_user_service_address": False,
    }


def test_clone_instance_forwards_copy_and_keep_flags() -> None:
    """The copy/keep switches, GPU count, name, and disk size reach the body."""
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return _success(CLONE_NEW_UUID)

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        result = instance_handler.clone_instance(
            client,
            CLONE_SOURCE_UUID,
            machine_id=CLONE_MACHINE_ID,
            base_image_uuid=CLONE_BASE_IMAGE_UUID,
            gpu_amount=2,
            instance_name=" copy ",
            expand_data_disk=30,
            copy_data_disk=False,
            keep_src_user_service_address=True,
        )

    body = seen["body"]
    assert isinstance(body, dict)
    assert body["instance_info"]["req_gpu_amount"] == 2
    assert body["instance_info"]["instance_name"] == "copy"
    assert body["instance_info"]["expand_data_disk"] == 30
    assert body["instance_info"]["copy_data_disk_after_clone"] is False
    assert body["instance_info"]["keep_src_user_service_address_after_clone"] is True
    assert body["price_info"]["expand_data_disk"] == 30
    assert result == {
        "instance_uuid": CLONE_NEW_UUID,
        "source_instance_uuid": CLONE_SOURCE_UUID,
        "machine_id": CLONE_MACHINE_ID,
        "gpu_amount": 2,
        "charge_type": "payg",
        "base_image_uuid": CLONE_BASE_IMAGE_UUID,
        "private_image_uuid": "",
        "instance_name": "copy",
        "expand_data_disk": 30,
        "copy_data_disk": False,
        "keep_src_user_service_address": True,
    }


def test_clone_instance_private_image_variant() -> None:
    """A private-image clone sends that UUID and leaves the base image blank."""
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return _success(CLONE_NEW_UUID)

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        result = instance_handler.clone_instance(
            client,
            CLONE_SOURCE_UUID,
            machine_id=CLONE_MACHINE_ID,
            private_image_uuid=CLONE_PRIVATE_IMAGE_UUID,
        )

    body = seen["body"]
    assert isinstance(body, dict)
    assert body["instance_info"]["base_image_uuid"] == ""
    assert body["instance_info"]["private_image_uuid"] == CLONE_PRIVATE_IMAGE_UUID
    assert result["base_image_uuid"] == ""
    assert result["private_image_uuid"] == CLONE_PRIVATE_IMAGE_UUID


@pytest.mark.parametrize("data", [None, 123, {"uuid": CLONE_NEW_UUID}, ["x"], "", "   "])
def test_clone_instance_malformed_uuid_raises_api_error(data: object) -> None:
    """A successful envelope whose ``data`` is not a non-empty string is malformed."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _success(data)

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(APIError, match="malformed data"):
            instance_handler.clone_instance(
                client,
                CLONE_SOURCE_UUID,
                machine_id=CLONE_MACHINE_ID,
                base_image_uuid=CLONE_BASE_IMAGE_UUID,
            )


def test_clone_instance_failure_raises_api_error() -> None:
    """A non-success envelope becomes an :class:`APIError`."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": "MachineNotEnoughGpu", "msg": "no capacity", "data": None})

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(APIError, match="no capacity"):
            instance_handler.clone_instance(
                client,
                CLONE_SOURCE_UUID,
                machine_id=CLONE_MACHINE_ID,
                base_image_uuid=CLONE_BASE_IMAGE_UUID,
            )


def test_clone_instance_auth_failure_raises_auth_error() -> None:
    """An ``AuthorizeFailed`` envelope becomes an :class:`AuthError`."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"code": "AuthorizeFailed", "msg": "login timed out", "data": None, "request_id": "req-15"},
        )

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AuthError, match="login timed out"):
            instance_handler.clone_instance(
                client,
                CLONE_SOURCE_UUID,
                machine_id=CLONE_MACHINE_ID,
                base_image_uuid=CLONE_BASE_IMAGE_UUID,
            )


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        (
            {"instance_uuid": "", "machine_id": CLONE_MACHINE_ID, "base_image_uuid": CLONE_BASE_IMAGE_UUID},
            "instance_uuid must not be empty",
        ),
        (
            {"instance_uuid": "   ", "machine_id": CLONE_MACHINE_ID, "base_image_uuid": CLONE_BASE_IMAGE_UUID},
            "instance_uuid must not be empty",
        ),
        (
            {"instance_uuid": CLONE_SOURCE_UUID, "machine_id": "", "base_image_uuid": CLONE_BASE_IMAGE_UUID},
            "machine_id must not be empty",
        ),
        (
            {"instance_uuid": CLONE_SOURCE_UUID, "machine_id": "   ", "base_image_uuid": CLONE_BASE_IMAGE_UUID},
            "machine_id must not be empty",
        ),
        (
            {
                "instance_uuid": CLONE_SOURCE_UUID,
                "machine_id": CLONE_MACHINE_ID,
                "base_image_uuid": CLONE_BASE_IMAGE_UUID,
                "gpu_amount": 0,
            },
            "gpu_amount must be at least 1",
        ),
        (
            {
                "instance_uuid": CLONE_SOURCE_UUID,
                "machine_id": CLONE_MACHINE_ID,
                "base_image_uuid": CLONE_BASE_IMAGE_UUID,
                "gpu_amount": -2,
            },
            "gpu_amount must be at least 1",
        ),
        (
            {
                "instance_uuid": CLONE_SOURCE_UUID,
                "machine_id": CLONE_MACHINE_ID,
                "base_image_uuid": CLONE_BASE_IMAGE_UUID,
                "gpu_amount": True,
            },
            "gpu_amount must be at least 1",
        ),
        (
            {
                "instance_uuid": CLONE_SOURCE_UUID,
                "machine_id": CLONE_MACHINE_ID,
                "base_image_uuid": CLONE_BASE_IMAGE_UUID,
                "expand_data_disk": -1,
            },
            "expand_data_disk must not be negative",
        ),
        (
            {
                "instance_uuid": CLONE_SOURCE_UUID,
                "machine_id": CLONE_MACHINE_ID,
                "base_image_uuid": CLONE_BASE_IMAGE_UUID,
                "expand_data_disk": True,
            },
            "expand_data_disk must not be negative",
        ),
        (
            {
                "instance_uuid": CLONE_SOURCE_UUID,
                "machine_id": CLONE_MACHINE_ID,
                "base_image_uuid": CLONE_BASE_IMAGE_UUID,
                "private_image_uuid": CLONE_PRIVATE_IMAGE_UUID,
            },
            "exactly one of base_image_uuid and private_image_uuid must be set",
        ),
        (
            {
                "instance_uuid": CLONE_SOURCE_UUID,
                "machine_id": CLONE_MACHINE_ID,
                "base_image_uuid": "  ",
                "private_image_uuid": "  ",
            },
            "exactly one of base_image_uuid and private_image_uuid must be set",
        ),
    ],
)
def test_clone_instance_rejects_invalid_arguments(kwargs: dict[str, object], message: str) -> None:
    """Invalid clone parameters fail before any request is sent."""
    with pytest.raises(ValueError, match=message):
        with AutoDLClient(TOKEN, transport=httpx.MockTransport(lambda request: pytest.fail("no request"))) as client:
            instance_handler.clone_instance(client, **kwargs)


def test_resolve_clone_source_public_image_reads_gpu_amount_from_list() -> None:
    """A public snapshot yields the base image and the list's GPU count."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return _success(SNAPSHOT)
        seen.append(request.url.path)
        return _success(_page([{"uuid": CLONE_SOURCE_UUID, "req_gpu_amount": 3}]))

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        result = instance_handler.resolve_clone_source(client, f" {CLONE_SOURCE_UUID} ")

    assert result == {
        "instance_uuid": CLONE_SOURCE_UUID,
        "base_image_uuid": CLONE_BASE_IMAGE_UUID,
        "private_image_uuid": "",
        "gpu_amount": 3,
    }
    assert seen == ["/api/v1/instance"]


def test_resolve_clone_source_private_image_type_uses_private_uuid() -> None:
    """An explicit ``private`` image type fills ``private_image_uuid``."""
    snapshot = {
        **SNAPSHOT,
        "image": {
            **SNAPSHOT["image"],
            "image_type": "private",
            "base_image_uuid": CLONE_PRIVATE_IMAGE_UUID,
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return _success(snapshot)
        return _success(_page([{"uuid": CLONE_SOURCE_UUID, "req_gpu_amount": 1}]))

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        result = instance_handler.resolve_clone_source(client, CLONE_SOURCE_UUID)

    assert result["base_image_uuid"] == ""
    assert result["private_image_uuid"] == CLONE_PRIVATE_IMAGE_UUID


def test_resolve_clone_source_image_prefix_heuristic_uses_private_uuid() -> None:
    """An unknown image type with the ``image-`` prefix is treated as private."""
    snapshot = {
        **SNAPSHOT,
        "image": {
            **SNAPSHOT["image"],
            "image_type": "",
            "base_image_uuid": CLONE_PRIVATE_IMAGE_UUID,
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return _success(snapshot)
        return _success(_page([{"uuid": CLONE_SOURCE_UUID, "req_gpu_amount": 1}]))

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        result = instance_handler.resolve_clone_source(client, CLONE_SOURCE_UUID)

    assert result["base_image_uuid"] == ""
    assert result["private_image_uuid"] == CLONE_PRIVATE_IMAGE_UUID


def test_resolve_clone_source_missing_from_list_raises_api_error() -> None:
    """A source absent from the instance list cannot be cloned."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return _success(SNAPSHOT)
        return _success(_page([{"uuid": "different-uuid", "req_gpu_amount": 1}]))

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(APIError, match="not found in the instance list"):
            instance_handler.resolve_clone_source(client, CLONE_SOURCE_UUID)


@pytest.mark.parametrize(
    "gpu_amount",
    [None, 0, -1, True, "2"],
)
def test_resolve_clone_source_malformed_gpu_amount_raises_api_error(gpu_amount: object) -> None:
    """A missing or non-positive GPU count cannot be inherited."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return _success(SNAPSHOT)
        return _success(_page([{"uuid": CLONE_SOURCE_UUID, "req_gpu_amount": gpu_amount}]))

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(APIError, match="could not determine the GPU amount"):
            instance_handler.resolve_clone_source(client, CLONE_SOURCE_UUID)


@pytest.mark.parametrize(
    "image",
    [None, "not-an-object", [], {}, {"base_image_uuid": ""}, {"base_image_uuid": 123}],
)
def test_resolve_clone_source_malformed_image_raises_api_error(image: object) -> None:
    """A snapshot without a usable image mapping is malformed."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return _success({**SNAPSHOT, "image": image})
        pytest.fail("the instance list must not be queried for a malformed image")

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(APIError, match="malformed image data"):
            instance_handler.resolve_clone_source(client, CLONE_SOURCE_UUID)


@pytest.mark.parametrize("instance_uuid", ["", "   "])
def test_resolve_clone_source_rejects_blank_instance_uuid(instance_uuid: str) -> None:
    """A blank source UUID fails before any request is sent."""
    with pytest.raises(ValueError, match="instance_uuid must not be empty"):
        with AutoDLClient(TOKEN, transport=httpx.MockTransport(lambda request: pytest.fail("no request"))) as client:
            instance_handler.resolve_clone_source(client, instance_uuid)


REGION_LIST = [
    {
        "data_center": "westDC3",
        "region_sign": "west-B",
        "region_name": "西北B区",
        "visible": True,
        "used_for": "gpu",
    },
    {
        "data_center": "westDC3",
        "region_sign": "west-C",
        "region_name": "西北B区",
        "visible": True,
        "used_for": "gpu",
    },
]


def _machine(machine_id: str, gpu_name: str, idle: int) -> dict[str, object]:
    """Build a minimal machine record the normaliser accepts.

    :param machine_id: Machine identifier.
    :param gpu_name: GPU model name.
    :param idle: Idle GPU count.
    :returns: A machine-record mapping.
    """
    return {
        "machine_id": machine_id,
        "gpu_name": gpu_name,
        "gpu_number": 8,
        "gpu_idle_num": idle,
    }


def test_select_machine_picks_first_matching_machine_with_capacity() -> None:
    """The first matching machine with enough idle cards is returned."""
    bodies: list[dict[str, object]] = []
    machines = [
        _machine("m-other", "RTX 3080", 8),
        _machine("m-first", "RTX 3090", 2),
        _machine("m-second", "RTX 3090", 8),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/api/v1/common":
            return _success({"region_list": REGION_LIST})
        if request.method == "POST" and request.url.path == "/api/v1/user/machine/list":
            bodies.append(json.loads(request.content))
            return _success({"list": machines, "max_page": 1})
        pytest.fail(f"unexpected request {request.method} {request.url.path}")

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        selected = instance_handler.select_machine(client, region=" 西北B区 ", gpu=" RTX 3090 ", gpu_amount=2)

    assert selected["machine_id"] == "m-first"
    assert selected["gpu_idle_num"] == 2
    assert bodies == [
        {
            "charge_type": "payg",
            "region_sign": "",
            "gpu_type_name": ["RTX 3090"],
            "machine_tag_name": [],
            "gpu_idle_num": 2,
            "mount_net_disk": False,
            "instance_disk_size_order": "",
            "pay_price_order": "",
            "gpu_idle_type": "",
            "date_range": "",
            "date_from": "",
            "date_to": "",
            "page_index": 1,
            "page_size": 1000,
            "default_order": True,
            "region_sign_list": ["west-B", "west-C"],
            "cpu_arch": [],
            "chip_corp": [],
            "machine_id": "",
        }
    ]


def test_select_machine_matches_gpu_name_case_insensitively() -> None:
    """The GPU model comparison ignores surrounding space and letter case."""
    machines = [_machine("m-1", "rtx 3090", 4)]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return _success({"region_list": REGION_LIST})
        return _success({"list": machines, "max_page": 1})

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        selected = instance_handler.select_machine(client, region="west-B", gpu="RTX 3090")

    assert selected["machine_id"] == "m-1"


def test_select_machine_raises_when_no_machine_has_capacity() -> None:
    """A listing without a matching model raises a descriptive :class:`APIError`."""
    machines = [_machine("m-1", "RTX 3080", 8)]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return _success({"region_list": REGION_LIST})
        return _success({"list": machines, "max_page": 1})

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(
            APIError,
            match=r"No machine with 2 idle 'RTX 3090' GPU\(s\) in region 'west-B'",
        ):
            instance_handler.select_machine(client, region="west-B", gpu="RTX 3090", gpu_amount=2)


def test_select_machine_unknown_region_raises_value_error() -> None:
    """An unknown region surfaces the catalogue's clean :class:`ValueError`."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/api/v1/common":
            return _success({"region_list": REGION_LIST})
        pytest.fail("the machine listing must not be queried for an unknown region")

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match="Unknown region 'nowhere'"):
            instance_handler.select_machine(client, region="nowhere", gpu="RTX 3090")


@pytest.mark.parametrize(
    ("region", "gpu", "gpu_amount", "message"),
    [
        ("", "RTX 3090", 1, "region must not be empty"),
        ("  ", "RTX 3090", 1, "region must not be empty"),
        ("west-B", "", 1, "gpu must not be empty"),
        ("west-B", "   ", 1, "gpu must not be empty"),
        ("west-B", "RTX 3090", 0, "gpu_amount must be at least 1"),
        ("west-B", "RTX 3090", True, "gpu_amount must be at least 1"),
    ],
)
def test_select_machine_rejects_invalid_arguments(
    region: str,
    gpu: str,
    gpu_amount: int,
    message: str,
) -> None:
    """Blank identifiers and a non-positive GPU count fail before any request."""
    with pytest.raises(ValueError, match=message):
        with AutoDLClient(TOKEN, transport=httpx.MockTransport(lambda request: pytest.fail("no request"))) as client:
            instance_handler.select_machine(client, region=region, gpu=gpu, gpu_amount=gpu_amount)


WAIT_INSTANCE_UUID = "wait-uuid-1"


class _FakeClock:
    """Monotonic clock that advances only when a fake sleep is recorded."""

    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        """Return the current fake time.

        :returns: Seconds since the fake origin.
        """
        return self.value

    def advance(self, seconds: float) -> None:
        """Move the clock forward.

        :param seconds: Delay to add.
        """
        self.value += seconds


@pytest.fixture
def fake_poll(monkeypatch) -> tuple[_FakeClock, list[float]]:
    """Replace the shared polling clock and sleep so tests run instantly.

    :param monkeypatch: pytest's monkeypatch fixture.
    :returns: The fake clock and the recorded wait arguments.
    """
    clock = _FakeClock()
    delays: list[float] = []

    def record(seconds: float) -> None:
        delays.append(seconds)
        clock.advance(seconds)

    monkeypatch.setattr(_poll, "now", clock)
    monkeypatch.setattr(_poll, "sleep", record)
    return clock, delays


def test_wait_for_instance_returns_immediately_when_running(fake_poll) -> None:
    """An instance already running succeeds on the first poll with no sleep."""
    _, delays = fake_poll
    entry = {"uuid": WAIT_INSTANCE_UUID, "status": "running"}

    def handler(request: httpx.Request) -> httpx.Response:
        return _success(_page([entry]))

    events: list[dict[str, object]] = []
    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        result = instance_handler.wait_for_instance(
            client,
            WAIT_INSTANCE_UUID,
            interval=2.0,
            on_event=events.append,
        )

    assert result == {
        "instance_uuid": WAIT_INSTANCE_UUID,
        "status": "running",
        "waited_seconds": 0.0,
        "instance": entry,
    }
    assert events == [
        {"event": "instance_status", "instance_uuid": WAIT_INSTANCE_UUID, "status": "running"},
        {"event": "running", "instance_uuid": WAIT_INSTANCE_UUID},
    ]
    assert delays == []


def test_wait_for_instance_polls_until_running(fake_poll) -> None:
    """A creating instance is polled again after the interval until it runs."""
    _, delays = fake_poll
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        status = "creating" if len(calls) == 1 else "running"
        return _success(_page([{"uuid": WAIT_INSTANCE_UUID, "status": status}]))

    events: list[dict[str, object]] = []
    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        result = instance_handler.wait_for_instance(
            client,
            WAIT_INSTANCE_UUID,
            interval=5.0,
            on_event=events.append,
        )

    assert result["status"] == "running"
    assert result["waited_seconds"] == 5.0
    assert [event["event"] for event in events] == [
        "instance_status",
        "instance_status",
        "running",
    ]
    assert [event["status"] for event in events[:2]] == ["creating", "running"]
    assert delays == [5.0]


def test_wait_for_instance_accepts_cpu_mode_as_running(fake_poll) -> None:
    """The CPU-only start mode is ready to use and keeps its raw status."""
    entry = {"uuid": WAIT_INSTANCE_UUID, "status": "cpu"}

    def handler(request: httpx.Request) -> httpx.Response:
        return _success(_page([entry]))

    events: list[dict[str, object]] = []
    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        result = instance_handler.wait_for_instance(
            client,
            WAIT_INSTANCE_UUID,
            on_event=events.append,
        )

    assert result["status"] == "cpu"
    assert events[-1] == {"event": "running", "instance_uuid": WAIT_INSTANCE_UUID}


def test_wait_for_instance_treats_a_missing_entry_as_pending(fake_poll) -> None:
    """A missing or non-matching entry is pending and then matches by exact UUID."""
    _, delays = fake_poll
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return _success(_page([{"uuid": "different-uuid", "status": "running"}]))
        return _success(_page([{"uuid": WAIT_INSTANCE_UUID, "status": "running"}]))

    events: list[dict[str, object]] = []
    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        result = instance_handler.wait_for_instance(
            client,
            WAIT_INSTANCE_UUID,
            interval=4.0,
            on_event=events.append,
        )

    assert result["status"] == "running"
    assert [event["status"] for event in events if event["event"] == "instance_status"] == [
        "not found",
        "running",
    ]
    assert delays == [4.0]


def test_wait_for_instance_raises_when_the_instance_fails(fake_poll) -> None:
    """A failed status while waiting for running becomes an :class:`APIError`."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _success(_page([{"uuid": WAIT_INSTANCE_UUID, "status": "failed"}]))

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(APIError, match="entered status 'failed' while waiting for running"):
            instance_handler.wait_for_instance(client, WAIT_INSTANCE_UUID)


def test_wait_for_instance_failed_status_is_case_insensitive(fake_poll) -> None:
    """Mixed-case failed statuses still abort the wait."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _success(_page([{"uuid": WAIT_INSTANCE_UUID, "status": "Error"}]))

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(APIError, match="entered status 'Error'"):
            instance_handler.wait_for_instance(client, WAIT_INSTANCE_UUID)


def test_wait_for_instance_until_shutdown_succeeds(fake_poll) -> None:
    """``shutdown`` is the only success status for that target."""
    entry = {"uuid": WAIT_INSTANCE_UUID, "status": "shutdown"}

    def handler(request: httpx.Request) -> httpx.Response:
        return _success(_page([entry]))

    events: list[dict[str, object]] = []
    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        result = instance_handler.wait_for_instance(
            client,
            WAIT_INSTANCE_UUID,
            until="shutdown",
            on_event=events.append,
        )

    assert result["status"] == "shutdown"
    assert events[-1] == {"event": "shutdown", "instance_uuid": WAIT_INSTANCE_UUID}


def test_wait_for_instance_until_shutdown_raises_on_released(fake_poll) -> None:
    """A released instance cannot reach shutdown and raises :class:`APIError`."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _success(_page([{"uuid": WAIT_INSTANCE_UUID, "status": "released"}]))

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(APIError, match="while waiting for shutdown"):
            instance_handler.wait_for_instance(client, WAIT_INSTANCE_UUID, until="shutdown")


def test_wait_for_instance_until_released_accepts_a_missing_entry(fake_poll) -> None:
    """A disappeared instance counts as released."""
    events: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return _success(_page([]))

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        result = instance_handler.wait_for_instance(
            client,
            WAIT_INSTANCE_UUID,
            until="released",
            on_event=events.append,
        )

    assert result == {
        "instance_uuid": WAIT_INSTANCE_UUID,
        "status": "released",
        "waited_seconds": 0.0,
        "instance": None,
    }
    assert events == [
        {"event": "instance_status", "instance_uuid": WAIT_INSTANCE_UUID, "status": "not found"},
        {"event": "released", "instance_uuid": WAIT_INSTANCE_UUID},
    ]


def test_wait_for_instance_until_released_checks_before_failed_statuses(fake_poll) -> None:
    """``released`` is in the failed set but succeeds before that branch."""
    entry = {"uuid": WAIT_INSTANCE_UUID, "status": "released"}

    def handler(request: httpx.Request) -> httpx.Response:
        return _success(_page([entry]))

    events: list[dict[str, object]] = []
    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        result = instance_handler.wait_for_instance(
            client,
            WAIT_INSTANCE_UUID,
            until="released",
            on_event=events.append,
        )

    assert result["status"] == "released"
    assert result["instance"] == entry
    assert events[-1] == {"event": "released", "instance_uuid": WAIT_INSTANCE_UUID}


def test_wait_for_instance_times_out(fake_poll) -> None:
    """A status that never changes raises :class:`TimeoutError` with the last status."""
    _, delays = fake_poll

    def handler(request: httpx.Request) -> httpx.Response:
        return _success(_page([{"uuid": WAIT_INSTANCE_UUID, "status": "creating"}]))

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(
            TimeoutError,
            match=r"Timed out after 5s waiting for instance .* to reach running \(last status: 'creating'\)",
        ):
            instance_handler.wait_for_instance(
                client,
                WAIT_INSTANCE_UUID,
                interval=2.0,
                timeout=5.0,
            )

    assert delays == [2.0, 2.0, 2.0]


def test_wait_for_instance_zero_timeout_has_no_deadline(fake_poll) -> None:
    """``timeout=0`` keeps polling past what would be a deadline."""
    _, delays = fake_poll
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        status = "creating" if len(calls) < 3 else "running"
        return _success(_page([{"uuid": WAIT_INSTANCE_UUID, "status": status}]))

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        result = instance_handler.wait_for_instance(
            client,
            WAIT_INSTANCE_UUID,
            interval=100.0,
            timeout=0.0,
        )

    assert result["status"] == "running"
    assert result["waited_seconds"] == 200.0
    assert delays == [100.0, 100.0]


def test_wait_for_instance_retries_a_transient_error(fake_poll) -> None:
    """A 500 is retried when ``retry`` allows it, then the wait succeeds."""
    _, delays = fake_poll
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(500, json={"msg": "boom"})
        return _success(_page([{"uuid": WAIT_INSTANCE_UUID, "status": "running"}]))

    events: list[dict[str, object]] = []
    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        result = instance_handler.wait_for_instance(
            client,
            WAIT_INSTANCE_UUID,
            interval=3.0,
            retry=1,
            on_event=events.append,
        )

    assert result["status"] == "running"
    assert calls == [1, 1]
    assert events[0]["event"] == "poll_failed"
    assert events[0]["retries"] == 1
    assert events[0]["limit"] == 1
    assert "boom" in str(events[0]["error"])
    assert delays == [3.0]


def test_wait_for_instance_never_retries_auth_errors(fake_poll) -> None:
    """A 401 propagates immediately even with retries enabled."""
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(401, json={"msg": "bad token"})

    events: list[dict[str, object]] = []
    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AuthError, match="bad token"):
            instance_handler.wait_for_instance(
                client,
                WAIT_INSTANCE_UUID,
                retry=3,
                on_event=events.append,
            )

    assert calls == [1]
    assert events == []


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"until": "stopped"}, "until"),
        ({"interval": 0}, "interval"),
        ({"interval": -1}, "interval"),
        ({"interval": True}, "interval"),
        ({"timeout": -1}, "timeout"),
        ({"timeout": True}, "timeout"),
        ({"retry": -1}, "retry"),
        ({"retry": True}, "retry"),
    ],
)
def test_wait_for_instance_rejects_invalid_options(kwargs: dict[str, object], message: str) -> None:
    """Invalid wait options fail before any request is sent."""

    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("no request must be sent for invalid options")

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match=message):
            instance_handler.wait_for_instance(client, WAIT_INSTANCE_UUID, **kwargs)


@pytest.mark.parametrize("instance_id", ["", "   "])
def test_wait_for_instance_rejects_a_blank_uuid(instance_id: str) -> None:
    """A blank UUID fails before any request is sent."""

    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("no request must be sent for a blank UUID")

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match="instance_id must not be empty"):
            instance_handler.wait_for_instance(client, instance_id)
