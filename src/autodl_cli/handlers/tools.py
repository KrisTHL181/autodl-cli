"""Raw-request helpers behind ``autodl tools request``.

The handler resolves the target URL, attaches AutoDL credentials only when the
request targets an ``autodl.com`` host, and returns the response as plain data.
It never writes to the terminal; :mod:`autodl_cli.commands.tools` and
:mod:`autodl_cli.output` own all rendering.
"""

from __future__ import annotations

import json
import shlex
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

if TYPE_CHECKING:
    from collections.abc import Mapping

    from autodl_cli.client import AutoDLClient

#: Response headers that must not be copied into a generated curl command.
_SKIP_CURL_HEADERS = frozenset({"accept-encoding", "content-length", "host"})

#: Apex domain whose hosts all receive AutoDL credentials.
_AUTODL_DOMAIN = "autodl.com"


def _is_autodl_host(host: str | None) -> bool:
    """Return whether ``host`` belongs to the AutoDL domain.

    Any ``autodl.com`` host is accepted, including the apex domain and every
    subdomain such as ``www.autodl.com`` or ``region-1.autodl.com``. A host
    that merely ends with the same characters (``autodl.com.example.org``) is
    not.

    :param host: Host name from a parsed URL, or ``None``.
    :returns: ``True`` when the host is on the AutoDL domain.
    """
    if not host:
        return False
    host = host.lower()
    return host == _AUTODL_DOMAIN or host.endswith(f".{_AUTODL_DOMAIN}")


def resolve_url(url: str, base_url: str) -> tuple[str, bool]:
    """Resolve a user-supplied URL against the AutoDL base URL.

    Absolute ``http`` and ``https`` URLs are sent as-is. Anything else is
    treated as a path and appended to ``base_url``. The boolean tells the
    caller whether the resolved URL points at AutoDL — any ``autodl.com`` host,
    or the base URL's own origin — which is the only case where AutoDL
    credentials may be attached.

    :param url: URL or path from the command line.
    :param base_url: AutoDL API root.
    :returns: The resolved URL and whether it is an AutoDL host.
    """
    parsed = urlparse(url)
    if parsed.scheme in ("http", "https"):
        resolved = url
    else:
        resolved = f"{base_url.rstrip('/')}/{url.lstrip('/')}"

    resolved_url = urlparse(resolved)
    base_url_parsed = urlparse(base_url)
    same_origin = (resolved_url.scheme, resolved_url.netloc) == (base_url_parsed.scheme, base_url_parsed.netloc)
    on_autodl = same_origin or _is_autodl_host(resolved_url.hostname)
    return resolved, on_autodl


def _has_header(headers: Mapping[str, str], name: str) -> bool:
    """Return whether ``headers`` contains ``name``, ignoring case.

    :param headers: Request headers.
    :param name: Header name to look for.
    :returns: ``True`` when the header is present.
    """
    lowered = name.lower()
    return any(key.lower() == lowered for key in headers)


def send_request(
    client: AutoDLClient,
    method: str,
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    data: str | None = None,
    include_auth: bool = True,
) -> dict[str, object]:
    """Send one request and return the response as a plain dictionary.

    ``data`` is sent as JSON when it parses as JSON, otherwise as raw form
    content. AutoDL credentials and the ``AppVersion`` header are attached only
    when the resolved URL targets an ``autodl.com`` host.

    :param client: Client used to send the request.
    :param method: HTTP method.
    :param url: Absolute URL or path relative to the client's base URL.
    :param headers: Extra request headers.
    :param data: Request body, if any.
    :param include_auth: Whether AutoDL credentials may be attached; they are
        still withheld for external hosts.
    :returns: A mapping with ``url``, ``method``, ``status``, ``reason``,
        ``headers``, ``text``, ``content``, ``is_json``, and ``json``.
    """
    resolved_url, on_autodl = resolve_url(url, client.base_url)

    request_headers = dict(headers or {})
    request_kwargs: dict[str, Any] = {}
    if data is not None:
        try:
            request_kwargs["json"] = json.loads(data)
        except ValueError:
            request_kwargs["content"] = data.encode("utf-8")
            if not _has_header(request_headers, "content-type"):
                request_headers["Content-Type"] = "application/x-www-form-urlencoded"

    response = client.raw_request(
        method,
        resolved_url,
        headers=request_headers,
        include_auth=include_auth and on_autodl,
        app_version=on_autodl,
        **request_kwargs,
    )

    try:
        json_body = response.json()
    except ValueError:
        json_body = None
        is_json = False
    else:
        is_json = True

    return {
        "url": resolved_url,
        "method": method.upper(),
        "status": response.status_code,
        "reason": response.reason_phrase,
        "headers": dict(response.headers),
        "text": response.text,
        "content": response.content,
        "is_json": is_json,
        "json": json_body,
    }


def build_curl(url: str, method: str, headers: Mapping[str, str], data: str | None = None) -> str:
    """Build an equivalent curl command.

    :param url: Resolved request URL.
    :param method: HTTP method.
    :param headers: Headers that would be sent.
    :param data: Request body, if any.
    :returns: A shell-quoted, multi-line curl command.
    """
    parts = ["curl"]
    verb = method.upper()
    if verb != "GET":
        parts.append(f"-X {verb}")
    for key, value in headers.items():
        if key.lower() in _SKIP_CURL_HEADERS:
            continue
        parts.append(f"-H {shlex.quote(f'{key}: {value}')}")
    if data is not None:
        parts.append(f"--data {shlex.quote(data)}")
    parts.append(shlex.quote(url))
    return " \\\n  ".join(parts)
