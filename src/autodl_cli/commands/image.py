"""``autodl image`` — base-image catalogue commands.

``list`` flattens the option tree served by ``POST /api/v1/image/all`` into one
row per selectable base image. Every filter is a case-insensitive substring
match, so ``--framework torch`` finds PyTorch and ``--cuda 12`` finds every
12.x toolkit.
"""

from __future__ import annotations

import click

from autodl_cli import output
from autodl_cli.client import AutoDLClient
from autodl_cli.commands._helpers import require_token
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
    token = require_token(load_config())
    as_json = bool(ctx.obj and ctx.obj.get("json"))

    try:
        with AutoDLClient(token) as client:
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


def register_image(main_group: click.Group) -> click.Group:
    """Register the ``image`` command group on ``main_group``.

    :param main_group: Root Click group.
    :returns: The same group, for chaining.
    """
    main_group.add_command(image)
    return main_group
