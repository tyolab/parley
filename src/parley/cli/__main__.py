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
    import uvicorn
    from parley.stores.sqlite import SqliteStore
    from parley.transports.polling import PollingTransport
    from parley.gateway.app import build_app
    from parley.mcp.server import build_mcp_app

    async def _run():
        store = await SqliteStore.connect(_db_path(args))
        rest = build_app(store, PollingTransport(), admin_token=args.token)
        servers = [uvicorn.Server(uvicorn.Config(
            rest, host=args.host, port=args.port, log_level="info"))]
        if not args.no_mcp:
            mcp_port = args.mcp_port or (args.port + 1)
            mcp_app = build_mcp_app(store, admin_token=args.token)
            servers.append(uvicorn.Server(uvicorn.Config(
                mcp_app, host=args.host, port=mcp_port, log_level="info")))
        await asyncio.gather(*(s.serve() for s in servers))

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


async def _watch(cfg, room, interval):
    from parley.client import Client
    c = Client(base_url=cfg["gw"], agent=cfg["agent"])
    print(f"[parley] watching as {cfg['agent']} (Ctrl-C to stop)")
    try:
        while True:
            for conv in await c.poll(room):
                for m in conv["messages"]:
                    print(f"[{conv['conv']}] {m['from']}: {m['body']}")
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
    cfg = resolve_config(args)
    if args.cmd == "say":
        asyncio.run(_say(cfg, args.room, args.text))
    elif args.cmd == "join":
        asyncio.run(_join(cfg, args.room))
    elif args.cmd == "watch":
        try:
            asyncio.run(_watch(cfg, args.room, args.interval))
        except KeyboardInterrupt:
            print("\n[parley] stopped")


if __name__ == "__main__":
    main()
