"""Tests for the best-effort notification helpers."""

from __future__ import annotations

from datetime import datetime, timedelta

import httpx
import pytest

from autodl_cli.utils import notify


class _Response:
    """Minimal stand-in for ``httpx.Response``."""

    def __init__(self, status_code: int) -> None:
        """Store the status code.

        :param status_code: HTTP status to report.
        """
        self.status_code = status_code


class _FakeDesktopNotifier:
    """Stand-in for ``desktop_notifier.DesktopNotifier``."""

    instances: list[_FakeDesktopNotifier] = []
    error: Exception | None = None

    def __init__(self, *, app_name: str) -> None:
        """Record the app name.

        :param app_name: Name passed by the notification helper.
        """
        self.app_name = app_name
        self.sent: list[tuple[str, str]] = []
        type(self).instances.append(self)

    async def send(self, *, title: str, message: str) -> str:
        """Record the notification or raise the configured error.

        :param title: Notification title.
        :param message: Notification body.
        :returns: A fake notification identifier.
        :raises Exception: When the class-level ``error`` is configured.
        """
        if type(self).error is not None:
            raise type(self).error
        self.sent.append((title, message))
        return "notification-id"


def _use_desktop_notifier(monkeypatch, notifier_class: type | None) -> None:
    """Replace the lazy desktop-notifier loader.

    :param monkeypatch: pytest's monkeypatch fixture.
    :param notifier_class: Class to return, or ``None`` to simulate a missing
        optional dependency.
    """
    monkeypatch.setattr(notify, "_load_desktop_notifier", lambda: notifier_class)


def test_desktop_notification_uses_desktop_notifier(monkeypatch) -> None:
    """The optional package receives the app name, title, and body."""
    _FakeDesktopNotifier.instances = []
    _FakeDesktopNotifier.error = None
    _use_desktop_notifier(monkeypatch, _FakeDesktopNotifier)

    assert notify.send_desktop("Title", "Body") is None

    instance = _FakeDesktopNotifier.instances[0]
    assert instance.app_name == notify.APP_NAME
    assert instance.sent == [("Title", "Body")]


def test_missing_desktop_notifier_returns_install_hint(monkeypatch) -> None:
    """The optional extra is reported instead of silently doing nothing."""
    _use_desktop_notifier(monkeypatch, None)

    error = notify.send_desktop("Title", "Body")

    assert error is not None
    assert "desktop-notifier" in error
    assert "autodl-cli[notify]" in error


def test_desktop_notifier_failure_is_swallowed(monkeypatch) -> None:
    """A raising notifier never escapes and names only the exception type."""
    _FakeDesktopNotifier.instances = []
    _FakeDesktopNotifier.error = RuntimeError("no notification daemon")
    _use_desktop_notifier(monkeypatch, _FakeDesktopNotifier)

    assert notify.send_desktop("Title", "Body") == "desktop-notifier raised RuntimeError"


def test_webhook_payload_contains_generic_fields() -> None:
    """The payload has source, event, title, body, text, timestamp, and data."""
    payload = notify.build_webhook_payload(
        "snipe.ordered",
        "GPU ordered",
        "Instance u-1 ordered",
        instance_uuid="u-1",
        machine_id="m-1",
        region_name=None,
    )

    assert payload["source"] == "autodl-cli"
    assert payload["event"] == "snipe.ordered"
    assert payload["title"] == "GPU ordered"
    assert payload["body"] == "Instance u-1 ordered"
    assert payload["text"] == "GPU ordered: Instance u-1 ordered"
    assert payload["data"] == {"instance_uuid": "u-1", "machine_id": "m-1"}
    timestamp = datetime.fromisoformat(str(payload["timestamp"]))
    assert timestamp.tzinfo is not None
    assert timestamp.utcoffset() == timedelta(0)


def test_post_webhook_accepts_2xx(monkeypatch) -> None:
    """A 2xx response returns ``None`` and sends the payload as JSON."""
    calls: dict[str, object] = {}

    def fake_post(url, **kwargs):
        calls["url"] = url
        calls["kwargs"] = kwargs
        return _Response(204)

    monkeypatch.setattr(notify.httpx, "post", fake_post)

    assert notify.post_webhook("https://example.test/hook", {"event": "x"}) is None
    assert calls["url"] == "https://example.test/hook"
    assert calls["kwargs"]["json"] == {"event": "x"}
    assert calls["kwargs"]["timeout"] == notify.NOTIFICATION_TIMEOUT


def test_post_webhook_reports_status_without_url(monkeypatch) -> None:
    """A non-2xx response returns a short error that hides the URL."""
    monkeypatch.setattr(notify.httpx, "post", lambda url, **kwargs: _Response(500))

    error = notify.post_webhook("https://api.day.app/SECRET", {})

    assert error is not None
    assert "500" in error
    assert "SECRET" not in error
    assert "api.day.app" not in error


def test_post_webhook_swallows_transport_errors(monkeypatch) -> None:
    """A transport error returns a description without the URL or exception text."""
    url = "https://api.day.app/SECRET"

    def boom(actual_url, **kwargs):
        raise httpx.ConnectError(f"failed to connect to {actual_url}")

    monkeypatch.setattr(notify.httpx, "post", boom)

    error = notify.post_webhook(url, {})

    assert error is not None
    assert "ConnectError" in error
    assert "SECRET" not in error
    assert url not in error


def test_notifier_enabled_reports_configured_channels() -> None:
    """``enabled`` is true when a channel is configured."""
    assert notify.Notifier().enabled is False
    assert notify.Notifier(desktop=True).enabled is True
    assert notify.Notifier(webhooks=["https://example.test/hook"]).enabled is True


def test_notifier_isolates_channels_and_deduplicates_warnings(monkeypatch) -> None:
    """One failing channel does not stop the others, and warnings repeat once."""
    delivered: list[str] = []
    monkeypatch.setattr(notify, "send_desktop", lambda title, body: "no display server")

    def fake_post(url, payload, **kwargs):
        delivered.append(url)
        return "server returned HTTP 500" if url == "https://bad.test/hook" else None

    monkeypatch.setattr(notify, "post_webhook", fake_post)
    notifier = notify.Notifier(desktop=True, webhooks=["https://bad.test/hook", "https://good.test/hook"])

    assert notifier.send("snipe.ordered", "Title", "Body") == [
        "Desktop notification failed: no display server.",
        "Notification webhook failed: server returned HTTP 500.",
    ]
    assert delivered == ["https://bad.test/hook", "https://good.test/hook"]

    assert notifier.send("snipe.running", "Title", "Body") == []
    assert delivered == [
        "https://bad.test/hook",
        "https://good.test/hook",
        "https://bad.test/hook",
        "https://good.test/hook",
    ]


def test_disabled_notifier_does_not_deliver(monkeypatch) -> None:
    """No channel is invoked when nothing is enabled."""
    monkeypatch.setattr(
        notify,
        "send_desktop",
        lambda title, body: pytest.fail("desktop notifications are disabled"),
    )
    monkeypatch.setattr(
        notify,
        "post_webhook",
        lambda url, payload: pytest.fail("webhooks are disabled"),
    )

    assert notify.Notifier().send("snipe.ordered", "Title", "Body") == []
