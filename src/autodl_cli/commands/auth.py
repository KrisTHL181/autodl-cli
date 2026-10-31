"""``autodl auth`` — authentication commands.

Two flows are supported. Password login requires a device fingerprint captured
from the browser, because AutoDL ties its captcha counter to that value; the
``paste`` command stores a token and fingerprint copied from a browser session.
The password and pasted text are never echoed, logged, or written to disk:
only the resulting JWT and the reusable device fingerprint are persisted.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Mapping

import click

from autodl_cli import output
from autodl_cli.client import AutoDLClient
from autodl_cli.config import config_path, load_config, save_config
from autodl_cli.errors import AutoDLError
from autodl_cli.handlers import auth as auth_handler

#: A FingerprintJS visitor ID is exactly 32 lowercase hexadecimal characters.
_FINGERPRINT_PATTERN = re.compile(r"[0-9a-f]{32}")

#: The JWT shape used by the AutoDL API.
_JWT_PATTERN = r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"

_JWT_RE = re.compile(_JWT_PATTERN)

#: ``Authorization``/``token`` keys followed by a JWT, with optional quotes,
#: ``Bearer`` prefix, and ``:``/``=`` separator.
_TOKEN_KEY_RE = re.compile(
    rf"""
    (?<![A-Za-z0-9_])
    ["']?(?i:authorization|token)["']?
    \s*[:=]\s*
    ["']?\s*
    (?:(?i:bearer)\s+)?
    (?P<token>{_JWT_PATTERN})
    """,
    re.VERBOSE,
)

#: HAR header entries, where the name and value are separate JSON fields.
_HAR_AUTH_RE = re.compile(
    rf'"name"\s*:\s*"authorization"\s*,\s*"value"\s*:\s*"(?:(?i:bearer)\s+)?(?P<token>{_JWT_PATTERN})"',
    re.IGNORECASE,
)

#: ``device_fingerprint``/``deviceFingerprint`` keys followed by 32 hex chars.
_FINGERPRINT_KEY_RE = re.compile(
    r"""
    (?<![A-Za-z0-9_])
    ["']?(?i:device[_-]?fingerprint)["']?
    \s*[:=]\s*
    ["']?\s*
    (?P<fingerprint>[0-9a-f]{32})(?![0-9a-f])
    """,
    re.VERBOSE,
)

#: Paths that belong to the pre-login exchange rather than authenticated calls.
_PRE_LOGIN_PATH_RE = re.compile(r"/api/v1/(?:new_login|passport|login_failed/count|send_message)\b")

#: Keys whose presence marks a pre-login request body.
_PRE_LOGIN_KEY_RE = re.compile(
    r"""
    (?<![A-Za-z0-9_])
    ["']?(?i:password|ticket|v_code|captcha_verify_param)["']?
    \s*[:=]
    """,
    re.VERBOSE,
)

_PHONE_KEY_RE = re.compile(r"""(?i)(?<![A-Za-z0-9_])["']?phone["']?\s*[:=]""")
_TICKET_KEY_RE = re.compile(r"""(?i)(?<![A-Za-z0-9_])["']?ticket["']?\s*[:=]""")

_PASTE_PROMPT = (
    "Paste a cURL command, 'Authorization: ...' / 'device_fingerprint: ...' lines, "
    "JSON, or a HAR file (Ctrl+D to finish):"
)

_ACCEPTED_SHAPES = (
    "Paste a cURL command, an 'Authorization: ...' or 'device_fingerprint: ...' line, a JSON object, or a HAR file."
)


def _clean_token(value: str) -> str:
    """Strip quotes, whitespace, and a ``Bearer`` prefix from a token.

    :param value: Raw token candidate.
    :returns: The bare token.
    """
    token = value.strip().strip("\"'")
    if token.lower().startswith("bearer "):
        token = token[7:]
    return token.strip().strip("\"'").strip()


def _normalize_pasted_text(text: str) -> str:
    """Unescape quotes so HAR-embedded JSON matches the plain patterns.

    :param text: Raw pasted text.
    :returns: Text with each escaped double quote replaced by a plain one.
    """
    return text.replace('\\"', '"')


def _looks_like_pre_login_request(text: str) -> bool:
    """Return whether pasted text looks like an unauthenticated login request.

    :param text: Raw or normalized pasted text.
    :returns: ``True`` for a pre-login endpoint path, a login credential key,
        or a body containing both ``phone`` and ``device_fingerprint``.
    """
    normalized = _normalize_pasted_text(text)
    phone_and_fingerprint = bool(_PHONE_KEY_RE.search(normalized) and _FINGERPRINT_KEY_RE.search(normalized))
    return bool(_PRE_LOGIN_PATH_RE.search(normalized) or _PRE_LOGIN_KEY_RE.search(normalized) or phone_and_fingerprint)


def _has_ticket_marker(text: str) -> bool:
    """Return whether pasted text contains a ``ticket`` key/value.

    :param text: Raw or normalized pasted text.
    :returns: ``True`` when a ticket key is present.
    """
    return _TICKET_KEY_RE.search(_normalize_pasted_text(text)) is not None


def _extract_token(normalized: str) -> str | None:
    """Find the single token in already-normalised pasted text.

    :param normalized: Input with escaped quotes unescaped.
    :returns: The token, or ``None`` when no token-shaped value is present.
    :raises ValueError: When more than one distinct token is present.
    """
    keyed_tokens = {_clean_token(match.group("token")) for match in _TOKEN_KEY_RE.finditer(normalized)}
    keyed_tokens |= {_clean_token(match.group("token")) for match in _HAR_AUTH_RE.finditer(normalized)}
    keyed_tokens.discard("")

    if len(keyed_tokens) > 1:
        raise ValueError("multiple tokens found; paste the Authorization header for one account only")
    if keyed_tokens:
        return keyed_tokens.pop()

    unkeyed_tokens = {_clean_token(match) for match in _JWT_RE.findall(normalized)}
    if len(unkeyed_tokens) > 1:
        raise ValueError("multiple tokens found; paste the Authorization header for one account only")
    if unkeyed_tokens:
        return unkeyed_tokens.pop()
    return None


def _extract_fingerprint(normalized: str) -> str | None:
    """Find the single device fingerprint in normalised pasted text.

    Keyed matches always win over bare values, so unrelated 32-hex request IDs
    in a HAR file are ignored.

    :param normalized: Input with escaped quotes unescaped.
    :returns: The fingerprint, or ``None`` when none is present.
    :raises ValueError: When more than one distinct fingerprint is present.
    """
    keyed = {match.group("fingerprint") for match in _FINGERPRINT_KEY_RE.finditer(normalized)}
    if len(keyed) > 1:
        raise ValueError("multiple device fingerprints found; paste the login request for one account only")
    if keyed:
        return keyed.pop()

    candidates: set[str] = set()
    stripped = normalized.strip()
    if _FINGERPRINT_PATTERN.fullmatch(stripped):
        candidates.add(stripped)
    else:
        for line in normalized.splitlines():
            candidate = line.strip()
            if _FINGERPRINT_PATTERN.fullmatch(candidate):
                candidates.add(candidate)

    if len(candidates) > 1:
        raise ValueError("multiple device fingerprints found; paste the login request for one account only")
    if candidates:
        return candidates.pop()
    return None


def _parse_pasted_credentials(text: str) -> dict[str, str]:
    """Extract a token and device fingerprint from pasted browser data.

    Accepted shapes include cURL commands, ``Authorization`` /
    ``device_fingerprint`` header lines, JSON objects, bare JWTs, bare 32-hex
    fingerprints, and HAR files.

    :param text: Raw pasted text.
    :returns: Any found values under the ``"token"`` and/or
        ``"device_fingerprint"`` keys.
    :raises ValueError: When the input contains multiple distinct tokens or
        fingerprints.
    """
    normalized = _normalize_pasted_text(text)
    credentials: dict[str, str] = {}

    token = _extract_token(normalized)
    if token is not None:
        credentials["token"] = token

    fingerprint = _extract_fingerprint(normalized)
    if fingerprint is not None:
        credentials["device_fingerprint"] = fingerprint

    return credentials


def _resolve_fingerprint(config: dict[str, object]) -> str:
    """Return the stored browser device fingerprint.

    A random fingerprint would be unknown to AutoDL and trigger its captcha
    gate, so the CLI refuses to guess.

    :param config: Parsed local config.
    :returns: A valid 32-character lowercase hexadecimal fingerprint.
    :raises click.ClickException: When no valid fingerprint is stored.
    """
    stored = config.get("device_fingerprint")
    if isinstance(stored, str) and _FINGERPRINT_PATTERN.fullmatch(stored):
        return stored
    raise click.ClickException(
        "No device fingerprint is stored. Run `autodl auth paste` with your browser's login request "
        "(it contains device_fingerprint), then retry."
    )


def _user_identity(user: object) -> tuple[object, object]:
    """Extract a display name and numeric id from an API user object.

    :param user: The ``user`` value returned by the login endpoint.
    :returns: ``(username, uid)``, falling back to ``"unknown"``.
    """
    if isinstance(user, Mapping):
        username = user.get("username") or user.get("name") or user.get("nickname") or "unknown"
        uid = user.get("id") or user.get("uid") or user.get("user_id") or "unknown"
        return username, uid
    return "unknown", "unknown"


@click.group(help="Authenticate with the AutoDL API.")
def auth() -> None:
    """Authenticate with the AutoDL API."""


@auth.command("login", help="Log in and save the resulting token in the local config.")
@click.option("--phone", prompt="Phone", help="Phone number registered with AutoDL.")
@click.option(
    "--phone-area",
    default="+86",
    show_default=True,
    help="Phone area prefix.",
)
@click.password_option(envvar="AUTODL_PASSWORD", prompt="Password", confirmation_prompt=False)
@click.pass_context
def login(ctx: click.Context, phone: str, phone_area: str, password: str) -> None:
    """Log in and save the resulting token in the local config.

    :param ctx: Click context; ``ctx.obj["json"]`` selects JSON output.
    :param phone: Phone number registered with AutoDL.
    :param phone_area: Phone area prefix.
    :param password: Plaintext password, read from ``AUTODL_PASSWORD`` when
        the option is omitted.
    :raises click.ClickException: When no fingerprint is stored or the API
        rejects the credentials.
    """
    config = load_config()
    fingerprint = _resolve_fingerprint(config)

    try:
        with AutoDLClient(None) as client:
            result = auth_handler.login(
                client,
                phone,
                password,
                phone_area=phone_area,
                device_fingerprint=fingerprint,
            )
    except AutoDLError as exc:
        raise click.ClickException(str(exc)) from exc

    config["token"] = result["token"]
    config["phone_area"] = phone_area
    config["device_fingerprint"] = result.get("device_fingerprint") or fingerprint
    save_config(config)

    user = result.get("user")
    if ctx.obj and ctx.obj.get("json"):
        output.render_json(
            {
                "authenticated": True,
                "user": user,
                "config_path": str(config_path()),
            }
        )
        return

    username, uid = _user_identity(user)
    output.success(f"Logged in as {username} (uid {uid})")
    output.info(f"Token saved to {config_path()}")


@auth.command("paste", help="Save a token and device fingerprint copied from the browser.")
@click.option("--no-verify", is_flag=True, help="Save the token without checking it against the API.")
@click.pass_context
def paste(ctx: click.Context, no_verify: bool) -> None:
    """Save credentials copied from a browser session.

    The instruction is written to stderr so ``--json`` keeps stdout clean.

    :param ctx: Click context; ``ctx.obj["json"]`` selects JSON output.
    :param no_verify: Skip the ``/api/v1/user/detail`` token check.
    :raises click.ClickException: When the input is empty, contains no
        credentials, has ambiguous credentials, or fails verification.
    """
    click.echo(_PASTE_PROMPT, err=True)
    text = sys.stdin.read()
    if not text.strip():
        raise click.ClickException("No input detected.")

    try:
        credentials = _parse_pasted_credentials(text)
    except ValueError as exc:
        raise click.ClickException(f"{exc}. {_ACCEPTED_SHAPES}") from exc

    token = credentials.get("token")
    fingerprint = credentials.get("device_fingerprint")

    if not token and _looks_like_pre_login_request(text):
        if fingerprint:
            config = load_config()
            config["device_fingerprint"] = fingerprint
            save_config(config)
        message = "This looks like a pre-login request with no Authorization token. "
        if fingerprint:
            message += "The device fingerprint was saved. "
        if _has_ticket_marker(text):
            message += "Tickets are short-lived and cannot be reused. "
        message += "Run `autodl auth login` to complete login."
        raise click.ClickException(message)

    if not credentials:
        raise click.ClickException(f"No credentials found. {_ACCEPTED_SHAPES}")

    user: dict[str, object] | None = None
    if token and not no_verify:
        try:
            with AutoDLClient(token) as client:
                user = auth_handler.get_current_user(client)
        except AutoDLError as exc:
            raise click.ClickException(f"Token verification failed: {exc}") from exc

    config = load_config()
    if token:
        config["token"] = token
    if fingerprint:
        config["device_fingerprint"] = fingerprint
    save_config(config)

    if ctx.obj and ctx.obj.get("json"):
        output.render_json(
            {
                "authenticated": bool(token),
                "verified": user is not None,
                "user": user,
                "device_fingerprint_saved": bool(fingerprint),
                "config_path": str(config_path()),
            }
        )
        return

    if token:
        if user is not None:
            username, uid = _user_identity(user)
            output.success(f"Saved credentials for {username} (uid {uid}).")
        else:
            output.success("Saved API token (not verified).")
    elif fingerprint:
        output.success("Saved device fingerprint.")

    if token and not fingerprint:
        output.warning("No device fingerprint found; `autodl auth login` needs one.")
    if fingerprint and not token:
        output.warning("No API token found; authenticated commands need one.")
    output.info(f"Config: {config_path()}")


def register_auth(main_group: click.Group) -> click.Group:
    """Register the ``auth`` command group on ``main_group``.

    :param main_group: Root Click group.
    :returns: The same group, for chaining.
    """
    main_group.add_command(auth)
    return main_group
