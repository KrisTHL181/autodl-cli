"""``autodl tools`` — general-purpose utility commands.

``request`` sends a raw HTTP request to any URL — the stored token and the
mandatory ``AppVersion`` header are attached only when the target stays on the
AutoDL origin — or prints an equivalent curl command. ``snipe`` watches GPU
stock and orders the first matching machine.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from autodl_cli import output
from autodl_cli.commands._helpers import build_client, require_token
from autodl_cli.config import load_config
from autodl_cli.errors import AutoDLError
from autodl_cli.handlers import snipe as snipe_handler
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

    with build_client(token, config) as client:
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


def _render_snipe_event(event: dict[str, object]) -> None:
    """Render one progress event from the snipe handler.

    :param event: Event mapping emitted by
        :func:`autodl_cli.handlers.snipe.snipe`.
    """
    kind = event.get("event")
    if kind == "poll":
        line = f"Poll #{event.get('attempt', '')}: {event.get('matches', '')} matching machine(s)"
        cooling = event.get("cooling")
        if isinstance(cooling, int) and cooling > 0:
            line += f", {cooling} cooling down"
        output.info(f"{line}.")
        return
    if kind == "poll_failed":
        output.warning(
            f"Poll failed: {event.get('error', '')}; retrying ({event.get('retries', '')}/{event.get('limit', '')})."
        )
        return
    if kind == "found":
        machine = event.get("machine")
        machine = machine if isinstance(machine, dict) else {}
        output.info(
            f"Found {machine.get('gpu_name', '')} on machine {machine.get('machine_id', '')} "
            f"({machine.get('region_name', '')}); ordering..."
        )
        return
    if kind == "order_failed":
        backoff = event.get("backoff")
        failure_count = event.get("failures")
        if isinstance(backoff, (int, float)) and isinstance(failure_count, int):
            detail = f"backing off for {backoff:g}s (failure #{failure_count})"
        else:
            detail = "retrying"
        output.warning(f"Order failed on machine {event.get('machine_id', '')}: {event.get('error', '')}; {detail}.")
        return
    if kind == "ordered":
        machine = event.get("machine")
        machine = machine if isinstance(machine, dict) else {}
        output.success(
            f"Ordered instance {event.get('instance_uuid', '')} on machine "
            f"{machine.get('machine_id', '')}; waiting for it to start..."
        )
        return
    if kind == "instance_status":
        status = event.get("status")
        if status == "not found":
            output.info("Instance status: not visible yet.")
        else:
            output.info(f"Instance status: {status}.")
        return
    if kind == "running":
        output.info("Instance is running.")


@tools.command("snipe", help="Watch GPU stock and order a machine as soon as one is available.")
@click.option(
    "--region",
    "-r",
    "regions",
    multiple=True,
    metavar="REGION",
    help="Region sign, data center, or display name to search (repeatable).",
)
@click.option(
    "--gpu",
    "-g",
    "gpu_types",
    multiple=True,
    metavar="NAME",
    help="Exact GPU model name to search for (repeatable, case-insensitive).",
)
@click.option(
    "--gpu-num",
    type=click.IntRange(min=1),
    default=1,
    show_default=True,
    help="Number of GPUs to request; this narrows the search but does not target it.",
)
@click.option(
    "--max-price",
    type=click.FloatRange(min=0),
    default=None,
    metavar="YUAN/H",
    help="Maximum pay-as-you-go price in yuan per hour; this narrows the search.",
)
@click.option(
    "--strategy",
    type=click.Choice(snipe_handler.SNIPE_STRATEGIES),
    default="price",
    show_default=True,
    help="Order matching machines by price, idle capacity, or the first result.",
)
@click.option("--image", "-i", "base_image_uuid", default="", help="Base-image UUID from `autodl image list`.")
@click.option(
    "--private-image",
    "private_image_uuid",
    default="",
    help="Private-image UUID from `autodl image list-private`.",
)
@click.option("--name", "-n", default="", help="Instance name.")
@click.option(
    "--data-disk",
    type=click.IntRange(min=0),
    default=0,
    show_default=True,
    help="Extra data-disk size in GB.",
)
@click.option(
    "--interval",
    type=click.FloatRange(min=1),
    default=snipe_handler.DEFAULT_INTERVAL,
    show_default=True,
    help="Seconds between stock checks.",
)
@click.option(
    "--timeout",
    type=click.FloatRange(min=0),
    default=0,
    show_default=True,
    help="Give up after this many seconds; 0 waits until interrupted.",
)
@click.option(
    "--retry",
    type=click.IntRange(min=0),
    default=0,
    show_default=True,
    help="Retry transient API errors during polling up to this many times; 0 disables retries.",
)
@click.pass_context
def snipe_command(
    ctx: click.Context,
    regions: tuple[str, ...],
    gpu_types: tuple[str, ...],
    gpu_num: int,
    max_price: float | None,
    strategy: str,
    base_image_uuid: str,
    private_image_uuid: str,
    name: str,
    data_disk: int,
    interval: float,
    timeout: float,
    retry: int,
) -> None:
    """Watch GPU stock and order a machine as soon as one is available.

    At least one of ``--region`` and ``--gpu`` is required. ``--max-price`` and
    ``--gpu-num`` only narrow the search; they do not select a target on their
    own. Exactly one of ``--image`` and ``--private-image`` must be set. The
    command blocks until the ordered instance is running or ``--timeout``
    expires. Transient API errors while polling are retried ``--retry`` times
    consecutively; authentication errors are never retried and ``0`` disables
    retries. A machine whose order is rejected is skipped for an exponentially
    growing cooldown, so the next matching machine is tried instead.

    :param ctx: Click context; ``ctx.obj["json"]`` selects JSON output.
    :param regions: Region identifiers to search; empty means every region.
    :param gpu_types: Exact GPU model names to search for.
    :param gpu_num: Number of GPUs to request.
    :param max_price: Maximum pay-as-you-go price in yuan per hour.
    :param strategy: Machine ordering: ``price``, ``idle``, or ``first``.
    :param base_image_uuid: Base-image UUID to boot from.
    :param private_image_uuid: Private-image UUID to boot from.
    :param name: Optional instance name.
    :param data_disk: Extra data-disk size in GB.
    :param interval: Seconds between stock checks.
    :param timeout: Maximum seconds to wait; ``0`` waits until interrupted.
    :param retry: Consecutive transient polling errors to retry; ``0``
        disables retries.
    :raises click.UsageError: When no targeting filter or the wrong number of
        image UUIDs is supplied.
    :raises click.ClickException: When no token is configured, the request
        fails, or the snipe times out.
    """
    if not regions and not gpu_types:
        raise click.UsageError("Pass at least one of --region or --gpu.")
    if bool(base_image_uuid.strip()) == bool(private_image_uuid.strip()):
        raise click.UsageError("Pass exactly one of --image and --private-image.")

    config = load_config()
    token = require_token(config)
    as_json = bool(ctx.obj and ctx.obj.get("json"))

    try:
        with build_client(token, config) as client:
            result = snipe_handler.snipe(
                client,
                regions=regions,
                gpu_types=gpu_types,
                gpu_amount=gpu_num,
                max_price=max_price,
                strategy=strategy,
                base_image_uuid=base_image_uuid,
                private_image_uuid=private_image_uuid,
                instance_name=name,
                expand_data_disk=data_disk,
                interval=interval,
                timeout=timeout,
                retry=retry,
                on_event=None if as_json else _render_snipe_event,
            )
    except (ValueError, TimeoutError, AutoDLError) as exc:
        raise click.ClickException(str(exc)) from exc

    if as_json:
        output.render_json(result)
        return

    output.success(
        f"Instance {result['instance_uuid']} is running on machine {result['machine_id']} "
        f"in {result['region_name']} ({result['gpu_name']})."
    )
    output.info(f"Check its status with `autodl instance list -q {result['instance_uuid']}`.")


def register_tools(main_group: click.Group) -> click.Group:
    """Register the ``tools`` command group on ``main_group``.

    :param main_group: Root Click group.
    :returns: The same group, for chaining.
    """
    main_group.add_command(tools)
    return main_group
