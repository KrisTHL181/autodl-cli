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


SNIPE_RESULT = {
    "instance_uuid": "snipe-instance-1",
    "machine_id": "m-1",
    "machine_alias": "worker",
    "region_name": "西北B区",
    "region_sign": "west-B",
    "gpu_name": "RTX 3090",
    "gpu_idle_num": 2,
    "payg_price": 1.48,
    "gpu_amount": 1,
    "charge_type": "payg",
    "base_image_uuid": "base-image-x",
    "private_image_uuid": "",
    "instance_name": "",
    "expand_data_disk": 0,
    "status": "running",
    "attempts": 2,
    "elapsed_seconds": 10.0,
}


def _patch_snipe(
    monkeypatch,
    *,
    events: bool = False,
    captured: dict[str, object] | None = None,
) -> None:
    """Replace the snipe handler so the command never touches the network.

    :param monkeypatch: pytest's monkeypatch fixture.
    :param events: Whether the fake should emit progress events.
    :param captured: Optional mapping that receives the call arguments.
    """
    result = dict(SNIPE_RESULT)

    def fake_snipe(client, **kwargs):
        if captured is not None:
            captured.update(kwargs)
        on_event = kwargs.get("on_event")
        if events and on_event is not None:
            machine = {
                "machine_id": result["machine_id"],
                "gpu_name": result["gpu_name"],
                "region_name": result["region_name"],
            }
            on_event({"event": "poll", "attempt": 1, "matches": 3, "cooling": 2})
            on_event({"event": "poll_failed", "error": "HTTP 500", "retries": 1, "limit": 3})
            on_event({"event": "found", "machine": machine})
            on_event(
                {
                    "event": "order_failed",
                    "machine_id": "m-1",
                    "error": "no capacity",
                    "failures": 2,
                    "backoff": 10.0,
                }
            )
            on_event(
                {
                    "event": "ordered",
                    "instance_uuid": result["instance_uuid"],
                    "machine": machine,
                }
            )
            on_event(
                {
                    "event": "instance_status",
                    "instance_uuid": result["instance_uuid"],
                    "status": "not found",
                }
            )
            on_event(
                {
                    "event": "instance_status",
                    "instance_uuid": result["instance_uuid"],
                    "status": "creating",
                }
            )
            on_event({"event": "running", "instance_uuid": result["instance_uuid"]})
        return result

    monkeypatch.setattr(tools_commands.snipe_handler, "snipe", fake_snipe)


def test_snipe_renders_progress_and_final_success(home: Path, monkeypatch) -> None:
    """Progress events become human-readable lines before the final summary."""
    _seed_token()
    captured: dict[str, object] = {}
    _patch_snipe(monkeypatch, events=True, captured=captured)

    result = CliRunner().invoke(
        main,
        ["tools", "snipe", "--gpu", "RTX 3090", "--image", "base-image-x"],
    )

    assert result.exit_code == 0, result.output
    assert "Poll #1: 3 matching machine(s), 2 cooling down." in result.output
    assert "Poll failed: HTTP 500; retrying (1/3)." in result.output
    assert "Found RTX 3090 on machine m-1 (西北B区); ordering..." in result.output
    assert "Order failed on machine m-1: no capacity; backing off for 10s (failure #2)." in result.output
    assert "Ordered instance snipe-instance-1 on machine m-1; waiting for it to start..." in result.output
    assert "Instance status: not visible yet." in result.output
    assert "Instance status: creating." in result.output
    assert "Instance is running." in result.output
    assert "Instance snipe-instance-1 is running on machine m-1" in result.output
    assert "autodl instance list -q snipe-instance-1" in result.output

    assert captured["gpu_types"] == ("RTX 3090",)
    assert captured["regions"] == ()
    assert captured["base_image_uuid"] == "base-image-x"
    assert captured["on_event"] is not None


def test_snipe_accepts_region_alone(home: Path, monkeypatch) -> None:
    """A region by itself is a valid targeting filter."""
    _seed_token()
    captured: dict[str, object] = {}
    _patch_snipe(monkeypatch, captured=captured)

    result = CliRunner().invoke(
        main,
        ["tools", "snipe", "--region", "west-B", "--image", "base-image-x"],
    )

    assert result.exit_code == 0, result.output
    assert captured["regions"] == ("west-B",)
    assert captured["gpu_types"] == ()


def test_snipe_forwards_retry_to_the_handler(home: Path, monkeypatch) -> None:
    """``--retry`` reaches the handler unchanged."""
    _seed_token()
    captured: dict[str, object] = {}
    _patch_snipe(monkeypatch, captured=captured)

    result = CliRunner().invoke(
        main,
        ["tools", "snipe", "--gpu", "RTX 3090", "--image", "base-image-x", "--retry", "3"],
    )

    assert result.exit_code == 0, result.output
    assert captured["retry"] == 3


def test_snipe_rejects_negative_retry(home: Path) -> None:
    """A negative retry count is a usage error before the handler runs."""
    result = CliRunner().invoke(
        main,
        ["tools", "snipe", "--gpu", "RTX 3090", "--image", "base-image-x", "--retry", "-1"],
    )

    assert result.exit_code == 2
    assert "--retry" in result.output


def test_snipe_json_emits_only_the_result(home: Path, monkeypatch) -> None:
    """``--json`` suppresses progress text and prints one JSON document."""
    _seed_token()
    _patch_snipe(monkeypatch, events=True)

    result = CliRunner().invoke(
        main,
        ["--json", "tools", "snipe", "--gpu", "RTX 3090", "--image", "base-image-x"],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == SNIPE_RESULT
    assert "Poll" not in result.output
    assert "Instance is running." not in result.output


@pytest.mark.parametrize(
    "args",
    [
        ["--max-price", "1.5"],
        ["--gpu-num", "2"],
        ["--max-price", "1.5", "--gpu-num", "2"],
    ],
)
def test_snipe_requires_a_targeting_filter(home: Path, monkeypatch, args: list[str]) -> None:
    """Price and GPU count alone do not select a target."""
    _seed_token()
    monkeypatch.setattr(
        tools_commands.snipe_handler,
        "snipe",
        lambda *call_args, **call_kwargs: pytest.fail("the handler must not run without a target"),
    )

    result = CliRunner().invoke(main, ["tools", "snipe", *args, "--image", "base-image-x"])

    assert result.exit_code == 2
    assert "Pass at least one of --region or --gpu." in result.output


@pytest.mark.parametrize(
    "args",
    [
        ["--gpu", "RTX 3090"],
        ["--gpu", "RTX 3090", "--image", "base-image-x", "--private-image", "image-y"],
    ],
)
def test_snipe_requires_exactly_one_image(home: Path, monkeypatch, args: list[str]) -> None:
    """Both or neither image UUID is a usage error."""
    _seed_token()
    monkeypatch.setattr(
        tools_commands.snipe_handler,
        "snipe",
        lambda *call_args, **call_kwargs: pytest.fail("the handler must not run with bad images"),
    )

    result = CliRunner().invoke(main, ["tools", "snipe", *args])

    assert result.exit_code == 2
    assert "Pass exactly one of --image and --private-image." in result.output


def test_snipe_timeout_is_a_clean_error(home: Path, monkeypatch) -> None:
    """A handler timeout becomes a Click error without a traceback."""
    _seed_token()

    def fake_snipe(client, **kwargs):
        raise TimeoutError("Timed out after 5s without ordering an instance")

    monkeypatch.setattr(tools_commands.snipe_handler, "snipe", fake_snipe)

    result = CliRunner().invoke(
        main,
        ["tools", "snipe", "--gpu", "RTX 3090", "--image", "base-image-x"],
    )

    assert result.exit_code == 1
    assert "Timed out after 5s without ordering an instance" in result.output
    assert "Traceback" not in result.output


def test_snipe_unknown_region_is_a_clean_error(home: Path, monkeypatch) -> None:
    """A region resolution failure becomes a Click error without a traceback."""
    _seed_token()

    def fake_snipe(client, **kwargs):
        raise ValueError("Unknown region 'nowhere'. Known regions: 西北B区")

    monkeypatch.setattr(tools_commands.snipe_handler, "snipe", fake_snipe)

    result = CliRunner().invoke(
        main,
        ["tools", "snipe", "--region", "nowhere", "--image", "base-image-x"],
    )

    assert result.exit_code == 1
    assert "Unknown region 'nowhere'" in result.output
    assert "Traceback" not in result.output


def test_snipe_help_lists_its_options(home: Path) -> None:
    """``tools snipe --help`` exits cleanly and documents the options."""
    result = CliRunner().invoke(main, ["tools", "snipe", "--help"])

    assert result.exit_code == 0, result.output
    assert "--region" in result.output
    assert "--gpu" in result.output
    assert "--max-price" in result.output
    assert "--strategy" in result.output
