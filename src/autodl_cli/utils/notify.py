"""Best-effort desktop and webhook notifications.

Nothing in this module raises: a missing optional desktop dependency, an
unavailable notification daemon, or an unreachable webhook only produces a
warning string that the caller may display. Webhook URLs are treated as secrets
because services such as Bark embed an access key in the path, so they are never
echoed in error messages.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

#: Maximum seconds to spend on one webhook delivery.
NOTIFICATION_TIMEOUT = 5.0

#: App name shown by the desktop notification daemon.
APP_NAME = "autodl-cli"


def _load_desktop_notifier() -> type | None:
    """Import :class:`desktop_notifier.DesktopNotifier` when it is installed.

    The dependency lives in the optional ``notify`` extra, so it is imported
    lazily and a missing package is not an error.

    :returns: The notifier class, or ``None`` when the extra is not installed.
    """
    try:
        from desktop_notifier import DesktopNotifier
    except ImportError:
        return None
    return DesktopNotifier


def send_desktop(title: str, body: str) -> str | None:
    """Show a desktop notification through ``desktop-notifier``.

    The call is best effort: a missing optional dependency, an unavailable
    notification daemon, or any other failure is reported as a string instead
    of raising.

    :param title: Notification title.
    :param body: Notification body.
    :returns: ``None`` when the notification was sent, otherwise a short error
        description suitable for a warning.
    """
    notifier_class = _load_desktop_notifier()
    if notifier_class is None:
        return "desktop-notifier is not installed (install with pip install 'autodl-cli[notify]')"

    try:
        notifier = notifier_class(app_name=APP_NAME)
        asyncio.run(notifier.send(title=title, message=body))
    except Exception as exc:
        return f"desktop-notifier raised {type(exc).__name__}"
    return None


def build_webhook_payload(event: str, title: str, body: str, **fields: object) -> dict[str, object]:
    """Build the JSON document sent to a webhook.

    ``None`` fields are dropped so consumers do not have to special-case
    missing instance data.

    :param event: Event name such as ``snipe.ordered``.
    :param title: Human-readable title.
    :param body: Human-readable body.
    :param fields: Extra values placed in the ``data`` object.
    :returns: A JSON-serialisable payload.
    """
    data = {key: value for key, value in fields.items() if value is not None}
    return {
        "source": "autodl-cli",
        "event": event,
        "title": title,
        "body": body,
        "text": f"{title}: {body}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": data,
    }


def post_webhook(url: str, payload: Mapping[str, object], *, timeout: float = NOTIFICATION_TIMEOUT) -> str | None:
    """POST ``payload`` as JSON to ``url``.

    The URL is never echoed in the returned error, and no exception escapes.

    :param url: Absolute HTTP(S) webhook URL.
    :param payload: JSON-serialisable document.
    :param timeout: Request timeout in seconds.
    :returns: ``None`` on a 2xx response, otherwise a short error description
        that does not contain the URL.
    """
    try:
        response = httpx.post(url, json=dict(payload), timeout=timeout)
    except Exception as exc:
        return f"request failed ({type(exc).__name__})"
    if not 200 <= response.status_code < 300:
        return f"server returned HTTP {response.status_code}"
    return None


class Notifier:
    """Deliver an event to the desktop and zero or more webhooks.

    Every channel is attempted independently. Warning strings are
    deduplicated across calls so a permanently unavailable desktop service
    does not repeat itself on every event, while later deliveries are still
    attempted.
    """

    def __init__(self, *, desktop: bool = False, webhooks: Iterable[str] = ()) -> None:
        """Create a notifier.

        :param desktop: Whether to show desktop notifications.
        :param webhooks: Webhook URLs to POST to.
        """
        self._desktop = desktop
        self._webhooks = tuple(webhooks)
        self._warned: set[str] = set()

    @property
    def enabled(self) -> bool:
        """Return whether at least one channel is configured.

        :returns: ``True`` when desktop notifications or a webhook are enabled.
        """
        return self._desktop or bool(self._webhooks)

    def _collect(self, warning: str, warnings: list[str]) -> None:
        """Append ``warning`` once, across all calls on this notifier.

        :param warning: Warning text.
        :param warnings: Warning list returned to the caller.
        """
        if warning in self._warned:
            return
        self._warned.add(warning)
        warnings.append(warning)

    def send(self, event: str, title: str, body: str, **fields: object) -> list[str]:
        """Send one event through every configured channel.

        :param event: Event name such as ``snipe.running``.
        :param title: Notification title.
        :param body: Notification body.
        :param fields: Extra values included in the webhook ``data`` object.
        :returns: Deduplicated warning strings for failed deliveries.
        """
        warnings: list[str] = []
        if self._desktop:
            error = send_desktop(title, body)
            if error is not None:
                self._collect(f"Desktop notification failed: {error}.", warnings)
        if not self._webhooks:
            return warnings

        payload = build_webhook_payload(event, title, body, **fields)
        for url in self._webhooks:
            error = post_webhook(url, payload)
            if error is not None:
                self._collect(f"Notification webhook failed: {error}.", warnings)
        return warnings
