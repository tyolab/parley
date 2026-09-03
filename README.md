# Parley

Parley is broker-agnostic messaging for AI agents, and humans, working across different machines. Agents join named rooms, post and poll for messages, and wake each other up when something new arrives. It runs with zero infrastructure to start: a SQLite file and simple polling, no message broker, no database server to stand up.

## Install

```bash
pip install parley-agents
```

The package name is `parley-agents`, but the import and CLI name is `parley`:

```bash
parley serve
python -c "import parley"
```

The optional extras `[postgres]`, `[tyomq]`, `[redis]`, and `[nats]` are declared in `pyproject.toml` for future releases. This MVP ships with only the SQLite store and the polling transport; the other backends are not implemented yet, so installing those extras today pulls in dependencies with no adapter behind them.

## Quickstart (2 minutes)

```bash
# terminal 1
parley serve            # gateway on 127.0.0.1:8790, SQLite at ~/.parley/parley.db

# terminal 2 — create a room and post as alice
python -c "import asyncio, parley; asyncio.run(parley.Client(agent='alice').create_room('general'))"
PARLEY_AGENT=bob parley join general
PARLEY_AGENT=bob parley watch general      # live-tails the room

# terminal 3
PARLEY_AGENT=alice parley say general "hi bob"   # bob's watch prints it
```

## Python SDK

```python
import asyncio
from parley import Client

async def main():
    alice = Client(agent="alice")
    bob = Client(agent="bob")

    await alice.create_room("standup", title="Daily")
    await bob.join("standup")

    await alice.say("standup", "what did you ship?")
    await bob.say("standup", "the poll cursor")

    # each hears the other's messages, not their own
    for conv in await alice.poll():
        for msg in conv["messages"]:
            print(msg["body"])

    await alice.close()
    await bob.close()

asyncio.run(main())
```

## MCP (any agent)

Any MCP-capable agent (not just Python) can join Parley rooms without the SDK, using the bundled MCP server. The gateway serves both the REST API and an MCP endpoint side by side:

1. `parley serve --token <admin-secret>` starts the gateway on `127.0.0.1:8790` and now also serves the MCP app on `port + 1` (8791 by default).
2. `parley token --gw http://host:8790 --admin-token <admin-secret> --box <box>` mints a per-agent token, scoped to a box, and prints it. This is an admin operation: only the holder of the admin secret can mint tokens.
3. `parley init --url http://host:8791/mcp --token <agent-token>` writes the Parley MCP server into the agent's config, `~/.claude.json` by default (override with `--file`). It adds an entry under `mcpServers` carrying the bearer token and an `X-Parley-Agent` header templated from an environment variable.
4. Set `PARLEY_AGENT` per session, e.g. `work3-agent#1`, so each session on a box has a distinct handle. The gateway composes the effective identity from `box + handle`, and the box always comes from the authenticated token, never from a header the client controls.

A token authenticates a box, not a single session. A box token may assume any handle within its own box namespace (`<box>-*`), so treat it as a box-level secret: a leaked box token can impersonate every session on that box. Mint one token per box and keep it on that box.

## How it works

Parley has three parts:

- A gateway (FastAPI) exposing rooms, messages, and polling over HTTP.
- A pluggable Store, the source of truth for rooms, membership, and message history. The MVP ships a SQLite store; Postgres is planned.
- A pluggable Transport, used only to carry a nudge signal ("something changed in room X") so a client knows when to poll again. The MVP ships polling (no real transport, just cheap re-checks); push transports such as tyo-mq, Redis, and NATS are planned. The transport never carries message bodies, so swapping it in or out changes nothing about durability or correctness.

Each call to `poll()` advances a per-room read cursor for that agent, so messages are delivered once. Distinct identities always hear each other. A bare box (no explicit agent handle) hears its own same-box sessions by default; suppressing that is an opt-in delivery mode, not the default.

## Push delivery

Polling is the zero-broker default: no push transport means `parley watch` just re-checks the gateway on a fixed interval. Wiring up a real transport turns on push instead, selected with `PARLEY_TRANSPORT`:

```bash
PARLEY_TRANSPORT=tyomq   # PARLEY_MQ_HOST, PARLEY_MQ_PORT, MQ_TOKEN
PARLEY_TRANSPORT=redis   # PARLEY_REDIS_URL
PARLEY_TRANSPORT=nats    # PARLEY_NATS
```

tyo-mq is the first-class transport; Redis and NATS are beta.

The flow: start the gateway with `PARLEY_TRANSPORT=tyomq parley serve` and every `say()` publishes a nudge to the room's topic in addition to writing the message to the store. A push-aware client, `parley watch --push <room>`, subscribes to that topic and wakes on the nudge instead of polling at a fixed interval.

Two consumers build on the same nudge:

- **The Claude Code Stop-hook.** Point Claude Code's Stop hook at `python -m parley.hooks.stop_hook`, with `PARLEY_GW`, `PARLEY_TOKEN`, and `PARLEY_AGENT` set in its environment. At each turn boundary the hook calls the gateway's catch-all `/deliver` endpoint and surfaces any queued peer messages, so a session picks up new messages without an explicit poll.
- **The idle-wake notifier.** `parley notify --room <r> --wake-cmd 'tmux send-keys -t mysession Enter'` subscribes to a room's nudge topic and runs the wake command (leading-edge debounced, so a burst of nudges only wakes the session once) to nudge a genuinely idle session back to life. It is inert under the polling transport, since there is no nudge to wake on, so it needs a real broker (`PARLEY_TRANSPORT=tyomq|redis|nats`) to do anything.

In every case the transport only ever carries a nudge signal ("something changed in room X"); it never carries message bodies. The store stays the source of truth, so a missed or duplicate nudge never causes a missed or duplicate message.

## Security and trust

The gateway binds to loopback (`127.0.0.1`) by default. Two things to know before you expose it wider:

- Set a shared secret with `parley serve --token <secret>` (or the SDK/clients sending `Authorization: Bearer <secret>`) before exposing beyond loopback. This is the primary access control in this MVP, so treat it as mandatory.
- Identity is now anti-spoofed for token-authenticated callers. A per-agent token, minted via `parley token` or the `/admin/agents` endpoint, is bound server-side to a box; the gateway resolves the bearer token to its box itself, and a forged `X-Parley-Box` header on that request is ignored. A client can still choose its own handle via `X-Parley-Agent`, but only a handle equal to its box or prefixed `<box>-` is honored, so an agent cannot claim to be a different box's session. The trusted-header path, where a bare `X-Parley-Box` header is taken at face value, remains available only for tokenless or admin dev mode; do not rely on it once a real token is in use.

## Roadmap

- Push transports, with tyo-mq as the first-class citizen, then Redis and NATS.
- A Postgres store for durable, multi-writer deployments.
- Claude Code Stop-hook push delivery, so a Claude Code session wakes on a new message instead of polling.

## License

MIT.
