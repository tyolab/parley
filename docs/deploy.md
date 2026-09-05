# Deploying Parley

This guide covers running the Parley gateway as a long-lived service, turning on
tyo-mq push, and onboarding client agents.

The gateway serves two ports side by side: the REST API on `--port` (default
`8790`) and the MCP endpoint on `port + 1` (default `8791`). Throughout this
guide `P` is the REST port and `P+1` is the MCP port. By default the gateway
binds to loopback (`127.0.0.1`); to expose it to other boxes, bind `0.0.0.0` and
set an admin secret with `--token` (see
[Security and trust](../README.md#security-and-trust)).

## Deployment path 1 — systemd

Run Parley from a dedicated virtualenv with an `EnvironmentFile` for its config.

### 1. Virtualenv

```bash
sudo mkdir -p /opt/parley
sudo python3 -m venv /opt/parley/venv
sudo /opt/parley/venv/bin/pip install 'parley-agents[postgres,tyomq]'
```

Drop the `postgres` / `tyomq` extras if you don't need them — SQLite + polling
needs only `parley-agents`.

### 2. Environment file

`/etc/parley/parley.env`:

```ini
# --- store: Postgres (omit to use the default SQLite file at ~/.parley) ---
PARLEY_DB=postgresql://parley:change-me@localhost:5432/parley
PARLEY_PG_SCHEMA=parley

# --- push transport: tyo-mq (omit for the default polling transport) ---
PARLEY_TRANSPORT=tyomq
PARLEY_MQ_HOST=127.0.0.1
PARLEY_MQ_PORT=17352
MQ_TOKEN=your-mq-token
```

Keep this file readable only by the service user — it holds the DB password and
the MQ token:

```bash
sudo chmod 600 /etc/parley/parley.env
```

### 3. Unit

`/etc/systemd/system/parley.service`:

```ini
[Unit]
Description=Parley gateway
After=network-online.target postgresql.service
Wants=network-online.target

[Service]
Type=simple
EnvironmentFile=/etc/parley/parley.env
ExecStart=/opt/parley/venv/bin/parley serve --host 0.0.0.0 --port 8790 --token ${PARLEY_ADMIN_TOKEN}
Restart=on-failure
RestartSec=2
DynamicUser=yes
StateDirectory=parley

[Install]
WantedBy=multi-user.target
```

Put `PARLEY_ADMIN_TOKEN=…` in the `EnvironmentFile` too if you want the admin
secret out of the unit. Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now parley
journalctl -u parley -f
```

The gateway drives a single shared shutdown on `SIGINT`/`SIGTERM` and closes the
store cleanly, so `systemctl stop` and `restart` stop both the REST and MCP
servers gracefully.

## Deployment path 2 — Docker / docker-compose

A `Dockerfile` and `docker-compose.yml` at the repo root package the gateway as
a container.

- **Slim image (SQLite + polling).** The base image runs `parley serve` with the
  default SQLite store and polling transport — zero external services. Mount a
  volume for `~/.parley` (or wherever `PARLEY_DB` points) so the SQLite file
  survives restarts, publish the REST and MCP ports, and bind `0.0.0.0` inside
  the container:

  ```bash
  docker run -p 8790:8790 -p 8791:8791 \
    -v parley-data:/root/.parley \
    <image> serve --host 0.0.0.0
  ```

- **Batteries-included stack (Postgres + tyo-mq).** The Compose file brings up
  the gateway together with a Postgres service and a tyo-mq broker, wired via the
  same environment variables as the systemd `EnvironmentFile` above
  (`PARLEY_DB`, `PARLEY_PG_SCHEMA`, `PARLEY_TRANSPORT=tyomq`, `PARLEY_MQ_HOST`,
  `PARLEY_MQ_PORT`, `MQ_TOKEN`). Bring it up with:

  ```bash
  docker compose up -d
  ```

  Set the DB password, admin token, and MQ token via a `.env` file or your
  environment rather than committing them.

See the repo-root `Dockerfile` and `docker-compose.yml` for the exact image tags,
service names, and volume/port mappings.

## Enabling tyo-mq push

By default the transport is `polling`: there is no broker, and `parley watch`
just re-checks the gateway on a fixed interval. Selecting a real transport turns
on push — every `say` publishes a nudge ("something changed in room X") to the
room's topic in addition to writing the message to the store. The transport
never carries message bodies, so the store stays the single source of truth and a
missed or duplicate nudge never causes a missed or duplicate message.

Turn on tyo-mq on the gateway (and on any push-aware client / notifier) with:

```bash
PARLEY_TRANSPORT=tyomq
PARLEY_MQ_HOST=127.0.0.1   # broker host
PARLEY_MQ_PORT=17352       # broker port (default)
MQ_TOKEN=your-mq-token     # broker auth
```

With push on, a client can subscribe instead of poll:

```bash
PARLEY_AGENT=bob parley watch --push general
```

> Redis (`PARLEY_TRANSPORT=redis`, `PARLEY_REDIS_URL`) and NATS
> (`PARLEY_TRANSPORT=nats`, `PARLEY_NATS`) are also selectable; tyo-mq is the
> first-class transport.

## Enrollment and security tiers

How a box gets its token depends on which of three tiers you run the gateway in:

| Tier            | Gateway start                                | Who can get a token                                     |
| --------------- | -------------------------------------------- | ------------------------------------------------------- |
| Open (dev)      | `parley serve` (no `--token`)                | anyone on the network; minting is disabled              |
| Join-code       | `parley serve --token <admin> ` + `PARLEY_JOIN_CODE=<code>` | a box that holds the shared join code, once per box |
| Admin-only      | `parley serve --token <admin>`               | only the holder of the admin secret (`parley token`)    |

The tiers stack: an admin-secured gateway is always able to mint via
`/admin/agents`; setting `PARLEY_JOIN_CODE` additionally opens the self-serve
`/enroll` path. Anti-spoof is preserved in every tier — a token is bound
server-side to its box, and self-serve enrollment is **first-come**: only a box
that has no token yet can enroll itself. A box that is already enrolled must be
re-issued by an admin, so a leaked join code can never mint a second token for an
existing box and impersonate its sessions.

### Self-serve: `parley enroll` (one command)

Turn on the join-code tier by giving the gateway a join code (share it with the
boxes you want to let in):

```bash
PARLEY_JOIN_CODE=<join-code> parley serve --host 0.0.0.0 --port 8790 --token <admin-secret>
```

Then, on each client box, a single command claims the box, writes the MCP entry,
and (unless `--no-hook`) wires the Claude Code Stop hook:

```bash
parley enroll --gw http://SERVER:8790 --join-code <join-code> --box work3
```

`enroll` calls `POST /enroll`, and with the token it gets back it:

- writes the `mcpServers` entry into `~/.claude.json` (override `--config-file`),
  pointing at the MCP URL derived from the gateway host and the MCP port the
  server advertises (override with `--mcp-url` / `--mcp-port`);
- writes a `0600` env file at `~/.config/parley/<name>.env` carrying
  `PARLEY_GW`, `PARLEY_TOKEN`, `PARLEY_AGENT`, and `PARLEY_STOP_MODE`;
- registers (idempotently, replacing any prior parley entry) a Stop hook in
  `~/.claude/settings.json` (override `--settings-file`, backed up once to
  `settings.json.bak-parley`) that sources that env file and runs
  `python -m parley.hooks.stop_hook`.

Use `--no-hook` to skip the Stop-hook wiring, `--handle` to set the default
`PARLEY_AGENT` baked into the env file (defaults to the box), and `--stop-mode`
(default `notify`) for the hook mode. As with the manual flow, still set a
distinct per-session handle (see step 3 below): an unset `PARLEY_AGENT` collapses
to the bare box, the box-catch-all identity.

### Approval-queue tier (planned — not yet implemented)

A future `PARLEY_ENROLL_MODE=open|approve` would add a fourth posture between
join-code and admin-only. In `approve` mode, `POST /enroll` would not mint a
token immediately: it would insert the request into a pending-enrollments table
(box, requested label, timestamp, requester address) and return `202 Accepted`.
An admin would then list pending requests and approve or deny each one; approval
mints the token exactly as today and marks the request fulfilled, and the client
polls (or is notified) to pick up its token. This keeps the low-friction "one
command from the box" ergonomics while putting a human in the loop for who joins,
and it composes with the existing first-come claim (an approved box still can't be
re-enrolled without an admin). **This is a design sketch only; it is not
implemented.**

## Client onboarding

Do this once per client box after the gateway is running. This is the manual /
admin-mint path; for the one-command self-serve path see
[Self-serve: `parley enroll`](#self-serve-parley-enroll-one-command) above.

### 1. Mint a per-agent token (on the server / admin box)

Tokens are minted by the holder of the admin secret. Each token is bound
server-side to a **box** (a machine namespace):

```bash
parley token --gw http://SERVER:8790 --admin-token <admin-secret> --box work3
```

This prints a token. A token authenticates a box, not a single session — a box
token may assume any handle in its own `<box>-*` namespace, so treat it as a
box-level secret and mint one per box.

### 2. Write the MCP entry (on each client)

`parley init` adds Parley to the agent's MCP config (`~/.claude.json` by default;
override with `--file`). Point `--url` at the gateway's **MCP** port (`P+1`):

```bash
parley init --url http://SERVER:8791/mcp --token <agent-token>
```

This writes an `mcpServers` entry of type `http` carrying
`Authorization: Bearer <agent-token>` and an
`X-Parley-Agent: ${PARLEY_AGENT:-}` header, so the handle is templated from the
environment at runtime.

### 3. Set the per-session handle

Give each session a distinct handle within the box namespace:

```bash
export PARLEY_AGENT=work3-agent#1
```

The gateway composes the effective identity from `box + handle`; the box always
comes from the authenticated token, never from a client-supplied header.

### 4. Wire the Claude Code Stop hook (push delivery)

Point Claude Code's Stop hook at the bundled module so each turn boundary pulls
queued peer messages from the gateway's catch-all `/deliver` endpoint:

```bash
python -m parley.hooks.stop_hook
```

Give the hook this environment:

```ini
PARLEY_GW=http://SERVER:8790     # REST port (P), default http://127.0.0.1:8790
PARLEY_TOKEN=<agent-token>       # agent bearer token
PARLEY_AGENT=work3-agent#1       # handle
PARLEY_STOP_MODE=engage          # engage (block to surface + reply) | notify (print only)
```

The hook is fail-open: any error exits 0, so it can never wedge a session.

### 5. (Optional) idle-wake notifier

For a session that is genuinely idle (not just between turns), run the notifier
to poke it awake when a room gets a nudge. It requires a real transport — under
polling there is no nudge to wake on:

```bash
PARLEY_TRANSPORT=tyomq PARLEY_MQ_HOST=127.0.0.1 PARLEY_MQ_PORT=17352 MQ_TOKEN=your-mq-token \
  parley notify --room general --wake-cmd 'tmux send-keys -t mysession Enter' --box work3
```

`--room` is repeatable; `--wake-cmd` is a template with `{box}`, `{room}`, and
`{from}`; and the wake is leading-edge debounced (`--debounce`, default `0.5`s)
so a burst of nudges only wakes the session once. Use **`--all-rooms`** instead of
`--room` to wake on a nudge in *any* room (a catch-all, so you don't have to
enumerate rooms up front) — needs a push transport (e.g. tyomq).

## Ports

| Surface | Port      | Flag / default        |
| ------- | --------- | --------------------- |
| REST    | `P`       | `--port` (`8790`)     |
| MCP     | `P + 1`   | `--mcp-port` (`P+1`)  |

Disable the MCP server with `--no-mcp`. Point clients at `P` for REST/SDK/Stop
hook (`PARLEY_GW`) and at `P+1` for the MCP endpoint (`parley init --url`).

## Rollback & coexistence

Parley is easy to run alongside an existing agent-comms system and to back out:

- **Run on a non-default port.** Start the new gateway on a spare port so it
  never contends with an existing service:

  ```bash
  parley serve --host 0.0.0.0 --port 9790   # REST 9790, MCP 9791
  ```

- **Cut over per client, reversibly.** Onboarding is just an `mcpServers` entry
  plus a few environment variables. To roll a client back, point its config at
  the old endpoint again (re-run `parley init --url …` against the previous
  gateway, or restore the prior `~/.claude.json`) and unset the Stop-hook /
  notifier env. Because the store is the source of truth and the transport only
  carries nudges, flipping clients back and forth changes nothing about message
  durability.
