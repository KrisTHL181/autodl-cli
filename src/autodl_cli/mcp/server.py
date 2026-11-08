"""``autodl-mcp`` — stdio MCP server for the AutoDL CLI.

The implementation lives in :mod:`click2mcp`: it walks the Click tree, synthesizes
the typed tool schemas, encodes argv, and provides the ``--groups`` launcher and
the ``autodl_help`` / ``autodl_run`` escape hatches. This module only configures
it for autodl.

Commands run as subprocesses with ``stdin=/dev/null``, so ``autodl auth paste`` —
which reads credentials from stdin — is excluded from the typed tools and refused
by ``autodl_run``.
"""

from __future__ import annotations

import sys

# ── instructions ───────────────────────────────────────────────────────────

_INSTRUCTIONS = """\
Wraps the `autodl` CLI (AutoDL container-instance management) as one typed tool
per leaf command: `instance_list`, `account_balance`, and so on. MCP clients
namespace them with the server name, e.g. `mcp__autodl__instance_list`.

Prefer the typed tools. Every typed tool exposes the root `--json` switch as a
`json` argument — set it to `true` for parseable output instead of styled text.

Two escape hatches remain:
- `autodl_help(path)` prints the CLI's own `--help` for any command path.
- `autodl_run(args)` runs an arbitrary command line, for anything the typed tools
  do not cover. `autodl auth paste` is refused because it needs stdin.

How long a command may run is the client's decision, not this server's: a call
returns when the command finishes.
"""

# ── server ─────────────────────────────────────────────────────────────────

try:
    from click2mcp import ClickMCP

    from autodl_cli.mcp.generate import EXCLUDED_PATHS, _load_cli
except ImportError as _exc:  # only reachable without the optional ``[mcp]`` extra
    _MCP_IMPORT_ERROR: ImportError | None = _exc
    _bridge = None
    mcp = None
else:
    _MCP_IMPORT_ERROR = None

    _bridge = ClickMCP(
        app="autodl",
        cli=_load_cli,
        module="autodl_cli.main",
        instructions=_INSTRUCTIONS,
        exclude=EXCLUDED_PATHS,
        inherit_group_options=True,
        escape_hatches=True,
    )
    mcp = _bridge.server


def main() -> None:
    """Serve MCP over stdio, optionally restricted to selected command groups."""
    if _MCP_IMPORT_ERROR is not None:
        sys.exit("autodl-mcp needs the optional MCP dependency.\nInstall it with: pip install 'autodl-cli[mcp]'")
    _bridge.run()


if __name__ == "__main__":
    main()
