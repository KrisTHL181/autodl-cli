"""``autodl tools`` — general-purpose utility commands.

``request`` sends a raw HTTP request to any URL — the stored token and the
mandatory ``AppVersion`` header are attached only when the target stays on the
AutoDL origin — or prints an equivalent curl command.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from autodl_cli import output
from autodl_cli.client import AutoDLClient
from autodl_cli.commands._helpers import require_token
from autodl_cli.config import load_config
from autodl_cli.errors import AutoDLError
from autodl_cli.handlers import tools as tools_handler


@click.group(help="General-purpose utility commands that are not tied to a single API domain.")
def tools() -> None:
    """General-purpose utility commands."""


def _parse_headers(raw_headers: tuple[str, ...]) -> dict[str, str]:
    """Parse repeated ``Key: Value`` header options.

    :param raw_headers: Raw values from ``--header``.
    :returns: Header name to value mapping.
    :raises click.BadParameter: When a value has no ``:`` separator or no name.
    """
    headers: dict[str, str] = {}
    for raw in raw_headers:
        name, separator, value = raw.partition(":")
        if not separator or not name.strip():
            raise click.BadParameter(
                f"invalid header {raw!r}; expected 'Key: Value'",
                param_hint="'-H' / '--header'",
            )
        headers[name.strip()] = value.strip()
    return headers


def _read_data(data: str) -> str:
    """Expand a curl-style ``@path`` body option.

    :param data: Raw ``--data`` value.
    :returns: The value itself, or the UTF-8 contents of the referenced file.
    :raises click.BadParameter: When the file cannot be read.
    """
    if not data.startswith("@"):
        return data
    source = Path(data[1:])
    try:
        return source.read_text(encoding="utf-8")
    except OSError as exc:
        raise click.BadParameter(
            f"cannot read {source}: {exc}",
            param_hint="'-d' / '--data'",
        ) from exc


def _parses_as_json(data: str) -> bool:
    """Return whether ``data`` is a valid JSON document.

    :param data: Request body.
    :returns: ``True`` when :func:`json.loads` accepts the text.
    """
    try:
        json.loads(data)
    except ValueError:
        return False
    return True


def _has_header(headers: dict[str, str], name: str) -> bool:
    """Return whether ``headers`` contains ``name``, ignoring case.

    :param headers: Request headers.
    :param name: Header name to look for.
    :returns: ``True`` when the header is present.
    """
    lowered = name.lower()
    return any(key.lower() == lowered for key in headers)


def _write_output(path: str, result: dict[str, object], *, include_headers: bool) -> None:
    """Write a response to a file.

    With ``include_headers`` the status line, headers, blank line, and body are
    written as UTF-8 text; otherwise the raw response bytes are written.

    :param path: Destination file.
    :param result: Response mapping returned by the handler.
    :param include_headers: Whether to prepend the status line and headers.
    """
    try:
        if include_headers:
            status = result["status"]
            reason = result["reason"]
            response_headers = result["headers"]
            lines = [f"HTTP {status} {reason}"]
            if isinstance(response_headers, dict):
                lines.extend(f"{key}: {value}" for key, value in response_headers.items())
            lines.append("")
            lines.append(str(result["text"]))
            Path(path).write_text("\n".join(lines), encoding="utf-8")
            return

        content = result["content"]
        Path(path).write_bytes(content if isinstance(content, bytes) else b"")
    except OSError as exc:
        raise click.ClickException(f"Cannot write {path}: {exc}") from exc


@tools.command("request", help="Send an HTTP request to the AutoDL API or any URL.")
@click.argument("url")
@click.option(
    "--method",
    "-X",
    default=None,
    help="HTTP method (default: GET, or POST when --data is given).",
)
@click.option("--data", "-d", default=None, help="Request body; use @path to read from a file.")
@click.option(
    "--header",
    "-H",
    "raw_headers",
    multiple=True,
    metavar="KEY:VALUE",
    help="Extra request header (repeatable).",
)
@click.option("--include", "-i", "include_headers", is_flag=True, help="Include the response status line and headers.")
@click.option("--no-auth", is_flag=True, help="Do not attach the stored token, even for AutoDL URLs.")
@click.option("--curl", "as_curl", is_flag=True, help="Print an equivalent curl command instead of sending.")
@click.option(
    "--output",
    "-o",
    "output_path",
    type=click.Path(dir_okay=False),
    default=None,
    help="Write the response body to this file.",
)
@click.pass_context
def request(
    ctx: click.Context,
    url: str,
    method: str | None,
    data: str | None,
    raw_headers: tuple[str, ...],
    include_headers: bool,
    no_auth: bool,
    as_curl: bool,
    output_path: str | None,
) -> None:
    """Send an HTTP request and print the response.

    :param ctx: Click context; ``ctx.obj["json"]`` selects JSON output.
    :param url: Absolute URL, or a path relative to the AutoDL base URL.
    :param method: HTTP method; defaults to GET, or POST when ``data`` is set.
    :param data: Request body; ``@path`` reads a UTF-8 file.
    :param raw_headers: Repeated ``Key: Value`` headers.
    :param include_headers: Whether to print the status line and headers.
    :param no_auth: Whether to withhold the stored token even on AutoDL URLs.
    :param as_curl: Whether to print a curl command instead of sending.
    :param output_path: Optional file that receives the response body.
    :raises click.ClickException: When no token is available for an AutoDL
        request or the request fails.
    :raises click.BadParameter: When a header or data file is invalid.
    """
    request_headers = _parse_headers(raw_headers)
    if data is not None:
        data = _read_data(data)
    request_method = method or ("POST" if data is not None else "GET")

    config = load_config()
    stored_token = config.get("token")
    token = stored_token if isinstance(stored_token, str) and stored_token else None

    with AutoDLClient(token) as client:
        resolved_url, on_autodl = tools_handler.resolve_url(url, client.base_url)
        include_auth = on_autodl and not no_auth
        if on_autodl and not no_auth and token is None:
            require_token(config)
            return

        if as_curl:
            curl_headers = client.headers_for(
                request_headers,
                include_auth=include_auth,
                app_version=on_autodl,
            )
            if data is not None and not _parses_as_json(data) and not _has_header(request_headers, "content-type"):
                curl_headers["Content-Type"] = "application/x-www-form-urlencoded"
            output.render_curl(tools_handler.build_curl(resolved_url, request_method, curl_headers, data))
            return

        try:
            result = tools_handler.send_request(
                client,
                request_method,
                url,
                headers=request_headers,
                data=data,
                include_auth=not no_auth,
            )
        except AutoDLError as exc:
            raise click.ClickException(str(exc)) from exc

    status = result["status"]
    reason = result["reason"]
    response_headers = result["headers"]
    body = str(result["text"])
    is_json = bool(result["is_json"])
    json_body = result["json"]

    if output_path is not None:
        _write_output(output_path, result, include_headers=include_headers)
        output.success(f"Response written to {output_path}")
    elif ctx.obj and ctx.obj.get("json"):
        output.render_json(
            {
                "method": result["method"],
                "url": result["url"],
                "status": status,
                "headers": response_headers,
                "body": json_body if is_json else body,
            }
        )
    elif "\x00" in body and sys.stdout.isatty():
        output.error("Response body is binary; use --output to save it.")
        ctx.exit(1)
    else:
        output.render_http_response(
            status=int(status),
            reason=str(reason),
            headers=response_headers if isinstance(response_headers, dict) else {},
            body=body,
            json_body=json_body,
            is_json=is_json,
            include_headers=include_headers,
        )

    if not isinstance(status, int) or not 200 <= status < 300:
        ctx.exit(1)


def register_tools(main_group: click.Group) -> click.Group:
    """Register the ``tools`` command group on ``main_group``.

    :param main_group: Root Click group.
    :returns: The same group, for chaining.
    """
    main_group.add_command(tools)
    return main_group
