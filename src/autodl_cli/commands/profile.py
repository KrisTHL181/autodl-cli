"""``autodl profile`` — manage local credential profiles.

Each profile is a separate token and phone area, so one machine can switch
AutoDL accounts without pasting credentials again. Profile files live under
``profiles/`` in the autodl-cli data directory and the active name is recorded
in the ``active_profile`` pointer.
"""

from __future__ import annotations

import click

from autodl_cli import config, output


def _as_json(ctx: click.Context) -> bool:
    """Return whether the global ``--json`` switch is active.

    :param ctx: Current Click context.
    :returns: ``True`` when JSON output was requested.
    """
    return bool(ctx.obj and ctx.obj.get("json"))


@click.group(help="Manage saved account profiles.")
def profile() -> None:
    """Manage local credential profiles."""


@profile.command("list", help="List saved profiles.")
@click.pass_context
def profile_list(ctx: click.Context) -> None:
    """List every profile, marking the effective one.

    :param ctx: Click context; ``ctx.obj["json"]`` selects JSON output.
    """
    active, _ = config.current_profile()
    rows = [
        {"name": name, "active": name == active, "authenticated": config.profile_has_token(name)}
        for name in config.list_profiles()
    ]

    if _as_json(ctx):
        output.render_json(rows)
        return
    output.render_profiles(rows)


@profile.command("current", help="Show the effective profile and its source.")
@click.pass_context
def profile_current(ctx: click.Context) -> None:
    """Show the effective profile and where its selection came from.

    :param ctx: Click context; ``ctx.obj["json"]`` selects JSON output.
    """
    name, source = config.current_profile()
    if _as_json(ctx):
        output.render_json({"profile": name, "source": source})
        return
    output.render_profile(name, source)


@profile.command("switch", help="Make an existing profile the active one.")
@click.argument("name")
@click.pass_context
def profile_switch(ctx: click.Context, name: str) -> None:
    """Write the active-profile pointer.

    :param ctx: Click context; ``ctx.obj["json"]`` selects JSON output.
    :param name: Profile to activate; its file must exist, except for
        ``default``, which may be implicit.
    :raises click.ClickException: When the profile is invalid or does not
        exist.
    """
    try:
        config.switch_profile(name)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    if _as_json(ctx):
        output.render_json({"profile": name})
        return
    output.success(f"Switched to profile '{name}'.")


@profile.command("delete", help="Delete a saved profile.")
@click.argument("name")
@click.option("--yes", "-y", is_flag=True, help="Delete without asking for confirmation.")
@click.pass_context
def profile_delete(ctx: click.Context, name: str, yes: bool) -> None:
    """Delete a profile file, clearing the pointer when it was active.

    :param ctx: Click context; ``ctx.obj["json"]`` selects JSON output.
    :param name: Profile to delete; its file must exist.
    :param yes: Whether to skip the confirmation prompt.
    :raises click.ClickException: When the profile is invalid or does not
        exist.
    :raises click.Abort: When the user declines the confirmation prompt.
    """
    try:
        exists = config.profile_exists(name)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    if not exists:
        raise click.ClickException(f"Profile '{name}' does not exist.")

    if not yes:
        click.confirm(f"Delete profile '{name}'?", abort=True)

    try:
        config.delete_profile(name)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    if _as_json(ctx):
        output.render_json({"profile": name, "deleted": True})
        return
    output.success(f"Deleted profile '{name}'.")


def register_profile(main_group: click.Group) -> click.Group:
    """Register the ``profile`` command group on ``main_group``.

    :param main_group: Root Click group.
    :returns: The same group, for chaining.
    """
    main_group.add_command(profile)
    return main_group
