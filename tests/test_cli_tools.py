"""Tests for ``autodl tools`` commands through the real Click entry point."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from autodl_cli import config as config_module
from autodl_cli.commands import tools as tools_commands
from autodl_cli.main import main

TOKEN = "fake-token"
JSON_RESULT = {
    "url": "https://www.autodl.com/api/v1/example",
    "method": "GET",
    "status": 200,
    "reason": "OK",
    "headers": {"content-type": "application/json"},
    "text": '{"ok": true}',
    "content": b'{"ok": true}',
    "is_json": True,
    "json": {"ok": True},
}


@pytest.fixture
def home(monkeypatch, tmp_path: Path) -> Path:
    """Point the data tree at an isolated temporary directory.

    :param monkeypatch: pytest's monkeypatch fixture.
    :param tmp_path: Per-test temporary directory.
    :returns: The redirected home directory.
    """
    monkeypatch.setenv("AUTODL_CLI_HOME", str(tmp_path))
    return tmp_path


def _seed_token() -> None:
    """Store a token so an AutoDL request can run."""
    config_module.save_config({"token": TOKEN})


def _result(**overrides: object) -> dict[str, object]:
    """Build a handler result, optionally overriding fields.

    :param overrides: Fields to replace.
    :returns: A response mapping like the one returned by ``send_request``.
    """
    result = dict(JSON_RESULT)
    result.update(overrides)
    return result


def _patch_send_request(monkeypatch, result: dict[str, object], captured: dict[str, object] | None = None) -> None:
    """Replace the handler call so the command never touches the network.

    :param monkeypatch: pytest's monkeypatch fixture.
    :param result: Response mapping returned by the fake.
    :param captured: Optional mapping that receives the call arguments.
    """

    def fake_send_request(client, method, url, *, headers=None, data=None, include_auth=True):
        if captured is not None:
            captured.update(
                {
                    "method": method,
                    "url": url,
                    "headers": headers,
                    "data": data,
                    "include_auth": include_auth,
                }
            )
        return result

    monkeypatch.setattr(tools_commands.tools_handler, "send_request", fake_send_request)


def test_default_output_pretty_prints_json(home: Path, monkeypatch) -> None:
    """A JSON body is pretty-printed without a status line."""
    _seed_token()
    _patch_send_request(monkeypatch, _result())

    result = CliRunner().invoke(main, ["tools", "request", "/api/v1/example"])

    assert result.exit_code == 0, result.output
    assert result.output == '{\n  "ok": true\n}\n'


def test_include_prints_status_and_headers(home: Path, monkeypatch) -> None:
    """``--include`` prepends the status line, headers, and a blank line."""
    _seed_token()
    _patch_send_request(monkeypatch, _result())

    result = CliRunner().invoke(main, ["tools", "request", "/api/v1/example", "--include"])

    assert result.exit_code == 0, result.output
    assert result.output.startswith("HTTP 200 OK\n")
    assert "content-type: application/json" in result.output
    assert "HTTP 200 OK" in result.output
    assert result.output.index("content-type") < result.output.index('"ok"')
    assert "\n\n{\n" in result.output


def test_non_2xx_prints_body_and_exits_one(home: Path, monkeypatch) -> None:
    """A failed response is printed rather than turned into a ClickException."""
    _seed_token()
    _patch_send_request(
        monkeypatch,
        _result(
            status=500,
            reason="Internal Server Error",
            headers={"content-type": "text/plain"},
            text="boom",
            content=b"boom",
            is_json=False,
            json=None,
        ),
    )

    result = CliRunner().invoke(main, ["tools", "request", "/api/v1/example"])

    assert result.exit_code == 1
    assert "boom" in result.output
    assert "Traceback" not in result.output
    assert "HTTP 500" not in result.output


def test_json_flag_emits_envelope(home: Path, monkeypatch) -> None:
    """The global ``--json`` switch emits the documented envelope."""
    _seed_token()
    _patch_send_request(monkeypatch, _result())

    result = CliRunner().invoke(main, ["--json", "tools", "request", "/api/v1/example"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {
        "method": "GET",
        "url": "https://www.autodl.com/api/v1/example",
        "status": 200,
        "headers": {"content-type": "application/json"},
        "body": {"ok": True},
    }
    assert TOKEN not in result.output


def test_missing_token_on_autodl_path_gives_hint(home: Path, monkeypatch) -> None:
    """An AutoDL request without a token fails with the paste hint."""
    monkeypatch.setattr(
        tools_commands.tools_handler,
        "send_request",
        lambda *args, **kwargs: pytest.fail("the handler must not run without a token"),
    )

    result = CliRunner().invoke(main, ["tools", "request", "/api/v1/example"])

    assert result.exit_code == 1
    assert "autodl auth paste" in result.output
    assert "Traceback" not in result.output


def test_missing_token_is_allowed_for_external_url(home: Path, monkeypatch) -> None:
    """An external URL needs no token."""
    _patch_send_request(monkeypatch, _result(url="https://example.com/ping", headers={}))

    result = CliRunner().invoke(main, ["tools", "request", "https://example.com/ping"])

    assert result.exit_code == 0, result.output


def test_no_auth_does_not_require_token(home: Path, monkeypatch) -> None:
    """``--no-auth`` sends an AutoDL request without a stored token."""
    captured: dict[str, object] = {}
    _patch_send_request(monkeypatch, _result(), captured)

    result = CliRunner().invoke(main, ["tools", "request", "/api/v1/example", "--no-auth"])

    assert result.exit_code == 0, result.output
    assert captured["include_auth"] is False


def test_curl_prints_command_without_sending(home: Path, monkeypatch) -> None:
    """``--curl`` includes the token, method, and data and never sends."""
    _seed_token()
    monkeypatch.setattr(
        tools_commands.tools_handler,
        "send_request",
        lambda *args, **kwargs: pytest.fail("--curl must not send a request"),
    )

    result = CliRunner().invoke(
        main,
        ["tools", "request", "/api/v1/example", "--curl", "-X", "POST", "-d", '{"name": "value"}'],
    )

    assert result.exit_code == 0, result.output
    assert "curl" in result.output
    assert "-X POST" in result.output
    assert "Authorization: fake-token" in result.output
    assert "AppVersion: v6.53.0" in result.output
    assert "--data" in result.output
    assert "https://www.autodl.com/api/v1/example" in result.output


def test_curl_header_override_is_case_insensitive(home: Path, monkeypatch) -> None:
    """A differently-cased ``-H`` replaces the token instead of adding a second header."""
    _seed_token()
    monkeypatch.setattr(
        tools_commands.tools_handler,
        "send_request",
        lambda *args, **kwargs: pytest.fail("--curl must not send a request"),
    )

    result = CliRunner().invoke(
        main,
        ["tools", "request", "/api/v1/example", "--curl", "-H", "authorization: Bearer x"],
    )

    assert result.exit_code == 0, result.output
    authorization_lines = [line for line in result.output.splitlines() if "authorization:" in line.lower()]
    assert len(authorization_lines) == 1
    assert "Bearer x" in authorization_lines[0]
    assert "fake-token" not in result.output


def test_curl_auto_posts_when_data_is_given(home: Path, monkeypatch) -> None:
    """Data without an explicit method switches the curl command to POST."""
    _seed_token()
    monkeypatch.setattr(
        tools_commands.tools_handler,
        "send_request",
        lambda *args, **kwargs: pytest.fail("--curl must not send a request"),
    )

    result = CliRunner().invoke(main, ["tools", "request", "/api/v1/example", "--curl", "-d", "a=1"])

    assert result.exit_code == 0, result.output
    assert "-X POST" in result.output
    assert "Content-Type: application/x-www-form-urlencoded" in result.output
    assert "--data a=1" in result.output


def test_output_writes_raw_body(home: Path, monkeypatch, tmp_path: Path) -> None:
    """``--output`` writes the raw response bytes and reports success."""
    _seed_token()
    _patch_send_request(monkeypatch, _result())
    target = tmp_path / "body.json"

    result = CliRunner().invoke(main, ["tools", "request", "/api/v1/example", "-o", str(target)])

    assert result.exit_code == 0, result.output
    assert target.read_bytes() == b'{"ok": true}'
    assert "Response written" in result.output


def test_output_with_include_writes_text(home: Path, monkeypatch, tmp_path: Path) -> None:
    """With ``--include`` the file contains the status line and headers."""
    _seed_token()
    _patch_send_request(monkeypatch, _result())
    target = tmp_path / "response.txt"

    result = CliRunner().invoke(main, ["tools", "request", "/api/v1/example", "-o", str(target), "-i"])

    assert result.exit_code == 0, result.output
    written = target.read_text(encoding="utf-8")
    assert written.startswith("HTTP 200 OK\n")
    assert "content-type: application/json" in written
    assert '"ok": true' in written


def test_invalid_header_is_a_usage_error(home: Path, monkeypatch) -> None:
    """A header without ``:`` is rejected before anything is sent."""
    _seed_token()
    monkeypatch.setattr(
        tools_commands.tools_handler,
        "send_request",
        lambda *args, **kwargs: pytest.fail("an invalid header must not reach the handler"),
    )

    result = CliRunner().invoke(main, ["tools", "request", "/api/v1/example", "-H", "invalid"])

    assert result.exit_code == 2
    assert "invalid header" in result.output.lower()
