"""``autodl image`` — base-image catalogue commands.

``list`` flattens the option tree served by ``POST /api/v1/image/all`` into one
row per selectable base image. Every filter is a case-insensitive substring
match, so ``--framework torch`` finds PyTorch and ``--cuda 12`` finds every
12.x toolkit. ``list-private`` shows the images saved from this account's
instances, reading ``POST /api/v1/image/private/list`` page by page;
``delete-private`` removes one by its numeric ID after a confirmation prompt.
"""

from __future__ import annotations

import click

from autodl_cli import output
from autodl_cli.commands._helpers import build_client, require_token
from autodl_cli.config import load_config
from autodl_cli.errors import AutoDLError
from autodl_cli.handlers import image as image_handler


@click.group(help="Browse AutoDL base images.")
def image() -> None:
    """Browse AutoDL base images."""


@image.command("list", help="Show the base images available for new instances.")
@click.option(
    "--framework",
    "-f",
    "framework_values",
    multiple=True,
    metavar="NAME",
    help="Framework name or fragment to include (repeatable), for example pytorch.",
)
@click.option(
    "--framework-version",
    "framework_version_values",
    multiple=True,
    metavar="VERSION",
    help="Framework version or fragment to include (repeatable), for example 2.12.",
)
@click.option(
    "--python",
    "python_values",
    multiple=True,
    metavar="VERSION",
    help="Python/OS label or fragment to include (repeatable), for example 3.12.",
)
@click.option(
    "--cuda",
    "cuda_values",
    multiple=True,
    metavar="VERSION",
    help="CUDA version or fragment to include (repeatable), for example 12.",
)
@click.option(
    "--chip",
    "chip_values",
    multiple=True,
    metavar="CORP",
    help="Chip vendor to include (repeatable), for example nvidia.",
)
@click.option(
    "--cpu-arch",
    "arch_values",
    multiple=True,
    metavar="ARCH",
    help="CPU architecture to include (repeatable), for example x86.",
)
@click.pass_context
def list_command(
    ctx: click.Context,
    framework_values: tuple[str, ...],
    framework_version_values: tuple[str, ...],
    python_values: tuple[str, ...],
    cuda_values: tuple[str, ...],
    chip_values: tuple[str, ...],
    arch_values: tuple[str, ...],
) -> None:
    """Show the selectable base images.

    The API returns a framework → version → Python/OS → CUDA tree; this command
    flattens it so each image's UUID is directly visible. Repeated filter values
    are ORed within one option and ANDed across options.

    :param ctx: Click context; ``ctx.obj["json"]`` selects JSON output.
    :param framework_values: Framework names or fragments to include.
    :param framework_version_values: Framework versions or fragments to include.
    :param python_values: Python/OS labels or fragments to include.
    :param cuda_values: CUDA versions or fragments to include.
    :param chip_values: Chip vendors to include.
    :param arch_values: CPU architectures to include.
    :raises click.ClickException: When a filter is empty, no token is
        configured, or the API call fails.
    """
    config = load_config()
    token = require_token(config)
    as_json = bool(ctx.obj and ctx.obj.get("json"))

    try:
        with build_client(token, config) as client:
            images = image_handler.list_images(
                client,
                frameworks=framework_values,
                framework_versions=framework_version_values,
                python_versions=python_values,
                cuda_versions=cuda_values,
                chip_corps=chip_values,
                cpu_archs=arch_values,
            )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    except AutoDLError as exc:
        raise click.ClickException(str(exc)) from exc

    if as_json:
        output.render_json(images)
        return

    output.render_images(images)


@image.command("list-private", help="List the private images saved from your instances.")
@click.option(
    "--page-size",
    default=image_handler.DEFAULT_PRIVATE_PAGE_SIZE,
    show_default=True,
    type=click.IntRange(min=1, max=image_handler.MAX_PRIVATE_PAGE_SIZE),
    help="Images requested per API call; every page is fetched.",
)
@click.pass_context
def list_private_command(ctx: click.Context, page_size: int) -> None:
    """List the private images saved from this account's instances.

    Each image reports its save status and progress, size, framework, and the
    UUID to use when ordering. Every page is fetched, so the result is not
    limited by AutoDL's per-request page size.

    :param ctx: Click context; ``ctx.obj["json"]`` selects JSON output.
    :param page_size: Images requested per API call.
    :raises click.ClickException: When no token is configured or the API call
        fails.
    """
    config = load_config()
    token = require_token(config)
    as_json = bool(ctx.obj and ctx.obj.get("json"))

    try:
        with build_client(token, config) as client:
            images = image_handler.list_private_images(client, page_size=page_size)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    except AutoDLError as exc:
        raise click.ClickException(str(exc)) from exc

    if as_json:
        output.render_json(images)
        return

    output.render_private_images(images)


@image.command("delete-private", help="Delete one of your private images.")
@click.argument("image_id", type=click.IntRange(min=1))
@click.option("--yes", "-y", is_flag=True, help="Delete without asking for confirmation.")
@click.pass_context
def delete_private_command(ctx: click.Context, image_id: int, yes: bool) -> None:
    """Delete one of your private images.

    ``IMAGE_ID`` is the numeric ``ID`` column from ``image list-private``, not
    the image UUID. Deletion is irreversible, so the command asks for
    confirmation unless ``--yes`` is passed; use ``--yes`` in scripts.

    :param ctx: Click context; ``ctx.obj["json"]`` selects JSON output.
    :param image_id: Numeric private-image ID.
    :param yes: Whether to skip the confirmation prompt.
    :raises click.ClickException: When no token is configured or the API call
        fails.
    :raises click.Abort: When the user declines the confirmation prompt.
    """
    config = load_config()
    token = require_token(config)
    if not yes:
        click.confirm(f"Delete private image {image_id}?", abort=True)

    as_json = bool(ctx.obj and ctx.obj.get("json"))

    try:
        with build_client(token, config) as client:
            result = image_handler.delete_private_image(client, image_id)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    except AutoDLError as exc:
        raise click.ClickException(str(exc)) from exc

    if as_json:
        output.render_json(result)
        return

    output.success(f"Deleted private image {result['image_id']}.")


def register_image(main_group: click.Group) -> click.Group:
    """Register the ``image`` command group on ``main_group``.

    :param main_group: Root Click group.
    :returns: The same group, for chaining.
    """
    main_group.add_command(image)
    return main_group
