"""Load ``tools snipe`` defaults from a TOML template.

The template is a flat table whose keys mirror the command's long option names
with dashes normalised to underscores. Values are validated through the Click
parameter types used by the command, so integer ranges, float ranges, and
choice options behave exactly as they do on the command line.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import click

if sys.version_info >= (3, 11):
    import tomllib
else:  # Python 3.10
    import tomli as tomllib

if TYPE_CHECKING:
    from collections.abc import Iterable

#: Config key (normalised to underscores) to Click parameter name.
PARAMETER_NAMES: dict[str, str] = {
    "region": "regions",
    "gpu": "gpu_types",
    "gpu_num": "gpu_num",
    "max_price": "max_price",
    "strategy": "strategy",
    "parallel": "parallel",
    "count": "count",
    "image": "base_image_uuid",
    "private_image": "private_image_uuid",
    "clone": "clone_instance_uuid",
    "copy_data_disk": "copy_data_disk",
    "keep_service_address": "keep_service_address",
    "name": "name",
    "data_disk": "data_disk",
    "interval": "interval",
    "timeout": "timeout",
    "retry": "retry",
    "notify": "notify",
    "notify_webhook": "notify_webhook",
}


def _error(message: str) -> click.BadParameter:
    """Build a ``--config`` error.

    :param message: Error detail.
    :returns: A :class:`click.BadParameter` pointing at ``--config``.
    """
    return click.BadParameter(message, param_hint="--config")


def _expected_type(param: click.Parameter) -> type | tuple[type, ...] | None:
    """Return the Python type a TOML value must already have.

    Click's converters are deliberately lenient (``"1"`` becomes ``1`` and
    ``1`` becomes ``True``), but a config file should hold the declared type.
    Choices are left to Click's own membership check.

    :param param: Click parameter that owns the option.
    :returns: An accepted type or tuple of types, or ``None`` when the value
        should be handed straight to Click.
    """
    param_type = param.type
    if isinstance(param_type, click.types.BoolParamType):
        return bool
    if isinstance(param_type, click.types.IntParamType):
        return int
    if isinstance(param_type, click.types.FloatParamType):
        return (int, float)
    if isinstance(param_type, click.types.StringParamType):
        return str
    return None


def _type_matches(value: object, expected: type | tuple[type, ...]) -> bool:
    """Check a TOML value against the expected Python type.

    ``bool`` is a subclass of ``int``, so booleans are rejected wherever a
    number or an integer is expected.

    :param value: Value from the TOML document.
    :param expected: Accepted type or types.
    :returns: ``True`` when the value already has an accepted type.
    """
    if isinstance(value, bool) and expected is not bool:
        return False
    return isinstance(value, expected)


def _type_label(expected: type | tuple[type, ...]) -> str:
    """Describe an expected type for an error message.

    :param expected: Accepted type or types.
    :returns: A human-readable description of the expected value.
    """
    if expected is bool:
        return "a boolean"
    if expected is int:
        return "an integer"
    if expected == (int, float):
        return "a number"
    return "a string"


def _convert(value: object, param: click.Parameter, key: str) -> object:
    """Validate one value with the Click parameter's own type.

    The Python type is checked before Click's converter runs so that a config
    file cannot silently coerce a value (``true`` to ``1``, ``123`` to
    ``"123"``); range bounds and choices are still enforced by Click.

    :param value: Value from the TOML document.
    :param param: Click parameter that owns the option.
    :param key: Config key, used in the error message.
    :returns: The converted value.
    :raises click.BadParameter: When the value has the wrong Python type or
        does not convert.
    """
    expected = _expected_type(param)
    if expected is not None and not _type_matches(value, expected):
        label = _type_label(expected)
        raise _error(f"{key}: expected {label}, got {type(value).__name__}")
    try:
        return param.type.convert(value, param, None)
    except click.BadParameter as exc:
        raise _error(f"{key}: {exc.message}") from exc


def _convert_value(key: str, value: object, param: click.Parameter) -> object:
    """Convert one TOML value, normalising repeatable options to a tuple.

    Repeatable options accept either a single string or an array of strings.
    Other options accept exactly one scalar value.

    :param key: Config key, used in error messages.
    :param value: Value from the TOML document.
    :param param: Click parameter that owns the option.
    :returns: The converted value.
    :raises click.BadParameter: When the value is a table, an array for a
        single-value option, or cannot be converted by the parameter type.
    """
    if isinstance(value, dict):
        raise _error(f"{key}: nested tables are not supported")

    if param.multiple:
        items = value if isinstance(value, list) else [value]
        return tuple(_convert(item, param, key) for item in items)

    if isinstance(value, list):
        raise _error(f"{key}: expected a single value")
    return _convert(value, param, key)


def load_values(path: Path, params: Iterable[click.Parameter]) -> dict[str, object]:
    """Read and validate a snipe TOML template.

    Keys are normalised by replacing ``-`` with ``_``, so ``gpu-num`` and
    ``gpu_num`` are equivalent. Unknown keys, duplicate keys after
    normalisation, nested tables, unreadable files, and invalid TOML all raise
    a :class:`click.BadParameter` tied to ``--config``.

    :param path: Template path; ``~`` is expanded.
    :param params: Parameters of the snipe command, used for type conversion.
    :returns: Click parameter name to converted value.
    :raises click.BadParameter: When the file or any value is invalid.
    """
    resolved = path.expanduser()
    try:
        with resolved.open("rb") as handle:
            document = tomllib.load(handle)
    except OSError as exc:
        raise _error(f"cannot read {resolved}: {exc}") from exc
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise _error(f"invalid TOML in {resolved}: {exc}") from exc

    by_name = {param.name: param for param in params if param.name}
    values: dict[str, object] = {}
    seen: dict[str, str] = {}

    for raw_key, raw_value in document.items():
        key = raw_key.replace("-", "_")
        if key in seen:
            raise _error(f"duplicate option {key!r} (also written as {seen[key]!r})")
        seen[key] = raw_key

        destination = PARAMETER_NAMES.get(key)
        if destination is None:
            raise _error(f"unknown option {key!r}")
        param = by_name.get(destination)
        if param is None:
            raise _error(f"option {key!r} is not available")

        values[destination] = _convert_value(key, raw_value, param)

    return values
