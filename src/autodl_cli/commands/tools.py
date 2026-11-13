"""``autodl tools`` — general-purpose utility commands.

``request`` sends a raw HTTP request to any URL — the stored token and the
mandatory ``AppVersion`` header are attached only when the target is an
``autodl.com`` host — or prints an equivalent curl command. ``snipe`` watches
GPU stock and orders the first matching machine, optionally sending desktop
and webhook notifications and loading defaults from a TOML template.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import urlparse

import click

from autodl_cli import output
from autodl_cli.commands._helpers import build_client, require_token
from autodl_cli.commands._snipe_config import load_values as load_snipe_values
from autodl_cli.config import load_config
from autodl_cli.errors import AutoDLError
from autodl_cli.handlers import snipe as snipe_handler
from autodl_cli.handlers import tools as tools_handler
from autodl_cli.utils.notify import Notifier

#: Parameters that choose what ``snipe`` boots from. They are mutually
#: exclusive, so an explicit CLI choice suppresses template values for the
#: other members of the group.
_IMAGE_CHOICE_OPTIONS: tuple[str, ...] = ("base_image_uuid", "private_image_uuid", "clone_instance_uuid")


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
        action = "cloning..." if event.get("clone") else "ordering..."
        output.info(
            f"Found {machine.get('gpu_name', '')} on machine {machine.get('machine_id', '')} "
            f"({machine.get('region_name', '')}); {action}"
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
        if event.get("extra"):
            output.info(
                f"Ordered surplus instance {event.get('instance_uuid', '')} on machine "
                f"{machine.get('machine_id', '')}; powering off and releasing it..."
            )
        else:
            output.success(
                f"Ordered instance {event.get('instance_uuid', '')} on machine "
                f"{machine.get('machine_id', '')}; waiting for it to start..."
            )
        return
    if kind == "releasing_extra":
        machine = event.get("machine")
        machine = machine if isinstance(machine, dict) else {}
        output.info(
            f"Releasing surplus instance {event.get('instance_uuid', '')} on machine {machine.get('machine_id', '')}..."
        )
        return
    if kind == "extra_power_off_failed":
        output.warning(
            f"Could not power off surplus instance {event.get('instance_uuid', '')}: "
            f"{event.get('error', '')}; releasing it anyway."
        )
        return
    if kind == "extra_released":
        output.success(f"Released surplus instance {event.get('instance_uuid', '')}.")
        return
    if kind == "extra_release_failed":
        output.warning(
            f"Could not release surplus instance {event.get('instance_uuid', '')}: {event.get('error', '')}."
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
        output.info(f"Instance {event.get('instance_uuid', '')} is running.")


def _validate_webhook_urls(urls: tuple[str, ...]) -> None:
    """Reject webhook values that are not absolute HTTP(S) URLs.

    The invalid value is not echoed, because a webhook URL may contain a
    secret key.

    :param urls: Webhook URLs from the command line or a config template.
    :raises click.UsageError: When a URL is not absolute HTTP(S).
    """
    for url in urls:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise click.UsageError("--notify-webhook must be an absolute http or https URL.")


def _describe_snipe_notification(
    event: dict[str, object],
    seen: set[tuple[str, str]],
    machines: dict[str, dict[str, object]],
    gpu_num: int,
) -> tuple[str, str, str, dict[str, object]] | None:
    """Turn a snipe progress event into a notification description.

    Only kept ``ordered`` events and ``running`` events produce a
    notification. Surplus orders are ignored, and repeated events for the same
    instance are dropped.

    :param event: Event mapping emitted by the snipe handler.
    :param seen: ``(event, instance_uuid)`` pairs already notified.
    :param machines: Machine data remembered from ``ordered`` events, keyed by
        instance UUID.
    :param gpu_num: Requested GPU count, included in the webhook data.
    :returns: ``(event_name, title, body, fields)``, or ``None`` when the
        event does not notify.
    """
    kind = event.get("event")
    if kind not in ("ordered", "running"):
        return None
    if kind == "ordered" and event.get("extra"):
        return None

    instance_uuid = str(event.get("instance_uuid") or "")
    if not instance_uuid:
        return None

    machine = event.get("machine")
    machine = machine if isinstance(machine, dict) else {}
    if kind == "ordered":
        machines[instance_uuid] = machine
    else:
        machine = machines.get(instance_uuid, machine)

    key = (str(kind), instance_uuid)
    if key in seen:
        return None
    seen.add(key)

    machine_id = str(machine.get("machine_id") or "")
    region_name = str(machine.get("region_name") or "")
    gpu_name = str(machine.get("gpu_name") or "")

    if kind == "ordered":
        event_name = "snipe.ordered"
        title = "GPU ordered"
        body = f"Instance {instance_uuid} ordered on machine {machine_id} in {region_name} ({gpu_name})"
    else:
        event_name = "snipe.running"
        title = "Instance running"
        if machine_id and region_name:
            body = f"Instance {instance_uuid} is running on machine {machine_id} in {region_name}"
        else:
            body = f"Instance {instance_uuid} is running"

    fields: dict[str, object] = {
        "instance_uuid": instance_uuid,
        "machine_id": machine_id or None,
        "region_name": region_name or None,
        "gpu_name": gpu_name or None,
        "gpu_num": gpu_num,
    }
    return event_name, title, body, fields


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
@click.option(
    "--parallel",
    type=click.IntRange(min=1),
    default=1,
    show_default=True,
    help="Machines to try ordering concurrently each poll; surplus orders are released.",
)
@click.option(
    "--count",
    type=click.IntRange(min=1),
    default=1,
    show_default=True,
    help="Number of instances to keep; surplus successful orders are released.",
)
@click.option("--image", "-i", "base_image_uuid", default="", help="Base-image UUID from `autodl image list`.")
@click.option(
    "--private-image",
    "private_image_uuid",
    default="",
    help="Private-image UUID from `autodl image list-private`.",
)
@click.option(
    "--clone",
    "clone_instance_uuid",
    metavar="INSTANCE_UUID",
    default="",
    help="Clone this source instance instead of booting from an image.",
)
@click.option(
    "--copy-data-disk/--no-copy-data-disk",
    "copy_data_disk",
    default=True,
    show_default=True,
    help="Copy the source instance's data disk (requires --clone).",
)
@click.option(
    "--keep-service-address",
    "keep_service_address",
    is_flag=True,
    help="Keep the source instance's user service address (requires --clone).",
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
@click.option(
    "--notify/--no-notify",
    "notify",
    default=None,
    help="Send desktop and webhook notifications for orders, running instances, and failures.",
)
@click.option(
    "--notify-webhook",
    "notify_webhook",
    multiple=True,
    metavar="URL",
    help="POST notification events as JSON to this URL (repeatable; implies --notify).",
)
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, readable=True, path_type=Path),
    default=None,
    metavar="PATH",
    help="Load option defaults from a TOML template; command-line options win.",
)
@click.pass_context
def snipe_command(
    ctx: click.Context,
    regions: tuple[str, ...],
    gpu_types: tuple[str, ...],
    gpu_num: int,
    max_price: float | None,
    strategy: str,
    parallel: int,
    count: int,
    base_image_uuid: str,
    private_image_uuid: str,
    clone_instance_uuid: str,
    copy_data_disk: bool,
    keep_service_address: bool,
    name: str,
    data_disk: int,
    interval: float,
    timeout: float,
    retry: int,
    notify: bool | None,
    notify_webhook: tuple[str, ...],
    config_path: Path | None,
) -> None:
    """Watch GPU stock and order a machine as soon as one is available.

    At least one of ``--region`` and ``--gpu`` is required. ``--max-price`` and
    ``--gpu-num`` only narrow the search; they do not select a target on their
    own. Exactly one of ``--image`` and ``--private-image`` must be set, unless
    ``--clone`` names a source instance; that source's image is inherited and
    the two image flags are then rejected. ``--gpu-num`` is not inherited from
    the source and still defaults to 1. A clone copies the source's data disk
    unless ``--no-copy-data-disk`` is given, and does not keep its user service
    address unless ``--keep-service-address`` is given; both flags require
    ``--clone``. The command blocks until the ordered instances are running or
    ``--timeout`` expires. ``--parallel`` tries several ranked machines per
    poll, and ``--count`` keeps that many instances; any extra successful
    orders are powered off and released immediately (cleanup is not bounded by
    ``--timeout``). Transient API errors while polling are retried ``--retry``
    times consecutively; authentication errors are never retried and ``0``
    disables retries. A machine whose order is rejected is skipped for an
    exponentially growing cooldown, so the next matching machine is tried
    instead.

    ``--notify`` sends a desktop notification and a JSON POST to every
    ``--notify-webhook`` URL when an instance is ordered, when it starts
    running, and when the command fails. Passing ``--notify-webhook`` alone
    enables notifications, while ``--no-notify`` disables them even when the
    config template enables them. ``--config`` reads defaults from a flat TOML
    table whose keys mirror the long option names; explicitly supplied
    command-line options always win. Notification delivery failures are
    reported as warnings but never abort the snipe.

    :param ctx: Click context; ``ctx.obj["json"]`` selects JSON output.
    :param regions: Region identifiers to search; empty means every region.
    :param gpu_types: Exact GPU model names to search for.
    :param gpu_num: Number of GPUs to request.
    :param max_price: Maximum pay-as-you-go price in yuan per hour.
    :param strategy: Machine ordering: ``price``, ``idle``, or ``first``.
    :param parallel: Machines to try ordering concurrently each poll.
    :param count: Number of instances to keep.
    :param base_image_uuid: Base-image UUID to boot from.
    :param private_image_uuid: Private-image UUID to boot from.
    :param clone_instance_uuid: Source instance UUID to clone; mutually
        exclusive with the image UUIDs.
    :param copy_data_disk: Whether a clone copies the source's data disk.
    :param keep_service_address: Whether a clone keeps the source's user
        service address.
    :param name: Optional instance name.
    :param data_disk: Extra data-disk size in GB.
    :param interval: Seconds between stock checks.
    :param timeout: Maximum seconds to wait; ``0`` waits until interrupted.
    :param retry: Consecutive transient polling errors to retry; ``0``
        disables retries.
    :param notify: Tri-state notification switch; ``None`` enables them only
        when a webhook is configured.
    :param notify_webhook: Webhook URLs that receive JSON event payloads.
    :param config_path: Optional TOML template with option defaults.
    :raises click.UsageError: When no targeting filter is supplied, the image
        flags conflict with ``--clone``, the wrong number of image UUIDs is
        supplied, clone-only flags are used without ``--clone``, or a webhook
        URL is not absolute HTTP(S).
    :raises click.BadParameter: When the config template is invalid.
    :raises click.ClickException: When no token is configured, the request
        fails, or the snipe times out.
    """
    options: dict[str, object] = {
        "regions": regions,
        "gpu_types": gpu_types,
        "gpu_num": gpu_num,
        "max_price": max_price,
        "strategy": strategy,
        "parallel": parallel,
        "count": count,
        "base_image_uuid": base_image_uuid,
        "private_image_uuid": private_image_uuid,
        "clone_instance_uuid": clone_instance_uuid,
        "copy_data_disk": copy_data_disk,
        "keep_service_address": keep_service_address,
        "name": name,
        "data_disk": data_disk,
        "interval": interval,
        "timeout": timeout,
        "retry": retry,
        "notify": notify,
        "notify_webhook": notify_webhook,
    }
    if config_path is not None:
        explicit_image_choice = any(
            ctx.get_parameter_source(destination) is not click.core.ParameterSource.DEFAULT
            for destination in _IMAGE_CHOICE_OPTIONS
        )
        for destination, value in load_snipe_values(config_path, ctx.command.params).items():
            if ctx.get_parameter_source(destination) is not click.core.ParameterSource.DEFAULT:
                continue
            if explicit_image_choice and destination in _IMAGE_CHOICE_OPTIONS:
                continue
            options[destination] = value

    regions = options["regions"]
    gpu_types = options["gpu_types"]
    gpu_num = options["gpu_num"]
    max_price = options["max_price"]
    strategy = options["strategy"]
    parallel = options["parallel"]
    count = options["count"]
    base_image_uuid = options["base_image_uuid"]
    private_image_uuid = options["private_image_uuid"]
    clone_instance_uuid = options["clone_instance_uuid"]
    copy_data_disk = options["copy_data_disk"]
    keep_service_address = options["keep_service_address"]
    name = options["name"]
    data_disk = options["data_disk"]
    interval = options["interval"]
    timeout = options["timeout"]
    retry = options["retry"]
    notify = options["notify"]
    notify_webhook = options["notify_webhook"]

    clone_mode = bool(clone_instance_uuid.strip())
    if not regions and not gpu_types:
        raise click.UsageError("Pass at least one of --region or --gpu.")
    if clone_mode and (base_image_uuid.strip() or private_image_uuid.strip()):
        raise click.UsageError("Use either --clone or --image/--private-image, not both.")
    if not clone_mode and bool(base_image_uuid.strip()) == bool(private_image_uuid.strip()):
        raise click.UsageError("Pass exactly one of --image and --private-image.")
    if not clone_mode and (not copy_data_disk or keep_service_address):
        raise click.UsageError("--no-copy-data-disk and --keep-service-address require --clone.")

    _validate_webhook_urls(notify_webhook)
    notify_source = ctx.get_parameter_source("notify")
    webhook_source = ctx.get_parameter_source("notify_webhook")
    if notify_source is not click.core.ParameterSource.DEFAULT:
        enabled = bool(notify)
    elif webhook_source is not click.core.ParameterSource.DEFAULT and notify_webhook:
        enabled = True
    else:
        enabled = notify if notify is not None else bool(notify_webhook)
    notifier = Notifier(desktop=enabled, webhooks=notify_webhook if enabled else ())

    config = load_config()
    token = require_token(config)
    as_json = bool(ctx.obj and ctx.obj.get("json"))

    notified: set[tuple[str, str]] = set()
    ordered_machines: dict[str, dict[str, object]] = {}

    def on_event(progress_event: dict[str, object]) -> None:
        """Notify for selected events and render progress in human mode.

        :param progress_event: Event mapping emitted by the snipe handler.
        """
        description = _describe_snipe_notification(progress_event, notified, ordered_machines, gpu_num)
        if description is not None:
            event_name, title, body, fields = description
            for warning in notifier.send(event_name, title, body, **fields):
                if as_json:
                    output.error(warning)
                else:
                    output.warning(warning)
        if not as_json:
            _render_snipe_event(progress_event)

    try:
        with build_client(token, config) as client:
            result = snipe_handler.snipe(
                client,
                regions=regions,
                gpu_types=gpu_types,
                gpu_amount=gpu_num,
                max_price=max_price,
                strategy=strategy,
                parallel=parallel,
                count=count,
                base_image_uuid=base_image_uuid,
                private_image_uuid=private_image_uuid,
                clone_instance_uuid=clone_instance_uuid,
                copy_data_disk=copy_data_disk,
                keep_src_user_service_address=keep_service_address,
                instance_name=name,
                expand_data_disk=data_disk,
                interval=interval,
                timeout=timeout,
                retry=retry,
                on_event=on_event,
            )
    except (TimeoutError, AutoDLError) as exc:
        for warning in notifier.send("snipe.failed", "Snipe failed", str(exc), error_type=type(exc).__name__):
            if as_json:
                output.error(warning)
            else:
                output.warning(warning)
        raise click.ClickException(str(exc)) from exc
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    if as_json:
        output.render_json(result)
        return

    instances = result.get("instances")
    records = [record for record in instances if isinstance(record, dict)] if isinstance(instances, list) else []
    if not records:
        records = [result]
    for record in records:
        output.success(
            f"Instance {record['instance_uuid']} is running on machine {record['machine_id']} "
            f"in {record['region_name']} ({record['gpu_name']})."
        )
    for record in records:
        output.info(f"Check its status with `autodl instance list -q {record['instance_uuid']}`.")

    released_instances = result.get("released_instances")
    if isinstance(released_instances, list) and released_instances:
        output.success(f"Released {len(released_instances)} surplus instance(s).")
    release_failures = result.get("release_failures")
    if isinstance(release_failures, list):
        for failure in release_failures:
            if isinstance(failure, dict):
                output.warning(
                    f"Could not release surplus instance {failure.get('instance_uuid', '')}: "
                    f"{failure.get('error', '')}."
                )


def register_tools(main_group: click.Group) -> click.Group:
    """Register the ``tools`` command group on ``main_group``.

    :param main_group: Root Click group.
    :returns: The same group, for chaining.
    """
    main_group.add_command(tools)
    return main_group
