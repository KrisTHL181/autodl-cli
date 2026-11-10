"""``autodl instance`` — instance lifecycle commands.

``list`` is implemented against ``POST /api/v1/instance``; its ``--query``
filter is applied locally because the API has no keyword field. ``detail``
reads one instance's configuration snapshot from
``GET /api/v1/instance/snapshot``. ``create`` posts the web console's
pay-as-you-go order body to ``POST /api/v1/order/instance/create/payg`` and
can resolve a machine from ``--region``/``--gpu`` first. ``power-on`` and
``power-off`` post to
``POST /api/v1/instance/power_on`` and ``POST /api/v1/instance/power_off``,
which report success with a null ``data`` payload; ``power-on --non-gpu``
starts the instance in CPU-only mode. ``reset`` posts to
``POST /api/v1/instance/init``, rebuilding the system disk while keeping the
data disk, and asks for confirmation. ``change-image`` posts to
``POST /api/v1/instance/change_image`` to rebuild the system disk from another
base image, and asks for confirmation too. ``release`` posts to
``POST /api/v1/instance/release`` and asks for confirmation because it deletes
the instance and its data disk. ``save-image`` posts to
``POST /api/v1/instance/image/save``. The remaining lifecycle commands wait for
their handlers.
"""

from __future__ import annotations

import click

from autodl_cli import output
from autodl_cli.commands._helpers import build_client, require_token
from autodl_cli.config import load_config
from autodl_cli.errors import AutoDLError
from autodl_cli.handlers import instance as instance_handler


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


def register_instance(main_group: click.Group) -> click.Group:
    """Register the ``instance`` command group on ``main_group``.

    :param main_group: Root Click group.
    :returns: The same group, for chaining.
    """
    main_group.add_command(instance)
    return main_group
