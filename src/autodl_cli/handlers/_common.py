"""Helpers shared by API handler modules.

The AutoDL API wraps every response in the same envelope::

    {"code": "Success", "msg": "...", "data": ..., "request_id": "..."}

Handlers use :func:`require_success` to validate that envelope and unwrap the
``data`` object instead of repeating the same checks.
"""

from __future__ import annotations

from autodl_cli.errors import APIError, AuthError, AutoDLError

#: Non-success codes that indicate the presentation token is unusable.
_AUTH_ERROR_CODES = frozenset({"AuthorizeFailed", "AuthError", "LoginRequired", "TokenExpired"})


def _unwrap(
    payload: dict[str, object],
    *,
    action: str,
    error_type: type[AutoDLError] | None = None,
) -> object:
    """Validate an API envelope and return its raw ``data`` value.

    :param payload: Decoded API response.
    :param action: Human-readable step name used in error messages.
    :param error_type: Exception class raised for a non-``Success`` code. When
        ``None``, auth-related codes raise :class:`AuthError` and every other
        failure raises :class:`APIError`.
    :returns: The ``data`` value, without checking its type.
    :raises autodl_cli.errors.AutoDLError: When ``code`` is not ``"Success"``.
    """
    code = payload.get("code")
    if code == "Success":
        return payload.get("data")

    message = payload.get("msg")
    if not isinstance(message, str) or not message:
        message = f"AutoDL {action} failed"
    request_id = payload.get("request_id")
    if isinstance(request_id, str) and request_id:
        message = f"{message} (request_id: {request_id})"

    if error_type is None:
        error_type = AuthError if isinstance(code, str) and code in _AUTH_ERROR_CODES else APIError
    raise error_type(message)


def require_success(
    payload: dict[str, object],
    *,
    action: str,
    error_type: type[AutoDLError] | None = None,
) -> dict[str, object]:
    """Validate an API envelope and return its ``data`` object.

    :param payload: Decoded API response.
    :param action: Human-readable step name used in error messages.
    :param error_type: Exception class raised for a non-``Success`` code. When
        ``None``, auth-related codes raise :class:`AuthError` and every other
        failure raises :class:`APIError`.
    :returns: The ``data`` mapping.
    :raises autodl_cli.errors.AutoDLError: When ``code`` is not ``"Success"``.
    :raises autodl_cli.errors.APIError: When a successful response has no
        object-valued ``data`` field.
    """
    data = _unwrap(payload, action=action, error_type=error_type)
    if isinstance(data, dict):
        return data
    raise APIError(f"AutoDL {action} returned malformed data")


def require_success_list(
    payload: dict[str, object],
    *,
    action: str,
    error_type: type[AutoDLError] | None = None,
) -> list[object]:
    """Validate an API envelope and return its ``data`` array.

    :param payload: Decoded API response.
    :param action: Human-readable step name used in error messages.
    :param error_type: Exception class raised for a non-``Success`` code. When
        ``None``, auth-related codes raise :class:`AuthError` and every other
        failure raises :class:`APIError`.
    :returns: The ``data`` list.
    :raises autodl_cli.errors.AutoDLError: When ``code`` is not ``"Success"``.
    :raises autodl_cli.errors.APIError: When a successful response has no
        list-valued ``data`` field.
    """
    data = _unwrap(payload, action=action, error_type=error_type)
    if isinstance(data, list):
        return data
    raise APIError(f"AutoDL {action} returned malformed data")


def require_success_any(
    payload: dict[str, object],
    *,
    action: str,
    error_type: type[AutoDLError] | None = None,
) -> object:
    """Validate an API envelope and return its ``data`` value unchanged.

    Write endpoints often answer with ``"data": null`` on success, so this
    helper checks only the ``code`` field instead of imposing a shape on the
    payload.

    :param payload: Decoded API response.
    :param action: Human-readable step name used in error messages.
    :param error_type: Exception class raised for a non-``Success`` code. When
        ``None``, auth-related codes raise :class:`AuthError` and every other
        failure raises :class:`APIError`.
    :returns: The ``data`` value, which may be ``None``.
    :raises autodl_cli.errors.AutoDLError: When ``code`` is not ``"Success"``.
    """
    return _unwrap(payload, action=action, error_type=error_type)
