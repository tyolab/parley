import argparse
import asyncio
import os
import socket


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="parley", description="Parley agent messaging")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="run the gateway")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8790)
    s.add_argument("--db", default=None)
    s.add_argument("--token", default=None)
    s.add_argument("--mcp-port", type=int, default=None)
    s.add_argument("--no-mcp", action="store_true")

    for name, help_ in [("join", "join a room"), ("watch", "watch/participate in rooms")]:
        c = sub.add_parser(name, help=help_)
        c.add_argument("room", nargs="?" if name == "watch" else None)
        c.add_argument("--gw", default=None)
        c.add_argument("--agent", default=None)
        if name == "watch":
            c.add_argument("--interval", type=float, default=2.0)
            c.add_argument("--push", action="store_true")

    sy = sub.add_parser("say", help="post one message")
    sy.add_argument("room")
    sy.add_argument("text")
    sy.add_argument("--gw", default=None)
    sy.add_argument("--agent", default=None)

    tk = sub.add_parser("token", help="mint a per-agent token (admin)")
    tk.add_argument("--gw", default=None)
    tk.add_argument("--admin-token", required=True)
    tk.add_argument("--box", required=True)
    tk.add_argument("--label", default=None)

    ini = sub.add_parser("init", help="write the Parley MCP server into an agent config")
    ini.add_argument("--url", required=True, help="the gateway MCP URL, e.g. http://host:8791/mcp")
    ini.add_argument("--token", required=True, help="a per-agent token (from `parley token`)")
    ini.add_argument("--name", default="parley")
    ini.add_argument("--file", default=os.path.expanduser("~/.claude.json"))
    return p


def resolve_config(args) -> dict:
    gw = getattr(args, "gw", None) or os.environ.get("PARLEY_GW") or "http://127.0.0.1:8790"
    agent = getattr(args, "agent", None) or os.environ.get("PARLEY_AGENT") or socket.gethostname()
    return {"gw": gw, "agent": agent}


def _db_path(args) -> str:
    path = args.db or os.environ.get("PARLEY_DB")
    if not path:
        d = os.path.expanduser("~/.parley")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, "parley.db")
    return path


def _serve(args):
    import contextlib
    import signal

    import uvicorn

    from parley.gateway.app import build_app
    from parley.mcp.server import build_mcp_app
    from parley.stores.sqlite import SqliteStore

    async def _run():
        store = await SqliteStore.connect(_db_path(args))
        import os
        from parley.transports.factory import make_transport
        transport = make_transport(
            os.environ.get("PARLEY_TRANSPORT", "polling"),
            host=os.environ.get("PARLEY_MQ_HOST", "localhost"),
            port=os.environ.get("PARLEY_MQ_PORT", "17352"),
            token=os.environ.get("MQ_TOKEN"),
            url=os.environ.get("PARLEY_REDIS_URL", "redis://127.0.0.1:6379"),
            servers=os.environ.get("PARLEY_NATS", "nats://127.0.0.1:4222"))
        rest = build_app(store, transport, admin_token=args.token)
        servers = [uvicorn.Server(uvicorn.Config(
            rest, host=args.host, port=args.port, log_level="info"))]
        if not args.no_mcp:
            mcp_port = args.mcp_port or (args.port + 1)
            mcp_app = build_mcp_app(store, admin_token=args.token)
            servers.append(uvicorn.Server(uvicorn.Config(
                mcp_app, host=args.host, port=mcp_port, log_level="info")))
        # Both servers run on one loop. Suppress each server's own signal capture --
        # with two servers the last handler installed would win, leaving the other
        # running forever on SIGINT/SIGTERM -- and drive a single shared shutdown so
        # a managed process (systemd/container) stops cleanly.
        for s in servers:
            s.capture_signals = contextlib.nullcontext

        def _shutdown():
            for s in servers:
                s.should_exit = True

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(NotImplementedError):
                loop.add_signal_handler(sig, _shutdown)
        try:
            await asyncio.gather(*(s.serve() for s in servers))
        finally:
            await store.close()

    asyncio.run(_run())


async def _say(cfg, room, text):
    from parley.client import Client
    c = Client(base_url=cfg["gw"], agent=cfg["agent"])
    try:
        print(await c.say(room, text))
    finally:
        await c.close()


async def _join(cfg, room):
    from parley.client import Client
    c = Client(base_url=cfg["gw"], agent=cfg["agent"])
    try:
        print(await c.join(room))
    finally:
        await c.close()


async def _token(args):
    import httpx
    gw = args.gw or os.environ.get("PARLEY_GW") or "http://127.0.0.1:8790"
    async with httpx.AsyncClient(base_url=gw) as c:
        r = await c.post("/admin/agents",
                         json={"box": args.box, "label": args.label},
                         headers={"Authorization": f"Bearer {args.admin_token}"})
        r.raise_for_status()
        print(r.json()["token"])


def _init(args):
    from parley.cli.init_config import merge_mcp_entry
    merge_mcp_entry(args.file, name=args.name, url=args.url, token=args.token)
    print(f"[parley init] wrote '{args.name}' -> {args.url} into {args.file}")


async def _watch(cfg, room, interval, push=False):
    from parley.client import Client
    c = Client(base_url=cfg["gw"], agent=cfg["agent"])

    async def _drain():
        for conv in await c.poll(room):
            for m in conv["messages"]:
                print(f"[{conv['conv']}] {m['from']}: {m['body']}")

    if push and room:
        import os
        from parley.transports.factory import make_transport
        transport = make_transport(
            os.environ.get("PARLEY_TRANSPORT", "polling"),
            host=os.environ.get("PARLEY_MQ_HOST", "localhost"),
            port=os.environ.get("PARLEY_MQ_PORT", "17352"),
            token=os.environ.get("MQ_TOKEN"),
            url=os.environ.get("PARLEY_REDIS_URL", "redis://127.0.0.1:6379"),
            servers=os.environ.get("PARLEY_NATS", "nats://127.0.0.1:4222"))
        print(f"[parley] watching {room} as {cfg['agent']} (push; Ctrl-C to stop)")
        await _drain()  # catch up on anything already waiting
        subs = await c.listen(transport, [room], lambda sig: _drain())
        try:
            while True:
                await asyncio.sleep(3600)
        finally:
            for s in subs:
                await s.close()
            await transport.close()
            await c.close()
        return

    print(f"[parley] watching as {cfg['agent']} (Ctrl-C to stop)")
    try:
        while True:
            await _drain()
            await asyncio.sleep(interval)
    finally:
        await c.close()


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.cmd == "serve":
        _serve(args)
        return
    if args.cmd == "token":
        asyncio.run(_token(args))
        return
    if args.cmd == "init":
        _init(args)
        return
    cfg = resolve_config(args)
    if args.cmd == "say":
        asyncio.run(_say(cfg, args.room, args.text))
    elif args.cmd == "join":
        asyncio.run(_join(cfg, args.room))
    elif args.cmd == "watch":
        try:
            asyncio.run(_watch(cfg, args.room, args.interval, getattr(args, "push", False)))
        except KeyboardInterrupt:
            print("\n[parley] stopped")


if __name__ == "__main__":
    main()
