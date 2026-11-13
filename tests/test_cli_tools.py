"""Tests for ``autodl tools`` commands through the real Click entry point."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from autodl_cli import config as config_module
from autodl_cli.commands import tools as tools_commands
from autodl_cli.errors import AuthError, AutoDLError
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
    clone_event: bool = False,
    captured: dict[str, object] | None = None,
    result_override: dict[str, object] | None = None,
) -> None:
    """Replace the snipe handler so the command never touches the network.

    :param monkeypatch: pytest's monkeypatch fixture.
    :param events: Whether the fake should emit progress events.
    :param clone_event: Whether the emitted ``found`` event announces clone mode.
    :param captured: Optional mapping that receives the call arguments.
    :param result_override: Optional result mapping replacing ``SNIPE_RESULT``.
    """
    result = dict(SNIPE_RESULT if result_override is None else result_override)

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
            found_event: dict[str, object] = {"event": "found", "machine": machine}
            if clone_event:
                found_event["clone"] = True
            on_event(found_event)
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
                    "event": "ordered",
                    "instance_uuid": "snipe-extra",
                    "machine": machine,
                    "extra": True,
                }
            )
            on_event({"event": "releasing_extra", "instance_uuid": "snipe-extra", "machine": machine})
            on_event(
                {
                    "event": "extra_power_off_failed",
                    "instance_uuid": "snipe-extra",
                    "error": "power off refused",
                }
            )
            on_event({"event": "extra_released", "instance_uuid": "snipe-extra"})
            on_event(
                {
                    "event": "extra_release_failed",
                    "instance_uuid": "snipe-extra",
                    "error": "release denied",
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
    monkeypatch.setattr(tools_commands.output.console, "width", 200)
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
    assert "Ordered surplus instance snipe-extra on machine m-1; powering off and releasing it..." in result.output
    assert "Releasing surplus instance snipe-extra on machine m-1..." in result.output
    assert "Could not power off surplus instance snipe-extra: power off refused; releasing it anyway." in result.output
    assert "Released surplus instance snipe-extra." in result.output
    assert "Could not release surplus instance snipe-extra: release denied." in result.output
    assert "Instance status: not visible yet." in result.output
    assert "Instance status: creating." in result.output
    assert "Instance snipe-instance-1 is running." in result.output
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


def test_snipe_forwards_parallel_and_count_to_the_handler(home: Path, monkeypatch) -> None:
    """``--parallel`` and ``--count`` reach the handler unchanged."""
    _seed_token()
    captured: dict[str, object] = {}
    _patch_snipe(monkeypatch, captured=captured)

    result = CliRunner().invoke(
        main,
        [
            "tools",
            "snipe",
            "--gpu",
            "RTX 3090",
            "--image",
            "base-image-x",
            "--parallel",
            "3",
            "--count",
            "2",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["parallel"] == 3
    assert captured["count"] == 2


@pytest.mark.parametrize("args", [["--parallel", "0"], ["--count", "0"]])
def test_snipe_rejects_zero_parallel_or_count(home: Path, monkeypatch, args: list[str]) -> None:
    """Zero is a usage error before the handler runs."""
    _seed_token()
    monkeypatch.setattr(
        tools_commands.snipe_handler,
        "snipe",
        lambda *call_args, **call_kwargs: pytest.fail("the handler must not run with invalid counts"),
    )

    result = CliRunner().invoke(
        main,
        ["tools", "snipe", "--gpu", "RTX 3090", "--image", "base-image-x", *args],
    )

    assert result.exit_code == 2
    assert args[0] in result.output


def test_snipe_renders_multiple_kept_and_released_instances(home: Path, monkeypatch) -> None:
    """A multi-instance result prints one success line per kept instance and the release count."""
    _seed_token()
    monkeypatch.setattr(tools_commands.output.console, "width", 200)
    first = dict(SNIPE_RESULT)
    second = {**SNIPE_RESULT, "instance_uuid": "snipe-instance-2", "machine_id": "m-2"}
    released = {**SNIPE_RESULT, "instance_uuid": "snipe-instance-3", "status": "released"}
    result_override = {
        **SNIPE_RESULT,
        "instances": [first, second],
        "released_instances": [released],
        "release_failures": [],
        "count": 2,
        "parallel": 3,
    }
    _patch_snipe(monkeypatch, result_override=result_override)

    result = CliRunner().invoke(
        main,
        [
            "tools",
            "snipe",
            "--gpu",
            "RTX 3090",
            "--image",
            "base-image-x",
            "--count",
            "2",
            "--parallel",
            "3",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Instance snipe-instance-1 is running on machine m-1" in result.output
    assert "Instance snipe-instance-2 is running on machine m-2" in result.output
    assert result.output.count("autodl instance list -q") == 2
    assert "Released 1 surplus instance(s)." in result.output


def test_snipe_renders_release_failures(home: Path, monkeypatch) -> None:
    """Release failures are reported as warnings after the kept instances."""
    _seed_token()
    monkeypatch.setattr(tools_commands.output.console, "width", 200)
    result_override = {
        **SNIPE_RESULT,
        "instances": [dict(SNIPE_RESULT)],
        "released_instances": [],
        "release_failures": [{"instance_uuid": "snipe-extra", "error": "release denied"}],
    }
    _patch_snipe(monkeypatch, result_override=result_override)

    result = CliRunner().invoke(
        main,
        ["tools", "snipe", "--gpu", "RTX 3090", "--image", "base-image-x"],
    )

    assert result.exit_code == 0, result.output
    assert "Could not release surplus instance snipe-extra: release denied." in result.output


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
    assert "--parallel" in result.output
    assert "--count" in result.output
    assert "--notify" in result.output
    assert "--no-notify" in result.output
    assert "--notify-webhook" in result.output
    assert "--config" in result.output


def test_snipe_clone_forwards_its_options(home: Path, monkeypatch) -> None:
    """``--clone`` replaces the image UUIDs and forwards the clone defaults."""
    _seed_token()
    captured: dict[str, object] = {}
    _patch_snipe(monkeypatch, captured=captured)

    result = CliRunner().invoke(
        main,
        ["tools", "snipe", "--gpu", "RTX 3090", "--clone", "source-uuid"],
    )

    assert result.exit_code == 0, result.output
    assert captured["clone_instance_uuid"] == "source-uuid"
    assert captured["base_image_uuid"] == ""
    assert captured["private_image_uuid"] == ""
    assert captured["copy_data_disk"] is True
    assert captured["keep_src_user_service_address"] is False


def test_snipe_clone_forwards_copy_and_keep_flags(home: Path, monkeypatch) -> None:
    """``--no-copy-data-disk`` and ``--keep-service-address`` reach the handler."""
    _seed_token()
    captured: dict[str, object] = {}
    _patch_snipe(monkeypatch, captured=captured)

    result = CliRunner().invoke(
        main,
        [
            "tools",
            "snipe",
            "--gpu",
            "RTX 3090",
            "--clone",
            "source-uuid",
            "--no-copy-data-disk",
            "--keep-service-address",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["copy_data_disk"] is False
    assert captured["keep_src_user_service_address"] is True


def test_snipe_clone_json_passes_the_result_through(home: Path, monkeypatch) -> None:
    """``--json`` still emits only the handler result in clone mode."""
    _seed_token()
    _patch_snipe(monkeypatch)

    result = CliRunner().invoke(
        main,
        ["--json", "tools", "snipe", "--gpu", "RTX 3090", "--clone", "source-uuid"],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == SNIPE_RESULT


@pytest.mark.parametrize(
    "image_args",
    [
        ["--image", "base-image-x"],
        ["--private-image", "image-y"],
    ],
)
def test_snipe_clone_conflicts_with_image_flags(home: Path, monkeypatch, image_args: list[str]) -> None:
    """``--clone`` and either image flag are mutually exclusive."""
    _seed_token()
    monkeypatch.setattr(
        tools_commands.snipe_handler,
        "snipe",
        lambda *call_args, **call_kwargs: pytest.fail("the handler must not run with conflicting images"),
    )

    result = CliRunner().invoke(
        main,
        ["tools", "snipe", "--gpu", "RTX 3090", "--clone", "source-uuid", *image_args],
    )

    assert result.exit_code == 2
    assert "Use either --clone or --image/--private-image, not both." in result.output


@pytest.mark.parametrize("args", [["--no-copy-data-disk"], ["--keep-service-address"]])
def test_snipe_clone_only_flags_require_clone(home: Path, monkeypatch, args: list[str]) -> None:
    """Clone-only flags are rejected outside clone mode."""
    _seed_token()
    monkeypatch.setattr(
        tools_commands.snipe_handler,
        "snipe",
        lambda *call_args, **call_kwargs: pytest.fail("the handler must not run with clone-only flags"),
    )

    result = CliRunner().invoke(
        main,
        ["tools", "snipe", "--gpu", "RTX 3090", "--image", "base-image-x", *args],
    )

    assert result.exit_code == 2
    assert "--no-copy-data-disk and --keep-service-address require --clone." in result.output


def test_snipe_renders_clone_found_event(home: Path, monkeypatch) -> None:
    """A clone-mode ``found`` event says the machine is being cloned."""
    _seed_token()
    monkeypatch.setattr(tools_commands.output.console, "width", 200)
    _patch_snipe(monkeypatch, events=True, clone_event=True)

    result = CliRunner().invoke(
        main,
        ["tools", "snipe", "--gpu", "RTX 3090", "--clone", "source-uuid"],
    )

    assert result.exit_code == 0, result.output
    assert "Found RTX 3090 on machine m-1 (西北B区); cloning..." in result.output


class _RecordingNotifier:
    """Stand-in for :class:`autodl_cli.utils.notify.Notifier` that records sends."""

    instances: list[_RecordingNotifier] = []
    warnings: tuple[str, ...] = ()

    def __init__(self, *, desktop: bool = False, webhooks=()) -> None:
        """Store the channel configuration.

        :param desktop: Whether desktop notifications are enabled.
        :param webhooks: Configured webhook URLs.
        """
        self.desktop = desktop
        self.webhooks = tuple(webhooks)
        self.sent: list[tuple[str, str, str, dict[str, object]]] = []
        type(self).instances.append(self)

    @property
    def enabled(self) -> bool:
        """Return whether a channel is configured.

        :returns: ``True`` when desktop notifications or a webhook are enabled.
        """
        return self.desktop or bool(self.webhooks)

    def send(self, event: str, title: str, body: str, **fields: object) -> list[str]:
        """Record one notification and return configured warnings.

        :param event: Event name.
        :param title: Notification title.
        :param body: Notification body.
        :param fields: Extra webhook data.
        :returns: Warnings configured through the ``warnings`` attribute.
        """
        self.sent.append((event, title, body, fields))
        return list(type(self).warnings)


def _patch_notifier(monkeypatch) -> type[_RecordingNotifier]:
    """Replace the command's ``Notifier`` with a recording stand-in.

    :param monkeypatch: pytest's monkeypatch fixture.
    :returns: The recording class; its ``instances`` list receives each notifier.
    """
    monkeypatch.setattr(tools_commands, "Notifier", _RecordingNotifier)
    monkeypatch.setattr(_RecordingNotifier, "instances", [])
    monkeypatch.setattr(_RecordingNotifier, "warnings", ())
    return _RecordingNotifier


def _write_snipe_config(tmp_path: Path, text: str) -> Path:
    """Write a snipe TOML template.

    :param tmp_path: Directory that receives the file.
    :param text: TOML source.
    :returns: The written path.
    """
    path = tmp_path / "snipe.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_snipe_config_supplies_defaults(home: Path, monkeypatch, tmp_path: Path) -> None:
    """A template supplies every option and enables notifications."""
    _seed_token()
    captured: dict[str, object] = {}
    _patch_snipe(monkeypatch, captured=captured)
    recorder = _patch_notifier(monkeypatch)
    config = _write_snipe_config(
        tmp_path,
        """
region = ["nm-B2"]
gpu = ["RTX 4090"]
gpu_num = 2
max_price = 1.8
strategy = "idle"
parallel = 2
count = 1
image = "base-image-x"
name = "trainer"
data_disk = 50
interval = 5
timeout = 600
retry = 3
copy_data_disk = true
notify = true
notify_webhook = ["https://example.test/hook"]
""",
    )

    result = CliRunner().invoke(main, ["tools", "snipe", "--config", str(config)])

    assert result.exit_code == 0, result.output
    assert captured["regions"] == ("nm-B2",)
    assert captured["gpu_types"] == ("RTX 4090",)
    assert captured["gpu_amount"] == 2
    assert captured["max_price"] == 1.8
    assert captured["strategy"] == "idle"
    assert captured["parallel"] == 2
    assert captured["count"] == 1
    assert captured["base_image_uuid"] == "base-image-x"
    assert captured["instance_name"] == "trainer"
    assert captured["expand_data_disk"] == 50
    assert captured["interval"] == 5
    assert captured["timeout"] == 600
    assert captured["retry"] == 3
    assert captured["copy_data_disk"] is True

    notifier = recorder.instances[0]
    assert notifier.desktop is True
    assert notifier.webhooks == ("https://example.test/hook",)


def test_snipe_cli_options_override_config(home: Path, monkeypatch, tmp_path: Path) -> None:
    """Values supplied on the command line win over the template."""
    _seed_token()
    captured: dict[str, object] = {}
    _patch_snipe(monkeypatch, captured=captured)
    recorder = _patch_notifier(monkeypatch)
    config = _write_snipe_config(
        tmp_path,
        """
region = "nm-B2"
gpu = "RTX 4090"
gpu_num = 2
strategy = "first"
image = "base-image-config"
notify = true
""",
    )

    result = CliRunner().invoke(
        main,
        [
            "tools",
            "snipe",
            "--config",
            str(config),
            "--gpu-num",
            "4",
            "--strategy",
            "price",
            "--image",
            "base-image-cli",
            "--no-notify",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["gpu_types"] == ("RTX 4090",)
    assert captured["gpu_amount"] == 4
    assert captured["strategy"] == "price"
    assert captured["base_image_uuid"] == "base-image-cli"

    notifier = recorder.instances[0]
    assert notifier.desktop is False
    assert notifier.webhooks == ()
    assert notifier.enabled is False


def test_snipe_config_accepts_a_string_for_repeatable_options(home: Path, monkeypatch, tmp_path: Path) -> None:
    """A scalar string is accepted for a repeatable option."""
    _seed_token()
    captured: dict[str, object] = {}
    _patch_snipe(monkeypatch, captured=captured)
    recorder = _patch_notifier(monkeypatch)
    config = _write_snipe_config(
        tmp_path,
        """
region = "nm-B2"
gpu = "RTX 4090"
image = "base-image-x"
notify_webhook = "https://example.test/hook"
""",
    )

    result = CliRunner().invoke(main, ["tools", "snipe", "--config", str(config)])

    assert result.exit_code == 0, result.output
    assert captured["regions"] == ("nm-B2",)
    assert captured["gpu_types"] == ("RTX 4090",)
    assert recorder.instances[0].webhooks == ("https://example.test/hook",)


def test_snipe_config_accepts_dashed_keys(home: Path, monkeypatch, tmp_path: Path) -> None:
    """Dashes in config keys are normalised to underscores."""
    _seed_token()
    captured: dict[str, object] = {}
    _patch_snipe(monkeypatch, captured=captured)
    config = _write_snipe_config(
        tmp_path,
        """
gpu = "RTX 4090"
gpu-num = 2
max-price = 1.5
private-image = "image-y"
copy-data-disk = true
""",
    )

    result = CliRunner().invoke(main, ["tools", "snipe", "--config", str(config)])

    assert result.exit_code == 0, result.output
    assert captured["gpu_amount"] == 2
    assert captured["max_price"] == 1.5
    assert captured["private_image_uuid"] == "image-y"
    assert captured["copy_data_disk"] is True


@pytest.mark.parametrize(
    ("body", "needle"),
    [
        ('region = "x"\ngpu = "g"\nimage = "i"\nbogus = 1\n', "bogus"),
        ('region = "x"\ngpu = "g"\nimage = "i"\ngpu_num = "two"\n', "gpu_num"),
        ('region = "x"\ngpu = "g"\nimage = "i"\ngpu_num = [1, 2]\n', "gpu_num"),
        ('region = "x"\ngpu = "g"\nimage = "i"\nstrategy = "fast"\n', "strategy"),
    ],
)
def test_snipe_rejects_invalid_config(
    home: Path,
    monkeypatch,
    tmp_path: Path,
    body: str,
    needle: str,
) -> None:
    """Unknown keys, bad types, arrays for scalar options, and bad choices fail."""
    _seed_token()
    monkeypatch.setattr(
        tools_commands.snipe_handler,
        "snipe",
        lambda *args, **kwargs: pytest.fail("an invalid template must not reach the handler"),
    )
    config = _write_snipe_config(tmp_path, body)

    result = CliRunner().invoke(main, ["tools", "snipe", "--config", str(config)])

    assert result.exit_code == 2
    assert needle in result.output
    assert "--config" in result.output


@pytest.mark.parametrize(
    ("body", "needle"),
    [
        ("gpu_num = true", "gpu_num"),
        ("gpu_num = 2.5", "gpu_num"),
        ('interval = "fast"', "interval"),
        ('notify = "yes"', "notify"),
        ("name = 123", "name"),
        ("region = 1", "region"),
        ("region = [1]", "region"),
        ("notify_webhook = [1]", "notify_webhook"),
    ],
)
def test_snipe_config_rejects_values_of_the_wrong_python_type(
    home: Path,
    monkeypatch,
    tmp_path: Path,
    body: str,
    needle: str,
) -> None:
    """TOML values must already have the option's declared Python type."""
    _seed_token()
    monkeypatch.setattr(
        tools_commands.snipe_handler,
        "snipe",
        lambda *args, **kwargs: pytest.fail("an invalid template must not reach the handler"),
    )
    config = _write_snipe_config(tmp_path, f'gpu = "RTX 4090"\nimage = "base-image-x"\n{body}\n')

    result = CliRunner().invoke(main, ["tools", "snipe", "--config", str(config)])

    assert result.exit_code == 2
    assert needle in result.output
    assert "--config" in result.output


def test_snipe_config_clone_conflict_is_a_usage_error(home: Path, monkeypatch, tmp_path: Path) -> None:
    """The existing clone/image exclusivity check runs after config merging."""
    _seed_token()
    monkeypatch.setattr(
        tools_commands.snipe_handler,
        "snipe",
        lambda *args, **kwargs: pytest.fail("the handler must not run with conflicting images"),
    )
    config = _write_snipe_config(
        tmp_path,
        """
gpu = "RTX 4090"
clone = "source-uuid"
image = "base-image-x"
""",
    )

    result = CliRunner().invoke(main, ["tools", "snipe", "--config", str(config)])

    assert result.exit_code == 2
    assert "Use either --clone or --image/--private-image, not both." in result.output


def test_snipe_cli_private_image_replaces_config_image(home: Path, monkeypatch, tmp_path: Path) -> None:
    """An explicit CLI image choice drops the template's conflicting image."""
    _seed_token()
    captured: dict[str, object] = {}
    _patch_snipe(monkeypatch, captured=captured)
    config = _write_snipe_config(
        tmp_path,
        """
gpu = "RTX 4090"
image = "base-image-config"
""",
    )

    result = CliRunner().invoke(
        main,
        ["tools", "snipe", "--config", str(config), "--private-image", "image-x"],
    )

    assert result.exit_code == 0, result.output
    assert captured["private_image_uuid"] == "image-x"
    assert captured["base_image_uuid"] == ""


def test_snipe_cli_clone_replaces_config_image(home: Path, monkeypatch, tmp_path: Path) -> None:
    """An explicit ``--clone`` drops the template's conflicting image."""
    _seed_token()
    captured: dict[str, object] = {}
    _patch_snipe(monkeypatch, captured=captured)
    config = _write_snipe_config(
        tmp_path,
        """
gpu = "RTX 4090"
image = "base-image-config"
""",
    )

    result = CliRunner().invoke(
        main,
        ["tools", "snipe", "--config", str(config), "--clone", "instance-1"],
    )

    assert result.exit_code == 0, result.output
    assert captured["clone_instance_uuid"] == "instance-1"
    assert captured["base_image_uuid"] == ""
    assert captured["private_image_uuid"] == ""


def test_snipe_webhook_alone_enables_notifications(home: Path, monkeypatch) -> None:
    """A webhook on its own turns notifications on, including the desktop."""
    _seed_token()
    _patch_snipe(monkeypatch)
    recorder = _patch_notifier(monkeypatch)

    result = CliRunner().invoke(
        main,
        [
            "tools",
            "snipe",
            "--gpu",
            "RTX 3090",
            "--image",
            "base-image-x",
            "--notify-webhook",
            "https://example.test/hook",
        ],
    )

    assert result.exit_code == 0, result.output
    notifier = recorder.instances[0]
    assert notifier.desktop is True
    assert notifier.webhooks == ("https://example.test/hook",)


def test_snipe_cli_webhook_overrides_config_notify_false(home: Path, monkeypatch, tmp_path: Path) -> None:
    """An explicit ``--notify-webhook`` wins over ``notify = false`` in the template."""
    _seed_token()
    _patch_snipe(monkeypatch)
    recorder = _patch_notifier(monkeypatch)
    config = _write_snipe_config(
        tmp_path,
        """
gpu = "RTX 4090"
image = "base-image-x"
notify = false
""",
    )

    result = CliRunner().invoke(
        main,
        ["tools", "snipe", "--config", str(config), "--notify-webhook", "https://example.test/hook"],
    )

    assert result.exit_code == 0, result.output
    notifier = recorder.instances[0]
    assert notifier.enabled is True
    assert notifier.desktop is True
    assert notifier.webhooks == ("https://example.test/hook",)


def test_snipe_no_notify_wins_over_config_notify_false_and_webhook(home: Path, monkeypatch, tmp_path: Path) -> None:
    """An explicit ``--no-notify`` wins over a template and a CLI webhook."""
    _seed_token()
    _patch_snipe(monkeypatch)
    recorder = _patch_notifier(monkeypatch)
    config = _write_snipe_config(
        tmp_path,
        """
gpu = "RTX 4090"
image = "base-image-x"
notify = false
""",
    )

    result = CliRunner().invoke(
        main,
        [
            "tools",
            "snipe",
            "--config",
            str(config),
            "--notify-webhook",
            "https://example.test/hook",
            "--no-notify",
        ],
    )

    assert result.exit_code == 0, result.output
    notifier = recorder.instances[0]
    assert notifier.enabled is False
    assert notifier.webhooks == ()


def test_snipe_no_notify_disables_a_webhook(home: Path, monkeypatch) -> None:
    """``--no-notify`` wins over an explicit webhook."""
    _seed_token()
    _patch_snipe(monkeypatch)
    recorder = _patch_notifier(monkeypatch)

    result = CliRunner().invoke(
        main,
        [
            "tools",
            "snipe",
            "--gpu",
            "RTX 3090",
            "--image",
            "base-image-x",
            "--notify-webhook",
            "https://example.test/hook",
            "--no-notify",
        ],
    )

    assert result.exit_code == 0, result.output
    notifier = recorder.instances[0]
    assert notifier.enabled is False
    assert notifier.webhooks == ()


def test_snipe_rejects_invalid_webhook_url_without_echoing_it(home: Path, monkeypatch) -> None:
    """A non-HTTP webhook URL is a usage error that does not repeat the value."""
    _seed_token()
    monkeypatch.setattr(
        tools_commands.snipe_handler,
        "snipe",
        lambda *args, **kwargs: pytest.fail("an invalid webhook must not reach the handler"),
    )

    result = CliRunner().invoke(
        main,
        [
            "tools",
            "snipe",
            "--gpu",
            "RTX 3090",
            "--image",
            "base-image-x",
            "--notify-webhook",
            "ftp://example.test/secret",
        ],
    )

    assert result.exit_code == 2
    assert "absolute http" in result.output
    assert "ftp://" not in result.output


def test_snipe_rejects_invalid_webhook_url_from_config(home: Path, monkeypatch, tmp_path: Path) -> None:
    """Webhook URLs from a template are validated the same way."""
    _seed_token()
    monkeypatch.setattr(
        tools_commands.snipe_handler,
        "snipe",
        lambda *args, **kwargs: pytest.fail("an invalid webhook must not reach the handler"),
    )
    config = _write_snipe_config(
        tmp_path,
        """
gpu = "RTX 4090"
image = "base-image-x"
notify_webhook = "not-a-url"
""",
    )

    result = CliRunner().invoke(main, ["tools", "snipe", "--config", str(config)])

    assert result.exit_code == 2
    assert "absolute http" in result.output
    assert "not-a-url" not in result.output


def test_snipe_notifies_for_ordered_and_running_events(home: Path, monkeypatch) -> None:
    """Kept orders and running instances notify; surplus orders do not."""
    _seed_token()
    monkeypatch.setattr(tools_commands.output.console, "width", 200)
    _patch_snipe(monkeypatch, events=True)
    recorder = _patch_notifier(monkeypatch)

    result = CliRunner().invoke(
        main,
        [
            "tools",
            "snipe",
            "--gpu",
            "RTX 3090",
            "--image",
            "base-image-x",
            "--notify-webhook",
            "https://example.test/hook",
        ],
    )

    assert result.exit_code == 0, result.output
    sent = recorder.instances[0].sent
    assert [item[0] for item in sent] == ["snipe.ordered", "snipe.running"]

    event, title, body, fields = sent[0]
    assert event == "snipe.ordered"
    assert title == "GPU ordered"
    assert body == "Instance snipe-instance-1 ordered on machine m-1 in 西北B区 (RTX 3090)"
    assert fields == {
        "instance_uuid": "snipe-instance-1",
        "machine_id": "m-1",
        "region_name": "西北B区",
        "gpu_name": "RTX 3090",
        "gpu_num": 1,
    }

    event, title, body, _fields = sent[1]
    assert event == "snipe.running"
    assert title == "Instance running"
    assert body == "Instance snipe-instance-1 is running on machine m-1 in 西北B区"
    assert all(item[3].get("instance_uuid") != "snipe-extra" for item in sent)


def test_snipe_notifications_deduplicate_by_instance_uuid(home: Path, monkeypatch) -> None:
    """Repeated ordered/running events for one instance notify once each."""
    _seed_token()
    _patch_notifier(monkeypatch)
    machine = {"machine_id": "m-1", "gpu_name": "RTX 3090", "region_name": "西北B区"}

    def fake_snipe(client, **kwargs):
        on_event = kwargs["on_event"]
        ordered = {"event": "ordered", "instance_uuid": "snipe-instance-1", "machine": machine}
        running = {"event": "running", "instance_uuid": "snipe-instance-1"}
        on_event(ordered)
        on_event(ordered)
        on_event(running)
        on_event(running)
        return dict(SNIPE_RESULT)

    monkeypatch.setattr(tools_commands.snipe_handler, "snipe", fake_snipe)
    recorder = _patch_notifier(monkeypatch)

    result = CliRunner().invoke(
        main,
        [
            "tools",
            "snipe",
            "--gpu",
            "RTX 3090",
            "--image",
            "base-image-x",
            "--notify-webhook",
            "https://example.test/hook",
        ],
    )

    assert result.exit_code == 0, result.output
    assert [item[0] for item in recorder.instances[0].sent] == ["snipe.ordered", "snipe.running"]


def test_snipe_json_still_notifies_and_stays_pure(home: Path, monkeypatch) -> None:
    """``--json`` suppresses rendering but not notifications or JSON purity."""
    _seed_token()
    _patch_snipe(monkeypatch, events=True)
    recorder = _patch_notifier(monkeypatch)

    result = CliRunner().invoke(
        main,
        [
            "--json",
            "tools",
            "snipe",
            "--gpu",
            "RTX 3090",
            "--image",
            "base-image-x",
            "--notify-webhook",
            "https://example.test/hook",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == SNIPE_RESULT
    assert [item[0] for item in recorder.instances[0].sent] == ["snipe.ordered", "snipe.running"]


def test_snipe_notification_warnings_use_warning_in_human_mode(home: Path, monkeypatch) -> None:
    """Delivery failures are warnings on stdout-like output in human mode."""
    _seed_token()
    _patch_snipe(monkeypatch, events=True)
    recorder = _patch_notifier(monkeypatch)
    recorder.warnings = ("Delivery failed.",)

    result = CliRunner().invoke(
        main,
        [
            "tools",
            "snipe",
            "--gpu",
            "RTX 3090",
            "--image",
            "base-image-x",
            "--notify",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Delivery failed." in result.output


def test_snipe_notification_warnings_use_stderr_in_json_mode(home: Path, monkeypatch) -> None:
    """``--json`` keeps warnings off stdout so the document stays parseable."""
    _seed_token()
    _patch_snipe(monkeypatch, events=True)
    recorder = _patch_notifier(monkeypatch)
    recorder.warnings = ("Delivery failed.",)

    result = CliRunner().invoke(
        main,
        [
            "--json",
            "tools",
            "snipe",
            "--gpu",
            "RTX 3090",
            "--image",
            "base-image-x",
            "--notify",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == SNIPE_RESULT
    assert "Delivery failed." not in result.stdout
    assert "Delivery failed." in result.stderr


@pytest.mark.parametrize(
    "error",
    [TimeoutError("timed out"), AutoDLError("api failed"), AuthError("token rejected")],
    ids=["timeout", "api-error", "auth-error"],
)
def test_snipe_failure_notifies_before_exiting(home: Path, monkeypatch, error: Exception) -> None:
    """Timeouts and AutoDL errors send ``snipe.failed`` and still exit cleanly."""
    _seed_token()
    recorder = _patch_notifier(monkeypatch)

    def fake_snipe(client, **kwargs):
        raise error

    monkeypatch.setattr(tools_commands.snipe_handler, "snipe", fake_snipe)

    result = CliRunner().invoke(
        main,
        [
            "tools",
            "snipe",
            "--gpu",
            "RTX 3090",
            "--image",
            "base-image-x",
            "--notify-webhook",
            "https://example.test/hook",
        ],
    )

    assert result.exit_code == 1
    assert str(error) in result.output
    assert "Traceback" not in result.output
    sent = recorder.instances[0].sent
    assert [item[0] for item in sent] == ["snipe.failed"]
    assert sent[0][2] == str(error)
    assert sent[0][3]["error_type"] == type(error).__name__


def test_snipe_value_error_does_not_notify(home: Path, monkeypatch) -> None:
    """A ValueError is a parameter error and never sends a notification."""
    _seed_token()
    recorder = _patch_notifier(monkeypatch)

    def fake_snipe(client, **kwargs):
        raise ValueError("Unknown region 'nowhere'")

    monkeypatch.setattr(tools_commands.snipe_handler, "snipe", fake_snipe)

    result = CliRunner().invoke(
        main,
        [
            "tools",
            "snipe",
            "--gpu",
            "RTX 3090",
            "--image",
            "base-image-x",
            "--notify-webhook",
            "https://example.test/hook",
        ],
    )

    assert result.exit_code == 1
    assert "Unknown region 'nowhere'" in result.output
    assert recorder.instances[0].sent == []
