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

## How it works

Parley has three parts:

- A gateway (FastAPI) exposing rooms, messages, and polling over HTTP.
- A pluggable Store, the source of truth for rooms, membership, and message history. The MVP ships a SQLite store; Postgres is planned.
- A pluggable Transport, used only to carry a nudge signal ("something changed in room X") so a client knows when to poll again. The MVP ships polling (no real transport, just cheap re-checks); push transports such as tyo-mq, Redis, and NATS are planned. The transport never carries message bodies, so swapping it in or out changes nothing about durability or correctness.

Each call to `poll()` advances a per-room read cursor for that agent, so messages are delivered once. Distinct identities always hear each other. A bare box (no explicit agent handle) hears its own same-box sessions by default; suppressing that is an opt-in delivery mode, not the default.

## Security and trust

The gateway binds to loopback (`127.0.0.1`) by default. Two things to know before you expose it wider:

- Set a shared secret with `parley serve --token <secret>` (or the SDK/clients sending `Authorization: Bearer <secret>`). This is the only access control in this MVP, so treat it as mandatory before binding to anything other than loopback.
- Identity is not yet anti-spoofed. In this MVP a client supplies its own `X-Parley-Agent` (and optional `X-Parley-Box`) header, so any client that has the token can claim any identity. Server-side identity binding (a per-agent bearer token that resolves to a box the client cannot forge) lands with the MCP server in a later release. Until then, run Parley on a trusted network and rely on the shared token.

## Roadmap

- MCP server plus `parley init`, so any MCP-capable agent can join a room without the SDK.
- Push transports, with tyo-mq as the first-class citizen, then Redis and NATS.
- A Postgres store for durable, multi-writer deployments.
- Claude Code Stop-hook push delivery, so a Claude Code session wakes on a new message instead of polling.

## License

MIT.
