"""``autodl instance`` — instance lifecycle commands.

``list`` is implemented against ``POST /api/v1/instance``; its ``--query``
filter is applied locally because the API has no keyword field. ``detail``
reads one instance's configuration snapshot from
``GET /api/v1/instance/snapshot``. ``create`` posts the web console's
pay-as-you-go order body to ``POST /api/v1/order/instance/create/payg`` and
can resolve a machine from ``--region``/``--gpu`` first. ``clone`` inherits the
source instance's image and GPU count and posts
``POST /api/v1/order/instance/clone/payg``, resolving the target machine the
same way. ``power-on`` and
``power-off`` post to
``POST /api/v1/instance/power_on`` and ``POST /api/v1/instance/power_off``,
which report success with a null ``data`` payload; ``power-on --non-gpu``
starts the instance in CPU-only mode. ``reset`` posts to
``POST /api/v1/instance/init``, rebuilding the system disk while keeping the
data disk, and asks for confirmation. ``change-image`` posts to
``POST /api/v1/instance/change_image`` to rebuild the system disk from another
base image, and asks for confirmation too. ``rename`` sends a
``PUT /api/v1/instance/name`` to set the instance name and does not prompt for
confirmation. ``release`` posts to
``POST /api/v1/instance/release`` and asks for confirmation because it deletes
the instance and its data disk. ``save-image`` posts to
``POST /api/v1/instance/image/save``. ``schedule-shutdown`` and
``cancel-shutdown`` post to ``POST /api/v1/instance/timed/shutdown`` to set,
modify, or clear an automatic shutdown time. The remaining lifecycle commands
wait for their handlers.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

import click

from autodl_cli import output
from autodl_cli.commands._helpers import build_client, require_token
from autodl_cli.config import load_config
from autodl_cli.errors import AutoDLError
from autodl_cli.handlers import instance as instance_handler

#: Accepted ``--at`` shape: date, ``T``/space, time, optional seconds and offset.
_AT_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})?$")

#: Accepted ``--in`` shape: one or more ``d``/``h``/``m``/``s`` components.
_DURATION_PATTERN = re.compile(r"^(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$")


def _now_beijing() -> datetime:
    """Return the current time in Beijing time (UTC+8).

    :returns: A timezone-aware datetime using the fixed UTC+8 offset.
    """
    return datetime.now(instance_handler.SHUTDOWN_TIMEZONE)


def _parse_at(text: str) -> datetime:
    """Parse an absolute shutdown time into Beijing time.

    Accepts ``YYYY-MM-DD HH:MM`` and ``YYYY-MM-DDTHH:MM``, optionally with
    seconds and a UTC offset such as ``+08:00`` or ``Z``. A naive value is
    interpreted as Beijing time; an aware value is converted to UTC+8.

    :param text: The ``--at`` option value.
    :returns: A timezone-aware datetime in UTC+8.
    :raises ValueError: When the text is not a supported timestamp.
    """
    value = text.strip()
    if not _AT_PATTERN.match(value):
        raise ValueError(f"Invalid --at value {text!r}; use 'YYYY-MM-DD HH:MM'.")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=instance_handler.SHUTDOWN_TIMEZONE)
    return parsed.astimezone(instance_handler.SHUTDOWN_TIMEZONE)


def _parse_duration(text: str) -> timedelta:
    """Parse a duration such as ``30m``, ``4h``, or ``1d2h``.

    Units are ``d``, ``h``, ``m``, and optionally ``s``. Seconds are rounded up
    to the next whole minute so the scheduled time keeps minute precision.

    :param text: The ``--in`` option value.
    :returns: A positive timedelta with whole-minute precision.
    :raises ValueError: When the text is unsupported or not positive.
    """
    value = text.strip().lower()
    match = _DURATION_PATTERN.match(value)
    if not match or not any(match.groups()):
        raise ValueError(f"Invalid --in value {text!r}; use durations like 30m, 4h, or 1d2h.")
    days, hours, minutes, seconds = (int(part) if part else 0 for part in match.groups())
    total_seconds = days * 86400 + hours * 3600 + minutes * 60 + seconds
    if total_seconds <= 0:
        raise ValueError("--in must be positive")
    return timedelta(minutes=(total_seconds + 59) // 60)


@click.group(help="Manage AutoDL container instances.")
def instance() -> None:
    """Manage AutoDL container instances."""


@instance.command("list", help="List every instance on the account.")
@click.option(
    "--status",
    "statuses",
    multiple=True,
    metavar="STATUS",
    help="Only instances in this status (repeatable).",
)
@click.option(
    "--charge-type",
    "charge_types",
    multiple=True,
    metavar="TYPE",
    help="Only instances with this billing mode (repeatable).",
)
@click.option("--sub-name", default="", help="Only instances whose sub-user name matches this value.")
@click.option("--unbind-sub-user", is_flag=True, help="Only instances with no bound sub-user.")
@click.option(
    "--query",
    "-q",
    default="",
    metavar="TEXT",
    help="Only instances whose UUID, name, region, machine alias, or GPU name contains this text.",
)
@click.option(
    "--page-size",
    default=instance_handler.DEFAULT_PAGE_SIZE,
    show_default=True,
    type=click.IntRange(min=1, max=100),
    help="Instances requested per API call.",
)
@click.pass_context
def list_command(
    ctx: click.Context,
    statuses: tuple[str, ...],
    charge_types: tuple[str, ...],
    sub_name: str,
    unbind_sub_user: bool,
    query: str,
    page_size: int,
) -> None:
    """List every instance on the account.

    :param ctx: Click context; ``ctx.obj["json"]`` selects JSON output.
    :param statuses: Status values to filter by; empty means no filter.
    :param charge_types: Billing modes to filter by; empty means no filter.
    :param sub_name: Sub-user name filter.
    :param unbind_sub_user: Whether to keep only instances with no bound
        sub-user.
    :param query: Free-text filter applied locally; empty means no filter.
    :param page_size: Instances requested per API call.
    :raises click.ClickException: When no token is configured or the API call
        fails.
    """
    config = load_config()
    token = require_token(config)

    try:
        with build_client(token, config) as client:
            instances = instance_handler.list_instances(
                client,
                page_size=page_size,
                statuses=statuses,
                charge_types=charge_types,
                sub_name=sub_name,
                unbind_sub_user=unbind_sub_user,
                query=query,
            )
    except AutoDLError as exc:
        raise click.ClickException(str(exc)) from exc

    if ctx.obj and ctx.obj.get("json"):
        output.render_json(instances)
        return

    output.render_instances(instances)


@instance.command("detail", help="Show one instance's configuration and machine details.")
@click.argument("instance_uuid")
@click.pass_context
def detail_command(ctx: click.Context, instance_uuid: str) -> None:
    """Show one instance's configuration and machine details.

    The snapshot covers the base image, GPU allocation, host machine, and
    prices. It does not include the live status or SSH command; use
    ``instance list`` for those.

    :param ctx: Click context; ``ctx.obj["json"]`` selects JSON output.
    :param instance_uuid: Instance UUID as printed by ``instance list``.
    :raises click.ClickException: When no token is configured or the API call
        fails.
    """
    config = load_config()
    token = require_token(config)

    try:
        with build_client(token, config) as client:
            detail = instance_handler.get_instance(client, instance_uuid)
    except AutoDLError as exc:
        raise click.ClickException(str(exc)) from exc

    if ctx.obj and ctx.obj.get("json"):
        output.render_json(detail)
        return

    output.render_instance_detail(detail, instance_uuid=instance_uuid)


@instance.command("rename", help="Rename an instance.")
@click.argument("instance_uuid")
@click.argument("new_name")
@click.pass_context
def rename_command(ctx: click.Context, instance_uuid: str, new_name: str) -> None:
    """Rename an instance.

    The new name is set immediately and appears in ``instance list``. The
    command does not ask for confirmation.

    :param ctx: Click context; ``ctx.obj["json"]`` selects JSON output.
    :param instance_uuid: Instance UUID as printed by ``instance list``.
    :param new_name: New instance name.
    :raises click.ClickException: When an argument is blank, no token is
        configured, or the API call fails.
    """
    config = load_config()
    token = require_token(config)

    try:
        with build_client(token, config) as client:
            result = instance_handler.rename_instance(client, instance_uuid, new_name)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    except AutoDLError as exc:
        raise click.ClickException(str(exc)) from exc

    if ctx.obj and ctx.obj.get("json"):
        output.render_json(result)
        return

    output.success(f"Renamed instance {result['instance_uuid']} to {result['instance_name']!r}.")


@instance.command("power-on", help="Power an instance on.")
@click.argument("instance_uuid")
@click.option(
    "--non-gpu",
    is_flag=True,
    help="Start the instance in CPU-only (no-GPU) mode.",
)
@click.pass_context
def power_on_command(ctx: click.Context, instance_uuid: str, non_gpu: bool) -> None:
    """Power an instance on, optionally in CPU-only mode.

    AutoDL accepts the request immediately; the instance may take a moment to
    start before it appears as running in ``instance list``. With ``--non-gpu``
    the instance boots without its GPUs, as the web console's no-GPU mode does.

    :param ctx: Click context; ``ctx.obj["json"]`` selects JSON output.
    :param instance_uuid: Instance UUID as printed by ``instance list``.
    :param non_gpu: Start the instance in CPU-only (no-GPU) mode.
    :raises click.ClickException: When the argument is blank, no token is
        configured, or the API call fails.
    """
    config = load_config()
    token = require_token(config)

    try:
        with build_client(token, config) as client:
            result = instance_handler.power_on(client, instance_uuid, non_gpu=non_gpu)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    except AutoDLError as exc:
        raise click.ClickException(str(exc)) from exc

    if ctx.obj and ctx.obj.get("json"):
        output.render_json(result)
        return

    mode = " in CPU-only mode" if non_gpu else ""
    output.success(f"Power-on requested for instance {result['instance_uuid']}{mode}.")


@instance.command("power-off", help="Power an instance off.")
@click.argument("instance_uuid")
@click.pass_context
def power_off_command(ctx: click.Context, instance_uuid: str) -> None:
    """Power an instance off.

    The data disk is kept; AutoDL releases a powered-off instance after the
    retention window shown by ``instance list`` unless it is powered on again.

    :param ctx: Click context; ``ctx.obj["json"]`` selects JSON output.
    :param instance_uuid: Instance UUID as printed by ``instance list``.
    :raises click.ClickException: When the argument is blank, no token is
        configured, or the API call fails.
    """
    config = load_config()
    token = require_token(config)

    try:
        with build_client(token, config) as client:
            result = instance_handler.power_off(client, instance_uuid)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    except AutoDLError as exc:
        raise click.ClickException(str(exc)) from exc

    if ctx.obj and ctx.obj.get("json"):
        output.render_json(result)
        return

    output.success(f"Power-off requested for instance {result['instance_uuid']}.")


@instance.command("schedule-shutdown", help="Schedule an automatic shutdown at a given time.")
@click.argument("instance_uuid")
@click.option(
    "--at",
    "at_time",
    default=None,
    help="Shut down at this time; naive values are Beijing time (UTC+8).",
)
@click.option(
    "--in",
    "in_duration",
    default=None,
    help="Shut down after this duration (e.g. 30m, 4h, 1d2h).",
)
@click.pass_context
def schedule_shutdown_command(
    ctx: click.Context,
    instance_uuid: str,
    at_time: str | None,
    in_duration: str | None,
) -> None:
    """Schedule an instance to shut down automatically at a given time.

    Pass exactly one of ``--at`` (``YYYY-MM-DD HH:MM``, optionally with a UTC
    offset) and ``--in`` (a duration such as ``30m`` or ``1d2h``). Naive times
    are Beijing time (UTC+8); an aware time is converted to UTC+8. A time in the
    past is rejected. Re-running the command with a new time changes the
    existing schedule. The command does not ask for confirmation.

    :param ctx: Click context; ``ctx.obj["json"]`` selects JSON output.
    :param instance_uuid: Instance UUID as printed by ``instance list``.
    :param at_time: Absolute time to shut down at; ``None`` when ``--in`` is used.
    :param in_duration: Delay before shutting down; ``None`` when ``--at`` is
        used.
    :raises click.ClickException: When neither or both of ``--at`` and ``--in``
        are given, a value cannot be parsed, or the time is in the past. Also
        raised when the argument is blank, no token is configured, or the API
        call fails.
    """
    if (at_time is None) == (in_duration is None):
        raise click.ClickException("Pass exactly one of --at and --in.")

    try:
        if at_time is not None:
            shutdown_at = _parse_at(at_time)
            if shutdown_at < _now_beijing():
                raise ValueError("--at must be in the future")
        else:
            shutdown_at = _now_beijing() + _parse_duration(in_duration or "")
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    config = load_config()
    token = require_token(config)

    try:
        with build_client(token, config) as client:
            result = instance_handler.schedule_shutdown(client, instance_uuid, shutdown_at=shutdown_at)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    except AutoDLError as exc:
        raise click.ClickException(str(exc)) from exc

    if ctx.obj and ctx.obj.get("json"):
        output.render_json(result)
        return

    output.success(f"Scheduled shutdown for instance {result['instance_uuid']} at {result['shutdown_at']} (UTC+8).")


@instance.command("cancel-shutdown", help="Cancel an instance's scheduled automatic shutdown.")
@click.argument("instance_uuid")
@click.pass_context
def cancel_shutdown_command(ctx: click.Context, instance_uuid: str) -> None:
    """Cancel an instance's scheduled automatic shutdown.

    There is no schedule left afterwards. The command does not ask for
    confirmation.

    :param ctx: Click context; ``ctx.obj["json"]`` selects JSON output.
    :param instance_uuid: Instance UUID as printed by ``instance list``.
    :raises click.ClickException: When the argument is blank, no token is
        configured, or the API call fails.
    """
    config = load_config()
    token = require_token(config)

    try:
        with build_client(token, config) as client:
            result = instance_handler.cancel_scheduled_shutdown(client, instance_uuid)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    except AutoDLError as exc:
        raise click.ClickException(str(exc)) from exc

    if ctx.obj and ctx.obj.get("json"):
        output.render_json(result)
        return

    output.success(f"Cancelled the scheduled shutdown for instance {result['instance_uuid']}.")


@instance.command("reset", help="Reset an instance, rebuilding its system disk.")
@click.argument("instance_uuid")
@click.option("--yes", "-y", is_flag=True, help="Reset without asking for confirmation.")
@click.pass_context
def reset_command(ctx: click.Context, instance_uuid: str, yes: bool) -> None:
    """Reset an instance, rebuilding its system disk.

    The system disk is restored from the instance's image, so changes made
    outside the data disk are lost; the data disk itself is kept. The command
    asks for confirmation unless ``--yes`` is passed; use ``--yes`` in scripts.

    :param ctx: Click context; ``ctx.obj["json"]`` selects JSON output.
    :param instance_uuid: Instance UUID as printed by ``instance list``.
    :param yes: Whether to skip the confirmation prompt.
    :raises click.ClickException: When the argument is blank, no token is
        configured, or the API call fails.
    :raises click.Abort: When the user declines the confirmation prompt.
    """
    config = load_config()
    token = require_token(config)
    if not yes:
        click.confirm(
            f"Reset instance {instance_uuid}? This rebuilds its system disk.",
            abort=True,
        )

    try:
        with build_client(token, config) as client:
            result = instance_handler.reset_instance(client, instance_uuid)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    except AutoDLError as exc:
        raise click.ClickException(str(exc)) from exc

    if ctx.obj and ctx.obj.get("json"):
        output.render_json(result)
        return

    output.success(f"Reset requested for instance {result['instance_uuid']}.")


@instance.command("change-image", help="Change an instance's image, rebuilding its system disk.")
@click.argument("instance_uuid")
@click.argument("base_image_uuid")
@click.option("--yes", "-y", is_flag=True, help="Change the image without asking for confirmation.")
@click.pass_context
def change_image_command(
    ctx: click.Context,
    instance_uuid: str,
    base_image_uuid: str,
    yes: bool,
) -> None:
    """Change an instance's image, rebuilding its system disk.

    The system disk is rebuilt from the new base image, so changes made outside
    the data disk are lost; the data disk itself is kept. The command asks for
    confirmation unless ``--yes`` is passed; use ``--yes`` in scripts.

    :param ctx: Click context; ``ctx.obj["json"]`` selects JSON output.
    :param instance_uuid: Instance UUID as printed by ``instance list``.
    :param base_image_uuid: Base-image UUID as printed by ``image list``.
    :param yes: Whether to skip the confirmation prompt.
    :raises click.ClickException: When an argument is blank, no token is
        configured, or the API call fails.
    :raises click.Abort: When the user declines the confirmation prompt.
    """
    config = load_config()
    token = require_token(config)
    if not yes:
        click.confirm(
            f"Change the image of instance {instance_uuid} to {base_image_uuid}? This rebuilds its system disk.",
            abort=True,
        )

    try:
        with build_client(token, config) as client:
            result = instance_handler.change_image(client, instance_uuid, base_image_uuid)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    except AutoDLError as exc:
        raise click.ClickException(str(exc)) from exc

    if ctx.obj and ctx.obj.get("json"):
        output.render_json(result)
        return

    output.success(f"Image change requested for {result['instance_uuid']}: {result['base_image_uuid']}.")


@instance.command("release", help="Release an instance, deleting it and its data disk.")
@click.argument("instance_uuid")
@click.option("--yes", "-y", is_flag=True, help="Release without asking for confirmation.")
@click.pass_context
def release_command(ctx: click.Context, instance_uuid: str, yes: bool) -> None:
    """Release an instance, deleting it and its data disk.

    Release is irreversible: the instance and its data disk are deleted. The
    command asks for confirmation unless ``--yes`` is passed; use ``--yes`` in
    scripts.

    :param ctx: Click context; ``ctx.obj["json"]`` selects JSON output.
    :param instance_uuid: Instance UUID as printed by ``instance list``.
    :param yes: Whether to skip the confirmation prompt.
    :raises click.ClickException: When the argument is blank, no token is
        configured, or the API call fails.
    :raises click.Abort: When the user declines the confirmation prompt.
    """
    config = load_config()
    token = require_token(config)
    if not yes:
        click.confirm(
            f"Release instance {instance_uuid}? This deletes it and its data disk.",
            abort=True,
        )

    try:
        with build_client(token, config) as client:
            result = instance_handler.release_instance(client, instance_uuid)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    except AutoDLError as exc:
        raise click.ClickException(str(exc)) from exc

    if ctx.obj and ctx.obj.get("json"):
        output.render_json(result)
        return

    output.success(f"Release requested for instance {result['instance_uuid']}.")


@instance.command("save-image", help="Save an instance as a custom image.")
@click.argument("instance_uuid")
@click.argument("image_name")
@click.option("--try-again", is_flag=True, help="Retry a previously failed save.")
@click.pass_context
def save_image_command(
    ctx: click.Context,
    instance_uuid: str,
    image_name: str,
    try_again: bool,
) -> None:
    """Save an instance as a custom image.

    AutoDL accepts the request and reports success immediately; the image may
    take longer to appear under the account's private images.

    :param ctx: Click context; ``ctx.obj["json"]`` selects JSON output.
    :param instance_uuid: Instance UUID as printed by ``instance list``.
    :param image_name: Name for the new image.
    :param try_again: Whether AutoDL should retry a previously failed save.
    :raises click.ClickException: When an argument is blank, no token is
        configured, or the API call fails.
    """
    config = load_config()
    token = require_token(config)

    try:
        with build_client(token, config) as client:
            result = instance_handler.save_image(
                client,
                instance_uuid,
                image_name,
                try_again=try_again,
            )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    except AutoDLError as exc:
        raise click.ClickException(str(exc)) from exc

    if ctx.obj and ctx.obj.get("json"):
        output.render_json(result)
        return

    output.success(f"Save requested for instance {result['instance_uuid']} as image {result['image_name']!r}.")


@instance.command("create", help="Order a pay-as-you-go instance.")
@click.option(
    "--machine-id",
    "-m",
    default="",
    help="Order on this machine ID (from `autodl gpu machines`).",
)
@click.option(
    "--region",
    "-r",
    default="",
    help="Resolve a machine in this region (needs --gpu).",
)
@click.option(
    "--gpu",
    "-g",
    default="",
    help="GPU model to require when resolving a machine (needs --region).",
)
@click.option(
    "--image",
    "-i",
    "base_image_uuid",
    default="",
    help="Base-image UUID from `autodl image list`.",
)
@click.option(
    "--private-image",
    "private_image_uuid",
    default="",
    help="Private-image UUID from `autodl image list-private`.",
)
@click.option("--gpu-num", type=click.IntRange(min=1), default=1, show_default=True, help="Number of GPUs to request.")
@click.option("--name", "-n", default="", help="Instance name.")
@click.option(
    "--data-disk",
    type=click.IntRange(min=0),
    default=0,
    show_default=True,
    help="Extra data-disk size in GB.",
)
@click.pass_context
def create_command(
    ctx: click.Context,
    machine_id: str,
    region: str,
    gpu: str,
    base_image_uuid: str,
    private_image_uuid: str,
    gpu_num: int,
    name: str,
    data_disk: int,
) -> None:
    """Order a pay-as-you-go instance.

    Pass either ``--machine-id`` or both ``--region`` and ``--gpu``. In the
    latter case the first machine in that region with enough idle GPUs of the
    requested model is ordered on. Exactly one of ``--image`` and
    ``--private-image`` must be set. The command does not ask for
    confirmation: AutoDL returns the new instance UUID immediately, and the
    instance may take a moment to appear in ``instance list``.

    :param ctx: Click context; ``ctx.obj["json"]`` selects JSON output.
    :param machine_id: Machine to order on; blank means resolve one.
    :param region: Region identifier used to resolve a machine.
    :param gpu: GPU model used to resolve a machine.
    :param base_image_uuid: Base-image UUID to boot from.
    :param private_image_uuid: Private-image UUID to boot from.
    :param gpu_num: Number of GPUs to request.
    :param name: Optional instance name.
    :param data_disk: Extra data-disk size in GB.
    :raises click.ClickException: When the selection options are inconsistent,
        an argument is invalid, no token is configured, or the API call fails.
    """
    if machine_id.strip() and (region.strip() or gpu.strip()):
        raise click.ClickException("Use either --machine-id or --region/--gpu, not both.")
    if not machine_id.strip() and not (region.strip() and gpu.strip()):
        raise click.ClickException("Pass --machine-id, or both --region and --gpu.")

    config = load_config()
    token = require_token(config)

    try:
        with build_client(token, config) as client:
            resolved_machine_id = machine_id.strip()
            if not resolved_machine_id:
                machine = instance_handler.select_machine(client, region=region, gpu=gpu, gpu_amount=gpu_num)
                resolved_machine_id = str(machine["machine_id"])
            result = instance_handler.create_instance(
                client,
                machine_id=resolved_machine_id,
                base_image_uuid=base_image_uuid,
                private_image_uuid=private_image_uuid,
                gpu_amount=gpu_num,
                instance_name=name,
                expand_data_disk=data_disk,
            )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    except AutoDLError as exc:
        raise click.ClickException(str(exc)) from exc

    if ctx.obj and ctx.obj.get("json"):
        output.render_json(result)
        return

    output.success(f"Instance {result['instance_uuid']} ordered on machine {result['machine_id']}.")
    output.info("Check its status with `autodl instance list`.")


@instance.command("clone", help="Clone an instance onto a machine.")
@click.argument("instance_uuid")
@click.option(
    "--machine-id",
    "-m",
    default="",
    help="Clone onto this machine ID (from `autodl gpu machines`).",
)
@click.option(
    "--region",
    "-r",
    default="",
    help="Resolve a machine in this region (needs --gpu).",
)
@click.option(
    "--gpu",
    "-g",
    default="",
    help="GPU model to require when resolving a machine (needs --region).",
)
@click.option(
    "--gpu-num",
    type=click.IntRange(min=1),
    default=None,
    help="Number of GPUs to request; defaults to the source instance's amount.",
)
@click.option("--name", "-n", default="", help="Name for the clone.")
@click.option(
    "--data-disk",
    type=click.IntRange(min=0),
    default=0,
    show_default=True,
    help="Extra data-disk size in GB.",
)
@click.option(
    "--copy-data-disk/--no-copy-data-disk",
    default=True,
    help="Copy the source instance's data disk.",
)
@click.option(
    "--keep-service-address",
    is_flag=True,
    help="Keep the source instance's user service address.",
)
@click.pass_context
def clone_command(
    ctx: click.Context,
    instance_uuid: str,
    machine_id: str,
    region: str,
    gpu: str,
    gpu_num: int | None,
    name: str,
    data_disk: int,
    copy_data_disk: bool,
    keep_service_address: bool,
) -> None:
    """Clone an instance onto a machine.

    Pass either ``--machine-id`` or both ``--region`` and ``--gpu``. In the
    latter case the first machine in that region with enough idle GPUs of the
    requested model is used. The image is inherited from the source instance.
    ``--gpu-num`` defaults to the source instance's GPU count. The command does
    not ask for confirmation: AutoDL returns the new instance UUID immediately,
    and the clone may take a moment to appear in ``instance list``.

    :param ctx: Click context; ``ctx.obj["json"]`` selects JSON output.
    :param instance_uuid: Source instance UUID as printed by ``instance list``.
    :param machine_id: Machine to clone onto; blank means resolve one.
    :param region: Region identifier used to resolve a machine.
    :param gpu: GPU model used to resolve a machine.
    :param gpu_num: Number of GPUs to request; ``None`` inherits the source's.
    :param name: Optional name for the clone.
    :param data_disk: Extra data-disk size in GB.
    :param copy_data_disk: Whether to copy the source instance's data disk.
    :param keep_service_address: Whether to keep the source's user service
        address.
    :raises click.ClickException: When the selection options are inconsistent,
        an argument is invalid, no token is configured, or the API call fails.
    """
    if machine_id.strip() and (region.strip() or gpu.strip()):
        raise click.ClickException("Use either --machine-id or --region/--gpu, not both.")
    if not machine_id.strip() and not (region.strip() and gpu.strip()):
        raise click.ClickException("Pass --machine-id, or both --region and --gpu.")

    config = load_config()
    token = require_token(config)

    try:
        with build_client(token, config) as client:
            source = instance_handler.resolve_clone_source(client, instance_uuid)
            gpu_amount = source["gpu_amount"] if gpu_num is None else gpu_num
            resolved_machine_id = machine_id.strip()
            if not resolved_machine_id:
                machine = instance_handler.select_machine(client, region=region, gpu=gpu, gpu_amount=gpu_amount)
                resolved_machine_id = str(machine["machine_id"])
            result = instance_handler.clone_instance(
                client,
                str(source["instance_uuid"]),
                machine_id=resolved_machine_id,
                base_image_uuid=str(source["base_image_uuid"]),
                private_image_uuid=str(source["private_image_uuid"]),
                gpu_amount=gpu_amount,
                instance_name=name,
                expand_data_disk=data_disk,
                copy_data_disk=copy_data_disk,
                keep_src_user_service_address=keep_service_address,
            )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    except AutoDLError as exc:
        raise click.ClickException(str(exc)) from exc

    if ctx.obj and ctx.obj.get("json"):
        output.render_json(result)
        return

    output.success(
        f"Instance {result['instance_uuid']} cloned from {result['source_instance_uuid']} "
        f"on machine {result['machine_id']}."
    )
    output.info("Check its status with `autodl instance list`.")


def register_instance(main_group: click.Group) -> click.Group:
    """Register the ``instance`` command group on ``main_group``.

    :param main_group: Root Click group.
    :returns: The same group, for chaining.
    """
    main_group.add_command(instance)
    return main_group
