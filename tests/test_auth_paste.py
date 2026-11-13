"""Tests for the ``autodl auth paste`` parser and command."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from autodl_cli import config as config_module
from autodl_cli.commands import auth as auth_commands
from autodl_cli.commands.auth import _looks_like_pre_login_request, _parse_pasted_credentials
from autodl_cli.errors import AuthError
from autodl_cli.main import main

JWT = "eyJhbGciOiJFUzI1NiJ9.eyJ1aWQiOjQyfQ.signature"
OTHER_JWT = "eyJhbGciOiJFUzI1NiJ9.eyJ1aWQiOjk5fQ.othersignature"
FINGERPRINT = "0123456789abcdef0123456789abcdef"
OTHER_FINGERPRINT = "fedcba9876543210fedcba9876543210"
PASSWORD_HASH = "5baa61e4c9b93f3f0682250b6cf8331b7ee68fd8"
USER = {"id": 42, "username": "tester"}


@pytest.fixture
def home(monkeypatch, tmp_path: Path) -> Path:
    """Point the data tree at an isolated temporary directory.

    :param monkeypatch: pytest's monkeypatch fixture.
    :param tmp_path: Per-test temporary directory.
    :returns: The redirected home directory.
    """
    monkeypatch.setenv("AUTODL_CLI_HOME", str(tmp_path))
    return tmp_path


def test_parser_curl_with_authorization_and_data() -> None:
    """A cURL command yields both the header token and the body fingerprint."""
    text = (
        "curl 'https://www.autodl.com/api/v1/new_login' \\\n"
        f"  -H 'Authorization: {JWT}' \\\n"
        '  --data-raw \'{"phone":"13800138000",'
        f'"device_fingerprint":"{FINGERPRINT}"}}\''
    )

    assert _parse_pasted_credentials(text) == {"token": JWT, "device_fingerprint": FINGERPRINT}


def test_parser_header_lines_with_bearer() -> None:
    """Header lines accept both the Bearer scheme and a fingerprint line."""
    text = f"Authorization: Bearer {JWT}\ndevice_fingerprint: {FINGERPRINT}\n"

    assert _parse_pasted_credentials(text) == {"token": JWT, "device_fingerprint": FINGERPRINT}


def test_parser_json_object() -> None:
    """A JSON object uses its ``token`` and ``device_fingerprint`` keys."""
    text = json.dumps({"token": JWT, "device_fingerprint": FINGERPRINT})

    assert _parse_pasted_credentials(text) == {"token": JWT, "device_fingerprint": FINGERPRINT}


def test_parser_bare_jwt() -> None:
    """A bare JWT is accepted as the whole input."""
    assert _parse_pasted_credentials(f"  {JWT}\n") == {"token": JWT}


def test_parser_bare_fingerprint() -> None:
    """A bare 32-hex fingerprint is accepted as the whole input."""
    assert _parse_pasted_credentials(f" {FINGERPRINT} \n") == {"device_fingerprint": FINGERPRINT}


def test_parser_token_only() -> None:
    """An ``Authorization=`` line without a fingerprint yields only a token."""
    assert _parse_pasted_credentials(f"Authorization={JWT}") == {"token": JWT}


def test_parser_fingerprint_only() -> None:
    """A camelCase fingerprint key without a token yields only a fingerprint."""
    assert _parse_pasted_credentials(f"deviceFingerprint={FINGERPRINT}") == {"device_fingerprint": FINGERPRINT}


def test_parser_har_prefers_keyed_fingerprint_over_request_ids() -> None:
    """HAR request IDs are ignored in favour of the keyed login fingerprint."""
    har = json.dumps(
        {
            "log": {
                "entries": [
                    {
                        "request": {
                            "headers": [
                                {"name": "x-request-id", "value": OTHER_FINGERPRINT},
                                {"name": "Authorization", "value": JWT},
                                {"name": "x-trace-id", "value": OTHER_FINGERPRINT},
                            ],
                            "postData": {
                                "text": json.dumps({"phone": "13800138000", "device_fingerprint": FINGERPRINT})
                            },
                        }
                    }
                ]
            }
        }
    )
    assert '\\"device_fingerprint\\"' in har

    parsed = _parse_pasted_credentials(har)

    assert parsed == {"token": JWT, "device_fingerprint": FINGERPRINT}
    assert OTHER_FINGERPRINT not in parsed.values()


def test_parser_multiple_distinct_tokens_raises() -> None:
    """Two unfettered JWTs are ambiguous."""
    with pytest.raises(ValueError, match="multiple tokens found"):
        _parse_pasted_credentials(f"{JWT}\n{OTHER_JWT}")


def test_parser_multiple_distinct_fingerprints_raises() -> None:
    """Two keyed fingerprints are ambiguous."""
    text = f"device_fingerprint: {FINGERPRINT}\ndevice_fingerprint: {OTHER_FINGERPRINT}"

    with pytest.raises(ValueError, match="multiple device fingerprints found"):
        _parse_pasted_credentials(text)


@pytest.mark.parametrize("text", ["", "   \n", "hello, this is not a credential"])
def test_parser_no_credentials_returns_empty(text: str) -> None:
    """Empty or unrelated prose yields no keys instead of guessing."""
    assert _parse_pasted_credentials(text) == {}


def test_paste_no_verify_saves_both(home: Path, monkeypatch) -> None:
    """``--no-verify`` stores the token and fingerprint without a request."""
    called = False

    def fail_verify(client):
        nonlocal called
        called = True
        raise AssertionError("verification must be skipped")

    monkeypatch.setattr(auth_commands.auth_handler, "get_current_user", fail_verify)

    text = f"Authorization: Bearer {JWT}\ndevice_fingerprint: {FINGERPRINT}"
    result = CliRunner().invoke(main, ["auth", "paste", "--no-verify"], input=text)

    assert result.exit_code == 0, result.output
    assert called is False
    saved = config_module.load_config()
    assert saved["token"] == JWT
    assert saved["device_fingerprint"] == FINGERPRINT
    assert JWT not in result.output
    assert "Saved API token (not verified)." in result.output


def test_paste_verified_json_output(home: Path, monkeypatch) -> None:
    """A verified token appears as the user in JSON, and the token stays hidden."""
    monkeypatch.setattr(auth_commands.auth_handler, "get_current_user", lambda client: USER)
    text = json.dumps({"token": JWT, "device_fingerprint": FINGERPRINT})

    result = CliRunner().invoke(main, ["--json", "auth", "paste"], input=text)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload == {
        "authenticated": True,
        "verified": True,
        "user": USER,
        "device_fingerprint_saved": True,
        "profile": "default",
        "profile_path": str(home / "profiles" / "default.toml"),
        "config_path": str(home / "config.toml"),
    }
    assert JWT not in result.output
    assert "Paste a cURL command" in result.stderr
    assert "Paste a cURL command" not in result.stdout
    assert config_module.load_config()["token"] == JWT


def test_paste_verification_failure_saves_nothing(home: Path, monkeypatch) -> None:
    """A rejected token exits 1 and leaves the previous config untouched."""
    config_module.save_config({"token": "old-token", "default_region": "west-b"})

    def reject(client):
        raise AuthError("token expired")

    monkeypatch.setattr(auth_commands.auth_handler, "get_current_user", reject)
    text = f"Authorization: Bearer {JWT}\ndevice_fingerprint: {FINGERPRINT}"

    result = CliRunner().invoke(main, ["--json", "auth", "paste"], input=text)

    assert result.exit_code == 1
    assert "Token verification failed: token expired" in result.output
    assert config_module.load_config() == {"token": "old-token", "default_region": "west-b"}


def test_paste_unparseable_input_fails(home: Path) -> None:
    """Prose with no credentials produces a clean error."""
    result = CliRunner().invoke(main, ["auth", "paste"], input="nothing useful here")

    assert result.exit_code == 1
    assert "No credentials found" in result.output
    assert "Traceback" not in result.output


def test_paste_empty_input_fails(home: Path) -> None:
    """Empty input produces the dedicated error."""
    result = CliRunner().invoke(main, ["auth", "paste"], input="   \n")

    assert result.exit_code == 1
    assert "No input detected." in result.output


def test_paste_fingerprint_only_preserves_token(home: Path) -> None:
    """A fingerprint-only paste keeps the existing token and other keys."""
    config_module.save_config({"token": "old-token", "default_region": "west-b"})

    result = CliRunner().invoke(main, ["--json", "auth", "paste"], input=FINGERPRINT)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload == {
        "authenticated": False,
        "verified": False,
        "user": None,
        "device_fingerprint_saved": True,
        "profile": "default",
        "profile_path": str(home / "profiles" / "default.toml"),
        "config_path": str(home / "config.toml"),
    }
    saved = config_module.load_config()
    assert saved == {
        "token": "old-token",
        "default_region": "west-b",
        "device_fingerprint": FINGERPRINT,
    }


def test_paste_token_only_preserves_fingerprint(home: Path, monkeypatch) -> None:
    """A token-only paste keeps the stored fingerprint and other keys."""
    config_module.save_config({"device_fingerprint": FINGERPRINT, "default_region": "west-b"})
    monkeypatch.setattr(auth_commands.auth_handler, "get_current_user", lambda client: USER)

    result = CliRunner().invoke(main, ["--json", "auth", "paste"], input=f"Authorization: Bearer {JWT}")

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["authenticated"] is True
    assert payload["verified"] is True
    assert payload["user"] == USER
    assert payload["device_fingerprint_saved"] is False
    saved = config_module.load_config()
    assert saved == {
        "token": JWT,
        "default_region": "west-b",
        "device_fingerprint": FINGERPRINT,
    }


def test_looks_like_pre_login_request_detection() -> None:
    """The detector recognises endpoint paths, credential keys, and phone bodies."""
    assert _looks_like_pre_login_request("https://www.autodl.com/api/v1/new_login")
    assert _looks_like_pre_login_request("POST /api/v1/login_failed/count")
    assert _looks_like_pre_login_request('{"password": "x"}')
    assert _looks_like_pre_login_request('{"ticket": "x"}')
    assert _looks_like_pre_login_request(f'{{"phone": "13800138000", "device_fingerprint": "{FINGERPRINT}"}}')
    assert not _looks_like_pre_login_request(FINGERPRINT)
    assert not _looks_like_pre_login_request("just some prose")


def test_paste_pre_login_new_login_saves_fingerprint_then_errors(home: Path) -> None:
    """A new_login body saves the fingerprint and refuses to store secrets."""
    body = json.dumps(
        {
            "phone": "13800138000",
            "password": PASSWORD_HASH,
            "v_code": "",
            "phone_area": "+86",
            "captcha_verify_param": None,
            "device_fingerprint": FINGERPRINT,
        }
    )

    result = CliRunner().invoke(main, ["auth", "paste"], input=body)

    assert result.exit_code == 1
    assert "pre-login request with no Authorization token" in result.output
    assert "The device fingerprint was saved." in result.output
    assert "Run `autodl auth login` to complete login." in result.output
    assert PASSWORD_HASH not in result.output
    assert config_module.load_config() == {"device_fingerprint": FINGERPRINT}


def test_paste_pre_login_login_failed_body_saves_fingerprint(home: Path) -> None:
    """A phone + fingerprint body is detected even without credential keys."""
    body = json.dumps({"phone": "13800138000", "device_fingerprint": FINGERPRINT})

    result = CliRunner().invoke(main, ["auth", "paste"], input=body)

    assert result.exit_code == 1
    assert "The device fingerprint was saved." in result.output
    assert "Run `autodl auth login` to complete login." in result.output
    assert "short-lived" not in result.output
    assert config_module.load_config() == {"device_fingerprint": FINGERPRINT}


def test_paste_pre_login_passport_mentions_short_lived_ticket(home: Path) -> None:
    """A passport request warns that its ticket cannot be reused."""
    text = (
        "curl 'https://www.autodl.com/api/v1/passport' \\\n"
        '  -d \'{"ticket":"fake-ticket","device":{"os":{"name":"Linux"}}}\''
    )

    result = CliRunner().invoke(main, ["auth", "paste"], input=text)

    assert result.exit_code == 1
    assert "Run `autodl auth login` to complete login." in result.output
    assert "Tickets are short-lived and cannot be reused." in result.output
    assert "device fingerprint was saved" not in result.output
    assert config_module.load_config() == {}


def test_paste_full_har_with_token_succeeds(home: Path, monkeypatch) -> None:
    """A token wins even when the same HAR contains pre-login entries."""
    monkeypatch.setattr(auth_commands.auth_handler, "get_current_user", lambda client: USER)
    har = json.dumps(
        {
            "log": {
                "entries": [
                    {
                        "request": {
                            "url": "https://www.autodl.com/api/v1/new_login",
                            "headers": [],
                            "postData": {
                                "text": json.dumps(
                                    {
                                        "phone": "13800138000",
                                        "password": PASSWORD_HASH,
                                        "v_code": "",
                                        "captcha_verify_param": None,
                                        "device_fingerprint": FINGERPRINT,
                                    }
                                )
                            },
                        }
                    },
                    {
                        "request": {
                            "url": "https://www.autodl.com/api/v1/user/detail",
                            "headers": [
                                {"name": "Authorization", "value": JWT},
                                {"name": "x-request-id", "value": OTHER_FINGERPRINT},
                            ],
                        }
                    },
                ]
            }
        }
    )

    result = CliRunner().invoke(main, ["--json", "auth", "paste"], input=har)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["authenticated"] is True
    assert JWT not in result.output
    saved = config_module.load_config()
    assert saved["token"] == JWT
    assert saved["device_fingerprint"] == FINGERPRINT


def test_paste_bare_fingerprint_still_exits_zero_with_warning(home: Path) -> None:
    """A bare fingerprint has no pre-login markers and keeps the old warning."""
    result = CliRunner().invoke(main, ["auth", "paste"], input=FINGERPRINT)

    assert result.exit_code == 0, result.output
    assert "Saved device fingerprint." in result.output
    assert "No API token found; authenticated commands need one." in result.output
    assert "pre-login" not in result.output
    assert "Run `autodl auth login`" not in result.output
    assert config_module.load_config() == {"device_fingerprint": FINGERPRINT}
    assert not (home / "profiles" / "default.toml").exists()
    assert not (home / "active_profile").exists()
