"""Tests for :mod:`autodl_cli.handlers.image`, all offline."""

from __future__ import annotations

import json

import httpx
import pytest

from autodl_cli.client import AutoDLClient
from autodl_cli.errors import APIError, AuthError
from autodl_cli.handlers import _poll
from autodl_cli.handlers import image as image_handler

TOKEN = "fake-token"


def _leaf(label: str, uuid: str, *, chip_corp: str = "nvidia", cpu_arch: str = "x86") -> dict[str, object]:
    """Build one CUDA-level leaf of the image option tree.

    :param label: CUDA version label.
    :param uuid: Base-image UUID.
    :param chip_corp: Chip vendor.
    :param cpu_arch: CPU architecture.
    :returns: A leaf shaped like the real API response.
    """
    return {
        "sort": 1,
        "label": label,
        "label_name": {
            "chip_corp": chip_corp,
            "cpu_arch": cpu_arch,
            "is_desktop": False,
            "uuid": uuid,
            "v": label,
        },
        "image_uuid": "",
    }


def _python(label: str, *leaves: dict[str, object]) -> dict[str, object]:
    """Build one Python/OS-level node.

    :param label: Python/OS label.
    :param leaves: CUDA-level children.
    :returns: A node shaped like the real API response.
    """
    return {"sort": 1, "label": label, "label_name": label, "image_uuid": "", "children": list(leaves)}


def _version(label: str, *pythons: dict[str, object]) -> dict[str, object]:
    """Build one framework-version-level node.

    :param label: Framework version label.
    :param pythons: Python/OS-level children.
    :returns: A node shaped like the real API response.
    """
    return {"sort": 1, "label": label, "label_name": label, "image_uuid": "", "children": list(pythons)}


def _framework(label: str, *versions: dict[str, object]) -> dict[str, object]:
    """Build one framework-level node.

    :param label: Framework name.
    :param versions: Framework-version-level children.
    :returns: A node shaped like the real API response.
    """
    return {"sort": 1, "label": label, "label_name": label, "image_uuid": "", "children": list(versions)}


#: A small tree with two frameworks, including two CUDA leaves under one
#: Python node and a non-NVIDIA image.
IMAGE_TREE = [
    _framework(
        "PyTorch",
        _version(
            "2.8.0",
            _python("3.12(ubuntu22.04)", _leaf("12.8", "base-image-ec1e9vdbd3")),
        ),
        _version(
            "2.12.1",
            _python("3.12(ubuntu22.04)", _leaf("13.0", "base-image-ee43618uo7")),
        ),
        _version(
            "2.11.0",
            _python(
                "3.10(ubuntu22.04)",
                _leaf("5.2.0", "base-image-gc8c4e8ndm", chip_corp="mthreads"),
            ),
        ),
    ),
    _framework(
        "Miniconda",
        _version(
            "conda3",
            _python(
                "3.8(ubuntu18.04)",
                _leaf("10.0", "base-image-1e5uf433g1"),
                _leaf("11.3", "base-image-7bn8iqhkb5"),
            ),
            _python("3.10(ubuntu22.04)", _leaf("11.8", "base-image-8hkyyugih5")),
        ),
    ),
]


def _success(data: object) -> httpx.Response:
    """Build a successful API envelope.

    :param data: The ``data`` value to wrap.
    :returns: A mock HTTP response.
    """
    return httpx.Response(200, json={"code": "Success", "msg": "", "data": data, "request_id": "req-1"})


def _list(tree: object = IMAGE_TREE, **filters: object) -> list[dict[str, object]]:
    """Run :func:`list_images` against a mock transport.

    :param tree: The ``data`` value returned by the endpoint.
    :param filters: Keyword filters forwarded to the handler.
    :returns: The flattened image list.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return _success(tree)

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        return image_handler.list_images(client, **filters)


def test_list_images_posts_to_catalogue_and_flattens_tree() -> None:
    """The handler POSTs to the catalogue endpoint and keeps the API's order."""
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["authorization"] = request.headers.get("authorization")
        seen["body"] = request.content
        return _success(IMAGE_TREE)

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        images = image_handler.list_images(client)

    assert seen == {
        "method": "POST",
        "path": "/api/v1/image/all",
        "authorization": TOKEN,
        "body": b"",
    }
    assert images == [
        {
            "framework_name": "PyTorch",
            "framework_version": "2.8.0",
            "python_version": "3.12(ubuntu22.04)",
            "cuda_version": "12.8",
            "image_uuid": "base-image-ec1e9vdbd3",
            "chip_corp": "nvidia",
            "cpu_arch": "x86",
            "is_desktop": False,
        },
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
            "framework_name": "PyTorch",
            "framework_version": "2.11.0",
            "python_version": "3.10(ubuntu22.04)",
            "cuda_version": "5.2.0",
            "image_uuid": "base-image-gc8c4e8ndm",
            "chip_corp": "mthreads",
            "cpu_arch": "x86",
            "is_desktop": False,
        },
        {
            "framework_name": "Miniconda",
            "framework_version": "conda3",
            "python_version": "3.8(ubuntu18.04)",
            "cuda_version": "10.0",
            "image_uuid": "base-image-1e5uf433g1",
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
        {
            "framework_name": "Miniconda",
            "framework_version": "conda3",
            "python_version": "3.10(ubuntu22.04)",
            "cuda_version": "11.8",
            "image_uuid": "base-image-8hkyyugih5",
            "chip_corp": "nvidia",
            "cpu_arch": "x86",
            "is_desktop": False,
        },
    ]


def test_list_images_treats_missing_children_as_empty() -> None:
    """A framework without a ``children`` field contributes no images."""
    tree = [{"sort": 1, "label": "Empty", "label_name": "Empty", "image_uuid": ""}]

    assert _list(tree) == []


def test_list_images_filters_are_case_insensitive_substrings() -> None:
    """Each filter matches a fragment, ignoring case and surrounding space."""
    images = _list(frameworks=[" torch "])

    assert {image["framework_name"] for image in images} == {"PyTorch"}


def test_list_images_filters_combine_with_and() -> None:
    """Repeated values of one filter are ORed; different filters are ANDed."""
    images = _list(
        frameworks=["pytorch"],
        cuda_versions=["12", "13"],
        chip_corps=["NVIDIA"],
    )

    assert [image["image_uuid"] for image in images] == [
        "base-image-ec1e9vdbd3",
        "base-image-ee43618uo7",
    ]


def test_list_images_filters_cover_every_dimension() -> None:
    """Framework version, Python, and CPU architecture are all matched."""
    images = _list(
        framework_versions=["conda"],
        python_versions=["3.10"],
        cpu_archs=["X86"],
    )

    assert [image["image_uuid"] for image in images] == ["base-image-8hkyyugih5"]


def test_list_images_rejects_an_empty_filter() -> None:
    """A blank filter value is a caller error, not a match-everything wildcard."""
    with pytest.raises(ValueError, match="framework filter must not be empty"):
        _list(frameworks=["  "])


@pytest.mark.parametrize(
    "tree",
    [
        pytest.param({"not": "a list"}, id="data-not-a-list"),
        pytest.param([["not", "a", "dict"]], id="framework-not-a-dict"),
        pytest.param([{"label": "", "children": []}], id="empty-framework-label"),
        pytest.param([{"label": "PyTorch", "children": "nope"}], id="children-not-a-list"),
        pytest.param(
            [_framework("PyTorch", _version("2.8.0", _python("3.12", {"label": "12.8"})))],
            id="leaf-label-name-not-a-dict",
        ),
        pytest.param(
            [
                _framework(
                    "PyTorch",
                    _version(
                        "2.8.0",
                        _python(
                            "3.12",
                            {"label": "12.8", "label_name": {"uuid": "", "chip_corp": "nvidia"}},
                        ),
                    ),
                )
            ],
            id="empty-image-uuid",
        ),
    ],
)
def test_list_images_rejects_malformed_data(tree: object) -> None:
    """Malformed nodes raise an API error instead of being skipped silently."""
    with pytest.raises(APIError, match="image list returned malformed data"):
        _list(tree)


def test_list_images_surfaces_an_authentication_failure() -> None:
    """An ``AuthorizeFailed`` envelope becomes an :class:`AuthError`."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": "AuthorizeFailed", "msg": "login timed out", "data": None})

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AuthError, match="login timed out"):
            image_handler.list_images(client)


#: Two sanitised private-image entries: one finished and one still saving.
PRIVATE_IMAGES = [
    {
        "id": 842525,
        "created_at": "2026-11-01T02:46:47+08:00",
        "updated_at": "2026-11-01T02:46:47+08:00",
        "image_uuid": "image-40c7c7115c",
        "instance_uuid": "mamykqv3ku-87936de3",
        "name": "save-image-test",
        "image_size": 1021552640,
        "progress_content": {"oss_file_size": 373865271, "progress": 100, "error": ""},
        "status": "finished",
        "chip_corp": "nvidia",
        "cpu_arch": "x86",
        "framework": "PyTorch:2.12.1",
        "python_v": "3.12(ubuntu22.04)",
        "cuda_v": "13.0",
        "is_desktop": False,
        "image_source": "private",
    },
    {
        "id": 842524,
        "created_at": "2026-11-01T02:45:00+08:00",
        "updated_at": "2026-11-01T02:45:00+08:00",
        "image_uuid": "image-11aa22bb33",
        "instance_uuid": "wn8vt448yq-473b14de",
        "name": "trainer-snapshot",
        "image_size": 0,
        "progress_content": {"oss_file_size": 157286400, "progress": 42, "error": ""},
        "status": "saving",
        "chip_corp": "nvidia",
        "cpu_arch": "x86",
        "framework": "TensorFlow:2.9.0",
        "python_v": "3.8(ubuntu20.04)",
        "cuda_v": "11.2",
        "is_desktop": False,
        "image_source": "private",
    },
]


def _private_page(
    entries: list[dict[str, object]],
    *,
    page_index: int = 1,
    max_page: int = 1,
) -> dict[str, object]:
    """Build the ``data`` object of a private-image list response.

    :param entries: Images on this page.
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


def test_list_private_images_posts_expected_body_and_returns_entries() -> None:
    """The handler sends the console's body and returns the entries unchanged."""
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["authorization"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return _success(_private_page(PRIVATE_IMAGES))

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        images = image_handler.list_private_images(client, page_size=20)

    assert seen == {
        "method": "POST",
        "path": "/api/v1/image/private/list",
        "authorization": TOKEN,
        "body": {
            "order_uuid": "",
            "date_from": "",
            "date_to": "",
            "page_index": 1,
            "page_size": 20,
        },
    }
    assert images == PRIVATE_IMAGES


def test_list_private_images_walks_all_pages() -> None:
    """Every page up to ``max_page`` is fetched and concatenated in order."""
    requested: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page_index = json.loads(request.content)["page_index"]
        requested.append(page_index)
        entry = dict(PRIVATE_IMAGES[0], image_uuid=f"image-page-{page_index}")
        return _success(_private_page([entry], page_index=page_index, max_page=2))

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        images = image_handler.list_private_images(client)

    assert requested == [1, 2]
    assert [image["image_uuid"] for image in images] == ["image-page-1", "image-page-2"]


def test_list_private_images_rejects_a_non_positive_page_size() -> None:
    """A zero or negative page size is rejected before any request."""
    with pytest.raises(ValueError, match="page_size must be at least 1"):
        with AutoDLClient(TOKEN, transport=httpx.MockTransport(lambda request: pytest.fail("no request"))) as client:
            image_handler.list_private_images(client, page_size=0)


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(None, id="data-not-an-object"),
        pytest.param({"list": "nope"}, id="list-not-an-array"),
        pytest.param({"list": [["not", "a", "dict"]]}, id="entry-not-a-dict"),
    ],
)
def test_list_private_images_rejects_malformed_data(data: object) -> None:
    """Malformed pages raise an API error instead of being skipped silently."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _success(data)

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(APIError, match="private image list"):
            image_handler.list_private_images(client)


def test_list_private_images_surfaces_an_authentication_failure() -> None:
    """An ``AuthorizeFailed`` envelope becomes an :class:`AuthError`."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": "AuthorizeFailed", "msg": "login timed out", "data": None})

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AuthError, match="login timed out"):
            image_handler.list_private_images(client)


def test_delete_private_image_sends_image_id_and_tolerates_null_data() -> None:
    """The handler DELETEs by numeric ID and accepts a null ``data`` payload."""
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["authorization"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return _success(None)

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        result = image_handler.delete_private_image(client, 842526)

    assert seen == {
        "method": "DELETE",
        "path": "/api/v1/image/private/delete",
        "authorization": TOKEN,
        "body": {"image_id": 842526},
    }
    assert result == {"image_id": 842526, "deleted": True}


@pytest.mark.parametrize("image_id", [0, -1, True, "842526"])
def test_delete_private_image_rejects_invalid_ids(image_id: object) -> None:
    """A non-positive or non-integer ID is rejected before any request."""
    with pytest.raises(ValueError, match="image_id must be a positive integer"):
        with AutoDLClient(TOKEN, transport=httpx.MockTransport(lambda request: pytest.fail("no request"))) as client:
            image_handler.delete_private_image(client, image_id)  # type: ignore[arg-type]


def test_delete_private_image_auth_failure_raises_auth_error() -> None:
    """An ``AuthorizeFailed`` envelope becomes an :class:`AuthError`."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"code": "AuthorizeFailed", "msg": "login timed out", "data": None, "request_id": "req-9"},
        )

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AuthError, match="login timed out"):
            image_handler.delete_private_image(client, 842526)


def test_delete_private_image_failure_raises_api_error() -> None:
    """A non-success envelope becomes an :class:`APIError`."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": "ImageNotFound", "msg": "no such image", "data": None})

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(APIError, match="no such image"):
            image_handler.delete_private_image(client, 842526)


WAIT_INSTANCE_UUID = "wn8vt448yq-473b14de"
WAIT_IMAGE_NAME = "trainer-snapshot"


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


def _save_entry(
    image_id: int,
    *,
    status: str = "finished",
    error: str = "",
    progress: int = 100,
    image_uuid: str = "image-new",
    instance_uuid: str = WAIT_INSTANCE_UUID,
    name: str = WAIT_IMAGE_NAME,
) -> dict[str, object]:
    """Build one private-image entry for a save.

    :param image_id: Numeric image ID.
    :param status: Save status.
    :param error: Error text placed inside ``progress_content``.
    :param progress: Progress percentage.
    :param image_uuid: Image UUID string.
    :param instance_uuid: Source instance UUID.
    :param name: Image name.
    :returns: A private-image mapping.
    """
    return {
        "id": image_id,
        "instance_uuid": instance_uuid,
        "name": name,
        "status": status,
        "image_uuid": image_uuid,
        "progress_content": {"progress": progress, "error": error},
    }


def test_wait_for_private_image_returns_a_new_finished_image(fake_poll) -> None:
    """A matching image absent from the snapshot succeeds on the first poll."""
    _, delays = fake_poll
    entry = _save_entry(9001, image_uuid="image-new")

    def handler(request: httpx.Request) -> httpx.Response:
        return _success(_private_page([entry]))

    events: list[dict[str, object]] = []
    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        result = image_handler.wait_for_private_image(
            client,
            instance_uuid=WAIT_INSTANCE_UUID,
            image_name=WAIT_IMAGE_NAME,
            previous_statuses={},
            interval=2.0,
            on_event=events.append,
        )

    assert result == {
        "image_uuid": "image-new",
        "image_id": 9001,
        "name": WAIT_IMAGE_NAME,
        "status": "finished",
        "waited_seconds": 0.0,
        "image": entry,
    }
    assert events == [
        {
            "event": "image_status",
            "image_id": 9001,
            "name": WAIT_IMAGE_NAME,
            "status": "finished",
            "progress": {"progress": 100, "error": ""},
        },
        {
            "event": "finished",
            "image_uuid": "image-new",
            "image_id": 9001,
            "name": WAIT_IMAGE_NAME,
        },
    ]
    assert delays == []


def test_wait_for_private_image_ignores_a_pre_existing_finished_image(fake_poll) -> None:
    """A finished image that was already present does not end the wait."""
    _, delays = fake_poll
    old = _save_entry(9001, image_uuid="image-old")
    new = _save_entry(9002, image_uuid="image-new")
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        entries = [old] if len(calls) == 1 else [old, new]
        return _success(_private_page(entries))

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        result = image_handler.wait_for_private_image(
            client,
            instance_uuid=WAIT_INSTANCE_UUID,
            image_name=WAIT_IMAGE_NAME,
            previous_statuses={9001: "finished"},
            interval=4.0,
        )

    assert result["image_id"] == 9002
    assert result["image_uuid"] == "image-new"
    assert result["waited_seconds"] == 4.0
    assert delays == [4.0]


def test_wait_for_private_image_polls_until_finished(fake_poll) -> None:
    """A saving image is polled again after the interval until it finishes."""
    _, delays = fake_poll
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        status = "saving" if len(calls) == 1 else "finished"
        return _success(_private_page([_save_entry(9001, status=status, progress=42)]))

    events: list[dict[str, object]] = []
    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        result = image_handler.wait_for_private_image(
            client,
            instance_uuid=WAIT_INSTANCE_UUID,
            image_name=WAIT_IMAGE_NAME,
            previous_statuses={},
            interval=2.0,
            on_event=events.append,
        )

    assert result["status"] == "finished"
    assert result["waited_seconds"] == 2.0
    assert [event["event"] for event in events] == [
        "image_status",
        "image_status",
        "finished",
    ]
    assert [event.get("status") for event in events[:2]] == ["saving", "finished"]
    assert events[0]["progress"] == {"progress": 42, "error": ""}
    assert delays == [2.0]


def test_wait_for_private_image_raises_on_a_failed_status(fake_poll) -> None:
    """A new failed image raises :class:`APIError`."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _success(_private_page([_save_entry(9001, status="failed")]))

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(APIError, match="entered status 'failed'"):
            image_handler.wait_for_private_image(
                client,
                instance_uuid=WAIT_INSTANCE_UUID,
                image_name=WAIT_IMAGE_NAME,
                previous_statuses={},
            )


def test_wait_for_private_image_raises_on_a_progress_error(fake_poll) -> None:
    """A non-empty ``progress_content.error`` raises :class:`APIError`."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _success(_private_page([_save_entry(9001, status="saving", error="disk full")]))

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(APIError, match="disk full"):
            image_handler.wait_for_private_image(
                client,
                instance_uuid=WAIT_INSTANCE_UUID,
                image_name=WAIT_IMAGE_NAME,
                previous_statuses={},
            )


def test_wait_for_private_image_accepts_finished_with_a_stale_error(fake_poll) -> None:
    """A finished image wins over leftover error text from an earlier attempt."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _success(_private_page([_save_entry(9001, status="finished", error="previous attempt")]))

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        result = image_handler.wait_for_private_image(
            client,
            instance_uuid=WAIT_INSTANCE_UUID,
            image_name=WAIT_IMAGE_NAME,
            previous_statuses={},
        )

    assert result["status"] == "finished"
    assert result["image_id"] == 9001


def test_wait_for_private_image_ignores_a_pre_existing_failure(fake_poll) -> None:
    """``--try-again`` does not fail immediately on the older failed entry."""
    _, delays = fake_poll
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        status = "failed" if len(calls) == 1 else "finished"
        return _success(_private_page([_save_entry(9001, status=status)]))

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        result = image_handler.wait_for_private_image(
            client,
            instance_uuid=WAIT_INSTANCE_UUID,
            image_name=WAIT_IMAGE_NAME,
            previous_statuses={9001: "failed"},
            interval=3.0,
        )

    assert result["status"] == "finished"
    assert delays == [3.0]


def test_wait_for_private_image_ignores_unrelated_images(fake_poll) -> None:
    """Only the exact source instance and name pair is considered."""
    calls: list[int] = []
    wanted = _save_entry(9001)

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            unrelated = [
                _save_entry(8001, instance_uuid="other-instance"),
                _save_entry(8002, name="other-name"),
            ]
            return _success(_private_page(unrelated))
        return _success(_private_page([wanted]))

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        result = image_handler.wait_for_private_image(
            client,
            instance_uuid=WAIT_INSTANCE_UUID,
            image_name=WAIT_IMAGE_NAME,
            previous_statuses={},
            interval=1.0,
        )

    assert result["image_id"] == 9001
    assert calls == [1, 1]


def test_wait_for_private_image_times_out(fake_poll) -> None:
    """An image that never finishes raises :class:`TimeoutError`."""
    _, delays = fake_poll

    def handler(request: httpx.Request) -> httpx.Response:
        return _success(_private_page([_save_entry(9001, status="saving")]))

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(
            TimeoutError,
            match=r"Timed out after 5s waiting for image .* \(last status: 'saving'\)",
        ):
            image_handler.wait_for_private_image(
                client,
                instance_uuid=WAIT_INSTANCE_UUID,
                image_name=WAIT_IMAGE_NAME,
                previous_statuses={},
                interval=2.0,
                timeout=5.0,
            )

    assert delays == [2.0, 2.0, 2.0]


def test_wait_for_private_image_retries_a_transient_error(fake_poll) -> None:
    """A 500 is retried when ``retry`` allows it, then the wait succeeds."""
    _, delays = fake_poll
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(500, json={"msg": "boom"})
        return _success(_private_page([_save_entry(9001)]))

    events: list[dict[str, object]] = []
    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        result = image_handler.wait_for_private_image(
            client,
            instance_uuid=WAIT_INSTANCE_UUID,
            image_name=WAIT_IMAGE_NAME,
            previous_statuses={},
            interval=3.0,
            retry=1,
            on_event=events.append,
        )

    assert result["image_id"] == 9001
    assert events[0]["event"] == "poll_failed"
    assert events[0]["retries"] == 1
    assert delays == [3.0]


def test_private_image_status_snapshot_collects_exact_matches() -> None:
    """Only exact instance/name matches with positive numeric IDs are recorded."""
    entries = [
        _save_entry(9001, status="saving"),
        _save_entry(9002, status="failed"),
        _save_entry(8001, status="finished", instance_uuid="other-instance"),
        _save_entry(8002, status="finished", name="other-name"),
        {**_save_entry(0, status="finished")},
        {**_save_entry(9003, status="finished"), "id": True},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return _success(_private_page(entries))

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        snapshot = image_handler.private_image_status_snapshot(
            client,
            WAIT_INSTANCE_UUID,
            WAIT_IMAGE_NAME,
        )

    assert snapshot == {9001: "saving", 9002: "failed"}


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"instance_uuid": "", "image_name": WAIT_IMAGE_NAME}, "instance_uuid must not be empty"),
        ({"instance_uuid": "   ", "image_name": WAIT_IMAGE_NAME}, "instance_uuid must not be empty"),
        ({"instance_uuid": WAIT_INSTANCE_UUID, "image_name": ""}, "image_name must not be empty"),
        ({"instance_uuid": WAIT_INSTANCE_UUID, "image_name": "   "}, "image_name must not be empty"),
    ],
)
def test_wait_for_private_image_rejects_blank_identifiers(kwargs: dict[str, object], message: str) -> None:
    """Blank identifiers fail before any request is sent."""

    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("no request must be sent for a blank identifier")

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match=message):
            image_handler.wait_for_private_image(
                client,
                previous_statuses={},
                **kwargs,
            )


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"interval": 0}, "interval"),
        ({"interval": -1}, "interval"),
        ({"interval": True}, "interval"),
        ({"timeout": -1}, "timeout"),
        ({"timeout": True}, "timeout"),
        ({"retry": -1}, "retry"),
        ({"retry": True}, "retry"),
    ],
)
def test_wait_for_private_image_rejects_invalid_numeric_options(
    kwargs: dict[str, object],
    message: str,
) -> None:
    """Invalid numeric options fail before any request is sent."""

    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("no request must be sent for invalid options")

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match=message):
            image_handler.wait_for_private_image(
                client,
                instance_uuid=WAIT_INSTANCE_UUID,
                image_name=WAIT_IMAGE_NAME,
                previous_statuses={},
                **kwargs,
            )


@pytest.mark.parametrize("instance_uuid", ["", "   "])
def test_private_image_status_snapshot_rejects_a_blank_instance_uuid(instance_uuid: str) -> None:
    """A blank instance UUID fails before any request is sent."""

    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("no request must be sent for a blank UUID")

    with AutoDLClient(TOKEN, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match="instance_uuid must not be empty"):
            image_handler.private_image_status_snapshot(client, instance_uuid, WAIT_IMAGE_NAME)
