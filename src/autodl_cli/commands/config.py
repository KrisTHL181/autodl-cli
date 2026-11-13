"""``autodl config`` — local connection and credential settings.

Every item is a Click subgroup with ``set`` / ``show`` / ``clear`` commands.
The per-item boilerplate lives in :func:`_register_item`; adding a setting only
requires another :class:`_Item` entry.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import click

from autodl_cli import output
from autodl_cli.config import (
    current_profile,
    get_app_version,
    get_base_url,
    get_device_fingerprint,
    get_phone_area,
    get_timeout,
    get_token,
    set_app_version,
    set_base_url,
    set_device_fingerprint,
    set_phone_area,
    set_timeout,
    set_token,
)


@dataclass
class _Item:
    """Specification for one config subgroup with set/show/clear commands.

    :param name: CLI subgroup name, for example ``"base-url"``.
    :param display: Human-readable name used in success messages.
    :param label: Label shown by ``show``, before the colon.
    :param getter: Callable returning the effective value.
    :param setter: Callable accepting the new value, or ``None`` to delete.
    :param group_help: Help text for the subgroup.
    :param param_type: Click type used by ``set``.
    :param param_name: Argument name used by ``set``.
    :param fmt: Display formatter for non-secret values.
    :param show_none_msg: Message shown by ``show`` when the value is ``None``.
    :param clear_msg: Overrides the ``clear`` success message.
    :param secret: Whether the value must be masked in every output.
    :param profile_scoped: Whether the value belongs to the effective profile
        rather than the global config.
    """

    name: str
    display: str
    label: str
    getter: Callable[[], object]
    setter: Callable[[Any], None]
    group_help: str | None = None
    param_type: object = str
    param_name: str = "value"
    fmt: Callable[[object], str] | None = None
    show_none_msg: str | None = None
    clear_msg: str | None = None
    secret: bool = False
    profile_scoped: bool = False

    @property
    def key(self) -> str:
        """Return the JSON key for this item.

        :returns: The group name with dashes replaced by underscores.
        """
        return self.name.replace("-", "_")

    def _display(self, value: object) -> str:
        """Format *value* for human-readable output.

        :param value: Value to format.
        :returns: The masked value for secrets, otherwise the formatted value.
        """
        if self.secret and isinstance(value, str):
            return _mask(value)
        if self.fmt is not None:
            return self.fmt(value)
        return str(value)

    def _json_value(self, value: object) -> object:
        """Return *value* as it should appear in JSON output.

        :param value: Value to convert.
        :returns: The masked value for secrets, otherwise the value itself.
        """
        if self.secret and isinstance(value, str):
            return _mask(value)
        return value

    def _scope(self) -> str:
        """Return a suffix naming the effective profile.

        :returns: ``" (profile <name>)"`` for profile-scoped items, otherwise
            an empty string.
        """
        if not self.profile_scoped:
            return ""
        return f" (profile {current_profile()[0]})"


def _mask(value: str) -> str:
    """Mask a secret for display.

    :param value: Secret to mask.
    :returns: The first six and last four characters separated by an ellipsis,
        or one ``*`` per character when the value is short.
    """
    if len(value) <= 10:
        return "*" * len(value)
    return f"{value[:6]}…{value[-4:]}"


def _as_json(ctx: click.Context) -> bool:
    """Return whether the global ``--json`` switch is active.

    :param ctx: Current Click context.
    :returns: ``True`` when JSON output was requested.
    """
    return bool(ctx.obj and ctx.obj.get("json"))


def _register_item(config_group: click.Group, item: _Item) -> None:
    """Register a ``set`` / ``show`` / ``clear`` subgroup for *item*.

    :param config_group: The ``config`` Click group.
    :param item: Specification of the config key.
    """

    @config_group.group(item.name, help=item.group_help or f"Manage {item.display.lower()}.")
    def subgroup() -> None:
        """Manage one config item."""

    @subgroup.command("set")
    @click.argument(item.param_name, type=item.param_type)
    @click.pass_context
    def cmd_set(ctx: click.Context, **kwargs: Any) -> None:
        """Set the value."""
        value = kwargs[item.param_name]
        try:
            item.setter(value)
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc

        current = item.getter()
        if _as_json(ctx):
            output.render_json({item.key: item._json_value(current)})
            return
        output.success(f"{item.display} set to: {item._display(current)}{item._scope()}")

    cmd_set.help = f"Set the {item.display.lower()}."

    @subgroup.command("show")
    @click.pass_context
    def cmd_show(ctx: click.Context) -> None:
        """Show the current value."""
        value = item.getter()
        if _as_json(ctx):
            output.render_json({item.key: item._json_value(value)})
            return
        if value is None and item.show_none_msg:
            output.info(item.show_none_msg)
            if item.profile_scoped:
                output.info(f"Profile: {current_profile()[0]}")
            return
        output.info(f"{item.label}: {item._display(value)}{item._scope()}")

    cmd_show.help = f"Show the current {item.display.lower()}."

    @subgroup.command("clear")
    @click.pass_context
    def cmd_clear(ctx: click.Context) -> None:
        """Remove the stored override so the default applies again."""
        item.setter(None)

        current = item.getter()
        if _as_json(ctx):
            output.render_json({item.key: item._json_value(current)})
            return
        if item.clear_msg:
            output.success(f"{item.clear_msg}{item._scope()}")
            return
        output.success(f"{item.display} reset to: {item._display(current)}{item._scope()}")

    cmd_clear.help = f"Reset {item.display.lower()} to its default."


_CONFIG_ITEMS: list[_Item] = [
    _Item(
        name="token",
        display="API token",
        label="Token",
        getter=get_token,
        setter=set_token,
        secret=True,
        profile_scoped=True,
        show_none_msg="No API token configured (run `autodl auth paste`).",
        clear_msg="API token cleared (run `autodl auth paste` to authenticate again).",
        group_help="""Manage the stored AutoDL API token.

The token is normally managed by `autodl auth login` and `autodl auth paste`;
use this group to inspect or replace it directly. The value is masked in every
command's output.

The token belongs to the effective profile. Use `--profile NAME`, the
`AUTODL_PROFILE` environment variable, or `autodl profile switch` to choose a
different account.""",
    ),
    _Item(
        name="device-fingerprint",
        display="Device fingerprint",
        label="Device fingerprint",
        getter=get_device_fingerprint,
        setter=set_device_fingerprint,
        show_none_msg="No device fingerprint configured.",
        clear_msg="Device fingerprint cleared.",
        group_help="""Manage the browser device fingerprint used by `autodl auth login`.

The fingerprint must be 32 lowercase hexadecimal characters. It is normally
saved by `autodl auth paste` from a browser login request.""",
    ),
    _Item(
        name="phone-area",
        display="Phone area prefix",
        label="Phone area",
        getter=get_phone_area,
        setter=set_phone_area,
        profile_scoped=True,
        group_help="""Manage the default phone area prefix for `autodl auth login`.

`autodl auth login` uses this value when `--phone-area` is omitted.

The value belongs to the effective profile, so each account can keep its own
prefix.""",
    ),
    _Item(
        name="base-url",
        display="API base URL",
        label="Base URL",
        getter=get_base_url,
        setter=set_base_url,
        group_help="""Manage the API root used by every request.

Override it to point the CLI at a mirror, a proxy, or a local test server.""",
    ),
    _Item(
        name="timeout",
        display="Request timeout",
        label="Timeout",
        getter=get_timeout,
        setter=set_timeout,
        param_type=float,
        param_name="seconds",
        fmt=lambda value: f"{value:g}s",
        group_help="""Manage the per-request timeout in seconds.

The value must be greater than 0 and at most 600.""",
    ),
    _Item(
        name="app-version",
        display="AppVersion header",
        label="AppVersion",
        getter=get_app_version,
        setter=set_app_version,
        group_help="""Manage the value of the mandatory `AppVersion` header.

Every API request carries this header. Bump it when AutoDL rejects the pinned
version.""",
    ),
]


def register_config(main_group: click.Group) -> click.Group:
    """Register the ``config`` command group on ``main_group``.

    :param main_group: Root Click group.
    :returns: The same group, for chaining.
    """

    @main_group.group()
    def config() -> None:
        """Manage local autodl-cli configuration."""

    for item in _CONFIG_ITEMS:
        _register_item(config, item)

    return main_group
