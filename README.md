<div align="center">

# ⚡ autodl-cli

**Your AutoDL GPU cloud, one command away.**

*A typed CLI, a public Python API, and an optional MCP server for AutoDL's web API.*

```
account · gpu · image · instance · nfs · tools — all from the command line.
```

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![GitHub Repo stars](https://img.shields.io/github/stars/KrisTHL181/autodl-cli?style=flat)](https://github.com/KrisTHL181/autodl-cli/stargazers)

</div>

---

**autodl-cli** puts AutoDL's GPU cloud in your shell. Authenticate once, then check
your balance, hunt for idle GPUs across regions, drill into machine-level capacity,
browse the base-image catalogue and your saved images, and read every instance
on your account — without clicking through the web console.

> ⚠️ This is an **unofficial** tool, not affiliated with AutoDL. It does **not**
> use a public developer API — it reverse-engineers the private endpoints behind
> the AutoDL web console. Those endpoints can change, rate-limit, or stop working
> at any time, so use this at your own risk.

---

## 🚀 Quick Start

> **Requirement:** Python 3.10 or newer. Check with `python --version` before installing.

```bash
pip install autodl-cli
```

Installing from source instead:

```bash
git clone https://github.com/KrisTHL181/autodl-cli.git
cd autodl-cli
pip install -e .
```

### 1. Authenticate

Credentials land in `~/.autodl-cli/profiles/<name>.toml` (mode `0600`); the
device fingerprint and global settings live in `~/.autodl-cli/config.toml`.
Only the API token and the device fingerprint are stored — never a password.

```bash
# Paste a cURL command, an `Authorization:` line, a JSON blob, or a HAR file
# copied from the AutoDL console (DevTools → Network).
autodl auth paste

# Or log in with a phone number and password.
autodl auth login --phone 13800138000

# Non-interactive login.
AUTODL_PASSWORD=... autodl auth login --phone 13800138000
```

`auth login` needs a **device fingerprint** captured from the browser, because
AutoDL ties its captcha counter to that value and the CLI refuses to invent one.
Run `autodl auth paste` on the portal's login request first; it saves the
fingerprint even when the request carries no token yet.

### 2. Verify

```bash
autodl account me          # who am I?
autodl account balance     # how much credit is left?
```

---

## 👥 Profiles

Profiles are local credential sets, so one machine can switch AutoDL accounts
without pasting a token again. `auth login` and `auth paste` store credentials
in the effective profile and make it active.

```bash
autodl profile list          # every profile, the active one, and whether it has a token
autodl profile current       # effective profile and where the selection came from
autodl profile switch work   # activate an existing profile
autodl profile delete work   # delete it (asks first; --yes in scripts)
```

Select a profile per command with the global `--profile` flag, or through the
`AUTODL_PROFILE` environment variable. The precedence is:
`--profile` > `AUTODL_PROFILE` > `active_profile` file > `default`.

```bash
autodl --profile work account me
AUTODL_PROFILE=work autodl account balance
autodl --profile work --json instance list
```

Global settings such as the device fingerprint, base URL, timeout, and
`AppVersion` are shared by every profile; only the token and phone area are
per-profile. If an older install still has `token` or `phone_area` in
`config.toml`, the CLI moves them to `profiles/default.toml` and records
`default` as active the first time it runs.

```bash
# Create a second profile without losing the first.
autodl --profile work auth paste
autodl profile list
```

---

## ✨ What You Can Do

### 👤 Account

Inspect the authenticated profile, wallet, and billing usage. The tables and
`--json` report money values in yuan, using the API's field names (for example
`assets` and `payg_price`). `account usage` breaks spend down by month or day
and can filter by sub-user.

```bash
autodl account me
autodl account balance
autodl account balance --charge-type payg
autodl account usage
autodl account usage --granularity daily
autodl account usage --sub-name alice
autodl account usage --exclude-sub-user
```

### 🎮 GPU Capacity

See what is actually free before ordering. `gpu list` shows per-region GPU
availability and can print the region catalogue when no region is given.
`gpu find` searches a model name across every region. `gpu machines` goes one
level deeper: individual machines with idle cards, filtered by region, GPU model,
chip vendor, CPU architecture, billing mode, machine tag, network-disk support,
and availability dates — then sorted by price, idle count, or disk size.

```bash
autodl gpu list                       # every region and its stock
autodl gpu list -r shanghai -a        # idle GPUs only in one region
autodl gpu find 4090 -a               # search a model across all regions
autodl gpu machines --idle 4 --gpu "RTX 4090" --sort price
autodl gpu machines --charge-type monthly --mount-net-disk --all
```

`tools snipe` keeps checking pay-as-you-go stock and orders the first matching
machine, then waits until the instance reports `running`. Pass at least one
targeting filter, `--region` or `--gpu`; `--max-price` and `--gpu-num` only
narrow the search. `--strategy` chooses the cheapest (`price`, the default),
the most idle cards (`idle`), or the first result returned (`first`), and
exactly one of `--image` and `--private-image` is required.

`--clone INSTANCE_UUID` replaces the image flags: the clone inherits the source
instance's image, but not its GPU count, so `--gpu-num` still defaults to 1 and
keeps narrowing the search. Targeting still uses `--region` or `--gpu`. Clones
copy the source's data disk by default; pass `--no-copy-data-disk` to skip that.
The source's user service address is not kept unless `--keep-service-address`
is given.

`--parallel N` tries up to N ranked machines per poll instead of one. Because
listings can be stale by the time an order is placed, several attempts may
succeed; `--count N` keeps the N best-ranked successes (default 1). Any surplus
orders are powered off and released immediately, before waiting for the kept
instances to start, and cleanup is never cut short by `--timeout`. The
single-instance default (`--parallel 1 --count 1`) behaves as before.

```bash
autodl tools snipe --region nm-B2 --gpu "RTX 3090" --max-price 1.5 --image base-image-ee43618uo7
autodl tools snipe --gpu "RTX 4090" --gpu-num 2 --private-image image-abcd1234 --interval 5 --timeout 600
autodl tools snipe --gpu "RTX 4090" --image base-image-ee43618uo7 --parallel 3
autodl tools snipe --gpu "RTX 4090" --image base-image-ee43618uo7 --count 2 --parallel 3
autodl tools snipe --region nm-B2 --gpu "RTX 4090" --clone instance-1234abcd
autodl tools snipe --gpu "RTX 4090" --clone instance-1234abcd --no-copy-data-disk --keep-service-address
```

Transient API errors during polling (rate limits or 5xx responses) can be
retried with `--retry N`: up to N consecutive failures are tolerated per poll
and the counter resets after a successful check. Authentication errors are
never retried, and `--retry 0` (the default) disables retries. Order failures
retry indefinitely, but the rejected machine is skipped for a cooldown that
starts at `--interval` and doubles with each consecutive failure on that machine
(capped at eight intervals), so the next matching machine is tried instead.

```bash
autodl tools snipe --gpu "RTX 4090" --image base-image-ee43618uo7 --retry 3 --interval 5
```

`--notify` sends a desktop notification and POSTs a JSON event to every
`--notify-webhook URL` when an instance is ordered, when it starts running, and
when the command fails. Desktop notifications use the optional
`desktop-notifier` package on Linux, macOS, and Windows; install it with
`pip install "autodl-cli[notify]"`. If the extra is missing, the command warns
once and keeps going. Passing `--notify-webhook` alone enables notifications,
while `--no-notify` disables both channels and overrides a config template. Each webhook body contains
`source`, `event` (`snipe.ordered`, `snipe.running`, or `snipe.failed`),
`title`, `body`, `text`, an ISO-8601 UTC `timestamp`, and a `data` object with
the instance UUID, machine, region, GPU name and count, or error type when
known. Delivery failures are reported as warnings and never stop the snipe.

`--config PATH` loads defaults from a flat TOML template. Keys mirror the long
option names (`gpu-num` and `gpu_num` are equivalent), repeatable options accept
either a string or an array, and values are validated against the same types as
the command line. Explicit command-line options always win. Unknown keys and
invalid values are rejected instead of silently ignored.

```toml
region = ["nm-B2"]
gpu = ["RTX 4090"]
gpu_num = 2
max_price = 1.8
strategy = "price"
parallel = 3
count = 1
image = "base-image-ee43618uo7"
name = "trainer"
data_disk = 50
interval = 5
timeout = 600
retry = 3
notify = true
notify_webhook = ["https://api.day.app/<key>"]
```

```bash
autodl tools snipe --config snipe.toml
autodl --json tools snipe --config snipe.toml --notify-webhook https://example.test/hook
```

### 🖼️ Base Images

The create page's image picker is a four-level tree: framework, framework
version, Python/OS, and CUDA. `image list` flattens it into one row per
selectable image and shows the base-image UUID used when ordering. Filters are
case-insensitive substring matches, so `--cuda 12` catches every 12.x toolkit.

```bash
autodl image list
autodl image list -f pytorch --cuda 12
autodl image list --python 3.12 --chip nvidia
autodl --json image list --chip mthreads | jq -r '.[].image_uuid'
```

`image list-private` shows the images saved from your own instances, with the
numeric ID, save status and progress, size, framework, creation time, and UUID.
Every page is fetched, so the listing is complete regardless of AutoDL's page
size.

```bash
autodl image list-private
autodl image list-private --page-size 20
autodl --json image list-private | jq -r '.[] | [.id, .name, .status] | @tsv'
```

Deletion uses that numeric ID and is irreversible, so the command asks for
confirmation; pass `--yes` in scripts.

```bash
autodl image delete-private 842525
autodl image delete-private 842525 --yes
```

### 🖥️ Instances

List every instance on the account and drill into any of them. The list marks how
many GPU cards are still free on each instance's machine, flags instances that
fell back to CPU mode, and shows any scheduled shutdown next to the release
deadline. Filters run server-side where the API supports them, and `-q` matches
UUID, name, region, machine alias, or GPU name locally.

```bash
autodl instance list
autodl instance list --status running -q 4090
autodl instance list --unbind-sub-user
autodl instance detail <instance-uuid>
autodl instance wait <instance-uuid>
autodl instance wait <instance-uuid> --until shutdown --timeout 600
autodl instance power-on <instance-uuid>
autodl instance power-on <instance-uuid> --non-gpu
autodl instance power-on <instance-uuid> --wait
autodl instance power-off <instance-uuid>
autodl instance schedule-shutdown <instance-uuid> --at "2026-11-13 00:00"
autodl instance schedule-shutdown <instance-uuid> --in 4h
autodl instance cancel-shutdown <instance-uuid>
autodl instance reset <instance-uuid>
autodl instance reset <instance-uuid> --yes
autodl instance change-image <instance-uuid> base-image-ec1e9vdbd3
autodl instance change-image <instance-uuid> base-image-ec1e9vdbd3 --yes
autodl instance rename <instance-uuid> trainer-2
autodl instance release <instance-uuid>
autodl instance release <instance-uuid> --yes
autodl instance save-image <instance-uuid> my-image
autodl instance save-image <instance-uuid> my-image --try-again
autodl instance save-image <instance-uuid> my-image --wait
autodl instance create --machine-id 1c0641804d --image base-image-ee43618uo7
autodl instance create --machine-id 1c0641804d --image base-image-ee43618uo7 --wait
autodl instance create --region nm-B2 --gpu "RTX 3090" --image base-image-ee43618uo7
autodl instance create --machine-id 1c0641804d --private-image image-abcd1234 \
  --gpu-num 2 --name trainer --data-disk 50
autodl instance clone <instance-uuid> --machine-id 1c0641804d
autodl instance clone <instance-uuid> --machine-id 1c0641804d --wait
autodl instance clone <instance-uuid> --region nm-B2 --gpu "RTX 3090"
autodl instance clone <instance-uuid> --machine-id 1c0641804d --gpu-num 2 \
  --name clone --data-disk 50 --no-copy-data-disk
```

`power-on` posts to `/api/v1/instance/power_on`; AutoDL accepts the request
immediately, and the instance may take a moment to show as running. Pass
`--non-gpu` to start it in CPU-only mode, which boots without its GPU cards and
shows as `CPU` in `instance list`. `power-off`
posts to `/api/v1/instance/power_off` and keeps the data disk; AutoDL releases
a powered-off instance after the retention window shown by `instance list`
unless it is powered on again. `reset` posts to `/api/v1/instance/init` and
rebuilds the system disk from the instance's image while keeping the data disk;
it asks for confirmation unless `--yes` is passed. `change-image` posts to
`/api/v1/instance/change_image` and rebuilds the system disk from the given
base image while keeping the data disk; like `reset`, it asks for confirmation
unless `--yes` is passed. `rename` sends a PUT to `/api/v1/instance/name` and
sets the instance name; it does not prompt for confirmation. `release` posts to
`/api/v1/instance/release` and deletes the instance and its data disk
immediately; it is irreversible, so the command asks for confirmation unless
`--yes` is passed. `save-image` posts to
`/api/v1/instance/image/save`; AutoDL accepts the request immediately, and the
image appears under the account's private images once the save finishes.

`instance wait` polls the instance list until the instance reaches `--until
running` (the default), `shutdown`, or `released`. `released` also succeeds when
the instance has disappeared from the list. `running` also accepts the CPU-only
`cpu` start mode used by `power-on --non-gpu`, because that instance is ready to
use even though it has no GPU cards. `--interval` sets the seconds
between checks (default 10), `--timeout` gives up after that many seconds
(default 0, meaning no deadline, so it waits until interrupted), and `--retry`
retries that many consecutive transient API errors (default 0). `power-on`,
`create`, `clone`, and `save-image` accept the same tuning options behind a
`--wait` switch: after their usual output they wait for the instance to report
`running`, or for the image save to report `finished`. `--interval`, `--timeout`,
and `--retry` are rejected unless `--wait` is also passed. `save-image --wait`
snapshots the private images matching the instance and image name before sending
the save request, so `--try-again` ignores the older finished or failed entry
and waits for the new save.

`schedule-shutdown` posts to `/api/v1/instance/timed/shutdown` to power the
instance off automatically later. Pass exactly one of `--at` (an absolute time
such as `"2026-11-13 00:00"`) and `--in` (a duration such as `30m`, `4h`, or
`1d2h`). Times are Beijing time (UTC+8); a naive `--at` value is read as UTC+8,
while an explicit offset such as `+08:00` or `Z` is converted to it. A time in
the past is rejected. Re-run the command with a new `--at` or `--in` to change
the scheduled time. `cancel-shutdown` clears the schedule. `instance list`
shows a pending stop as `Stop YYYY-MM-DD`.

`create` posts to `/api/v1/order/instance/create/payg` and orders a
pay-as-you-go instance. Pass either `--machine-id` or both `--region` and
`--gpu`; with the latter the first machine in that region with enough idle
cards of the requested model is ordered on. Use `--image` for a base image or
`--private-image` for an image saved from an instance, but not both.
`--gpu-num`, `--name`, and `--data-disk` set the GPU count (default 1), the
instance name, and extra data-disk size in GB (default 0). The command returns
the new instance UUID immediately — the instance may take a moment to appear in
`instance list` — and does not prompt for confirmation.

`clone` posts to `/api/v1/order/instance/clone/payg` and orders a
pay-as-you-go copy of an instance. Choose the target machine with
`--machine-id` or both `--region` and `--gpu`, as with `create`. The image is
always inherited from the source instance. `--gpu-num` defaults to the source
instance's GPU count, `--copy-data-disk` is on by default (disable it with
`--no-copy-data-disk`), and `--keep-service-address` is off. The command
returns the new instance UUID immediately and does not prompt for confirmation.

### 🗂️ Network Disk (NFS)

AutoDL's network disk is regional: each region has its own volume and its own
API host. `nfs regions` shows the available signs, hosts, and quota. `nfs ls`
reads a directory, `nfs download` retrieves a file, `nfs upload` sends a local
file in the same 5 MiB chunks the web console uses, `nfs rm` deletes a file (or
a directory with `-r`), and `nfs df` reports live usage (optionally for one
region).

```bash
autodl nfs regions
autodl nfs ls / --region bj-B1
autodl nfs ls /datasets --region bj-B1
autodl nfs download /models/model.bin --region bj-B1
autodl nfs download /models/model.bin --region bj-B1 -o ./checkpoints/
autodl nfs upload ./model.bin --region bj-B1
autodl nfs upload ./model.bin --region bj-B1 --dir-path /models --filename v2.bin
autodl nfs rm /models/old.bin --region bj-B1
autodl nfs rm /models/old.bin --region bj-B1 --yes
autodl nfs rm /models/old --region bj-B1 -r
autodl nfs df
autodl nfs df --region bj-B1
```

`--region` is required because there is no account-wide default volume (only
`nfs df` can omit it to show every region). `nfs df` reads each created volume's
`/detail` endpoint for total and used space plus inode counts, and also shows
the free-of-charge allowance and maximum capacity. Volumes that are not
initialised yet are listed with `-` usage, because the server rejects the detail
request for them. Uploads hash the first 1 MiB of the
file and send that digest with every chunk, matching the console; a file larger
than 5 MiB is split into ordered multipart chunks, with `is_last` set on the
final one.

Downloads are a two-step process: a JSON call asks the region host for a
short-lived download token, then a browser-style GET fetches the raw file with
that token in the `auth` query string and no `Authorization` header. The
destination defaults to the remote file name in the current directory; pass
`-o/--output` with a file path or an existing directory, and `--force` to
overwrite an existing file.

`rm` is irreversible and asks for confirmation unless `--yes` is passed. With
`-r` it targets the console's directory endpoint and warns that the directory's
contents are included. Use `--yes` in scripts.

### 🛠️ API Debugging

`autodl tools request` is a thin HTTP client for the AutoDL API. It attaches the
stored token and the required `AppVersion` header automatically, and works
against arbitrary URLs when `--no-auth` is passed.

```bash
autodl tools request /api/v1/user/detail
autodl tools request /api/v1/instance -X POST -d '{"page_index": 1}'
autodl tools request /api/v1/user/detail --curl   # print an equivalent curl
autodl tools request /api/v1/user/detail -i       # include status line and headers
autodl tools request /api/v1/user/detail -o out.json
```

### 🤖 MCP Server

Install the optional extra and expose every CLI command as a typed MCP tool —
`instance_list`, `account_balance`, `gpu_machines`, and so on (clients namespace
them with the server name, e.g. `mcp__autodl__instance_list`). Each tool inherits
the root `json` switch, and `autodl_help` / `autodl_run` remain available as
escape hatches.

```bash
pip install "autodl-cli[mcp]"
autodl-mcp                      # serve over stdio
autodl-mcp --groups instance    # only the instance commands
```

`auth paste` is excluded from the typed tools because it reads credentials from
stdin, which the MCP child process does not have.

### 📦 Python SDK

Every handler is reachable through `autodl_cli.api`, which normalises failures
into one exception hierarchy. Tokens are passed explicitly rather than read from
the config file.

```python
from autodl_cli import api
from autodl_cli.errors import AutoDLError

token = "<your JWT>"

try:
    me = api.get_current_user(token)
    balance = api.get_balance(token)
    instances = api.list_instances(token, query="4090")

    for instance in instances:
        print(instance["uuid"], instance["name"])
except AutoDLError as exc:
    print(f"AutoDL call failed: {exc}")
```

Use `api.AutoDLClient` directly when you need the raw authenticated HTTP client.

### 🧾 JSON Everywhere

`--json` turns any command's output into plain UTF-8 JSON with no ANSI escapes,
ready for `jq` and scripts. It is a **global** option, so it goes before the
subcommand:

```bash
autodl --json instance list | jq '.[].uuid'
autodl --json gpu machines --sort price --all | jq '.[0]'
```

---

## 🏗️ Architecture

```
src/autodl_cli/
├── main.py                # Click root group; registers every command group
├── api.py                 # public Python SDK facade
├── client.py              # httpx client — auth, AppVersion header, error mapping
├── config.py              # global settings + per-profile credential files (atomic, 0600)
├── paths.py               # the data directory, resolved in one place
├── errors.py              # AutoDLError hierarchy
├── output.py              # all Rich rendering and --json output
├── commands/              # argument parsing, one module per domain
│   ├── _helpers.py        # shared token/ID helpers
│   ├── auth.py
│   ├── account.py
│   ├── gpu.py
│   ├── image.py
│   ├── instance.py
│   ├── nfs.py
│   ├── profile.py
│   ├── tools.py
│   └── config.py
├── handlers/              # one module per domain; return plain dicts
│   ├── auth.py
│   ├── account.py
│   ├── gpu.py
│   ├── image.py
│   ├── instance.py
│   ├── nfs.py
│   └── tools.py
├── utils/wait.py          # jittered sleep helper
└── mcp/
    ├── generate.py        # AutoDL-specific click2mcp configuration
    └── server.py          # autodl-mcp stdio entry point

tests/
├── conftest.py            # redirects the data tree, registers --live options
├── test_*.py              # offline tests
└── live/                  # collected but skipped without --live
```

```
CLI (main.py — Click group)
  → Command modules (commands/<name>.py — each exports register_<name>())
  → Handlers (handlers/<domain>.py — call the API, return plain Python data)
  → Client (client.py — httpx session, auth, error mapping)
  ↓
AutoDL web API (reverse-engineered)
```

| Layer | What It Does |
|---|---|
| **🔐 Auth** | Stores a browser JWT per profile and a shared device fingerprint, or logs in with a phone number and password. Writes are atomic and private to the user |
| **🌐 Client** | Adds the mandatory `AppVersion` header, attaches the bearer token, maps HTTP and transport failures onto `AutoDLError` subclasses |
| **🧩 Handlers** | Translate API responses into plain dicts. Never print, never read environment variables, so `api.py` and the MCP server can reuse them |
| **🎨 Output** | Owns every Rich style, table, and JSON dump. Commands never print directly |
| **🔌 MCP** | `click2mcp` walks the Click tree and synthesises typed tools; `mcp/` only supplies AutoDL-specific configuration |

---

## 🧪 Extras

### Optional Dependencies

```bash
pip install "autodl-cli[mcp]"    # click2mcp — the autodl-mcp server entry point
pip install "autodl-cli[notify]" # desktop-notifier — `tools snipe --notify`
pip install "autodl-cli[test]"   # pytest, for working on the project itself
```

### Shell Completions

Click ships completion for each shell — add the matching line to your rc file:

```bash
# bash
eval "$(_AUTODL_COMPLETE=bash_source autodl)"
# zsh
eval "$(_AUTODL_COMPLETE=zsh_source autodl)"
# fish
_AUTODL_COMPLETE=fish_source autodl | source
```

### Local Data

```
~/.autodl-cli/
├── config.toml      # global settings: device fingerprint, base URL, timeout
├── active_profile   # plain-text name of the active profile
└── profiles/
    └── default.toml # per-profile token and phone area
```

`AUTODL_CLI_HOME` relocates the whole tree, which is how the test suite keeps its
state out of your real config.

### Development

```bash
pip install -e ".[test]"        # editable install with pytest
pre-commit run --all-files
ruff check .
ruff format .

pytest                          # offline tests, no network
pytest --live                   # hit the real AutoDL API
pytest --live --live-write      # allow tests that modify a real account
```

Live tests are collected but skipped unless `--live` is passed; `tests/conftest.py`
redirects the data tree to `tests/.state/` before any project import.

---

## 🤝 Contributing

The codebase is laid out for extensibility:

- **New command?** Add `commands/<name>.py` with
  `register_<name>(group) -> click.Group`, then call it from `main.py`.
- **New handler?** Add `handlers/<domain>.py`. Return plain dictionaries, never
  print, and go through `AutoDLClient` instead of `httpx`.
- **New MCP tool?** Nothing to do — typed tools are generated from the Click tree.

Run the formatter before submitting:

```bash
pre-commit run --all-files
ruff check .
ruff format .
```

---

## 📜 License

MIT

---

<div align="center">

*Built for people who would rather `ssh` than click.*

[Report a bug](https://github.com/KrisTHL181/autodl-cli/issues) · [Fork this repository](https://github.com/KrisTHL181/autodl-cli/fork) · Star ⭐ this repo!

</div>
