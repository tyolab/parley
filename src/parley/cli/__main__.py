import argparse
import asyncio
import os
import socket
import sys


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
        c.add_argument("--token", default=None)
        if name == "watch":
            c.add_argument("--interval", type=float, default=2.0)
            c.add_argument("--push", action="store_true")

    sy = sub.add_parser("say", help="post one message")
    sy.add_argument("room")
    sy.add_argument("text")
    sy.add_argument("--gw", default=None)
    sy.add_argument("--agent", default=None)
    sy.add_argument("--token", default=None)

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

    en = sub.add_parser("enroll", help="self-enroll a box with a join code and auto-wire it")
    en.add_argument("--gw", default=None, help="gateway REST base, e.g. http://host:8890")
    en.add_argument("--url", default=None, help="alias for --gw (REST base)")
    en.add_argument("--join-code", default=None, help="shared join code (or env PARLEY_JOIN_CODE)")
    en.add_argument("--box", required=True, help="the machine id to claim")
    en.add_argument("--name", default="parley", help="MCP server entry name")
    en.add_argument("--handle", default=None,
                    help="default PARLEY_AGENT baked into the hook env (default = box)")
    en.add_argument("--config-file", default=os.path.expanduser("~/.claude.json"))
    en.add_argument("--settings-file", default=os.path.expanduser("~/.claude/settings.json"))
    en.add_argument("--no-hook", action="store_true", help="skip Stop-hook wiring")
    en.add_argument("--mcp-url", default=None, help="override the MCP URL")
    en.add_argument("--mcp-port", type=int, default=None, help="override the MCP port")
    en.add_argument("--stop-mode", default="notify", choices=["notify", "engage"])

    nt = sub.add_parser("notify", help="run the idle-wake notifier daemon")
    nt.add_argument("--room", action="append", help="room to watch (repeatable)")
    nt.add_argument("--all-rooms", action="store_true",
                    help="watch every room (catch-all); needs a push transport (e.g. tyomq)")
    nt.add_argument("--wake-cmd", required=True, help="command template, {box}/{room}/{from}")
    nt.add_argument("--box", default="")
    nt.add_argument("--debounce", type=float, default=0.5)
    return p


def resolve_config(args) -> dict:
    gw = getattr(args, "gw", None) or os.environ.get("PARLEY_GW") or "http://127.0.0.1:8790"
    agent = getattr(args, "agent", None) or os.environ.get("PARLEY_AGENT") or socket.gethostname()
    token = getattr(args, "token", None) or os.environ.get("PARLEY_TOKEN")
    return {"gw": gw, "agent": agent, "token": token}


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

    async def _run():
        import os

        from parley.stores.factory import is_pg_dsn, make_store
        db = os.environ.get("PARLEY_DB")
        location = db if is_pg_dsn(db) else _db_path(args)
        store = await make_store(location, schema=os.environ.get("PARLEY_PG_SCHEMA", "parley"))

        from parley.transports.factory import make_transport
        transport = make_transport(
            os.environ.get("PARLEY_TRANSPORT", "polling"),
            host=os.environ.get("PARLEY_MQ_HOST", "localhost"),
            port=os.environ.get("PARLEY_MQ_PORT", "17352"),
            token=os.environ.get("MQ_TOKEN"),
            url=os.environ.get("PARLEY_REDIS_URL", "redis://127.0.0.1:6379"),
            servers=os.environ.get("PARLEY_NATS", "nats://127.0.0.1:4222"))
        # null MCP port when --no-mcp, so /enroll advertises it honestly.
        mcp_port = None if args.no_mcp else (args.mcp_port or (args.port + 1))
        rest = build_app(store, transport, admin_token=args.token,
                         join_code=os.environ.get("PARLEY_JOIN_CODE"), mcp_port=mcp_port)
        servers = [uvicorn.Server(uvicorn.Config(
            rest, host=args.host, port=args.port, log_level="info"))]
        if not args.no_mcp:
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
    c = Client(base_url=cfg["gw"], agent=cfg["agent"], token=cfg.get("token"))
    try:
        print(await c.say(room, text))
    finally:
        await c.close()


async def _join(cfg, room):
    from parley.client import Client
    c = Client(base_url=cfg["gw"], agent=cfg["agent"], token=cfg.get("token"))
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


async def _enroll_request(rest, join_code, box):
    """POST /enroll and return (status_code, json_dict). Isolated so the wiring flow
    in `_enroll` can be tested without a live gateway."""
    import httpx
    async with httpx.AsyncClient(base_url=rest) as c:
        r = await c.post("/enroll", json={"box": box},
                         headers={"Authorization": f"Bearer {join_code}"})
        try:
            data = r.json()
        except Exception:  # noqa: BLE001 - non-JSON error body -> surface raw text
            data = {"detail": r.text}
        return r.status_code, data


def _derive_mcp_url(rest, mcp_url, mcp_port, returned_mcp_port):
    """MCP URL precedence: explicit --mcp-url; else gw host + (--mcp-port | the port
    the server advertised | gw_port+1), path /mcp."""
    if mcp_url:
        return mcp_url
    from urllib.parse import urlsplit, urlunsplit
    parts = urlsplit(rest)
    scheme = parts.scheme or "http"
    gw_port = parts.port or (443 if scheme == "https" else 80)
    port = mcp_port or returned_mcp_port or (gw_port + 1)
    return urlunsplit((scheme, f"{parts.hostname}:{port}", "/mcp", "", ""))


def _stop_hook_command(name):
    # Source the per-name env file, let a live TYODE_AGENT override PARLEY_AGENT, then
    # run the bundled Stop hook. Uses sys.executable (the interpreter running `enroll`,
    # which by definition has parley installed) rather than a bare `python` that may not
    # exist or lack parley on the target box (venv/pipx/system all differ).
    return (f"bash -c 'set -a; . \"$HOME/.config/parley/{name}.env\"; "
            f"[ -n \"${{TYODE_AGENT:-}}\" ] && PARLEY_AGENT=\"$TYODE_AGENT\"; "
            f"exec {sys.executable} -m parley.hooks.stop_hook'")


def _enroll(args):
    rest = args.gw or args.url
    if not rest:
        print("[parley enroll] error: --gw (REST base URL) is required", file=sys.stderr)
        return 2
    join_code = args.join_code or os.environ.get("PARLEY_JOIN_CODE")
    if not join_code:
        print("[parley enroll] error: --join-code (or env PARLEY_JOIN_CODE) is required",
              file=sys.stderr)
        return 2
    box = args.box
    handle = args.handle or box

    status, data = asyncio.run(_enroll_request(rest, join_code, box))
    if status != 200:
        detail = data.get("detail") if isinstance(data, dict) else data
        print(f"[parley enroll] enrollment failed ({status}): {detail}", file=sys.stderr)
        return 1
    token = data["token"]
    mcp_url = _derive_mcp_url(rest, args.mcp_url, args.mcp_port, data.get("mcp_port"))

    from parley.cli.init_config import merge_mcp_entry, register_stop_hook, write_hook_env
    config_file = os.path.expanduser(args.config_file)
    merge_mcp_entry(config_file, name=args.name, url=mcp_url, token=token)

    env_path = None
    settings_file = None
    if not args.no_hook:
        env_path = os.path.expanduser(f"~/.config/parley/{args.name}.env")
        write_hook_env(env_path, gw=rest, token=token, agent=handle, stop_mode=args.stop_mode)
        settings_file = os.path.expanduser(args.settings_file)
        register_stop_hook(settings_file, command=_stop_hook_command(args.name))

    print(f"✅ enrolled as {box}")
    print(f"  MCP entry '{args.name}' -> {mcp_url}")
    print(f"  config:   {config_file}")
    if env_path:
        print(f"  hook env: {env_path} (mode 0600)")
        print(f"  settings: {settings_file} (Stop hook registered)")
    print(f"  next: set a distinct per-session handle, e.g. "
          f"export PARLEY_AGENT={box}-agent#1")
    print(f"        (an unset PARLEY_AGENT collapses to the bare box '{box}', "
          f"the box-catch-all identity)")
    return 0


def _notify(args):
    import os

    from parley.notify.daemon import Notifier
    from parley.transports.factory import make_transport

    rooms = ["*"] if args.all_rooms else args.room
    if not rooms:
        print("[parley notify] error: specify --room <name> (repeatable) or --all-rooms",
              file=sys.stderr)
        return 2

    async def _run():
        # Build the transport INSIDE the running loop: a thread-bridged adapter
        # (tyo-mq) captures the running loop at construction, so constructing it
        # before asyncio.run() would bind a dead loop and the wake would never fire.
        kind = os.environ.get("PARLEY_TRANSPORT", "polling")
        transport = make_transport(
            kind, host=os.environ.get("PARLEY_MQ_HOST", "localhost"),
            port=os.environ.get("PARLEY_MQ_PORT", "17352"),
            token=os.environ.get("MQ_TOKEN"),
            url=os.environ.get("PARLEY_REDIS_URL", "redis://127.0.0.1:6379"),
            servers=os.environ.get("PARLEY_NATS", "nats://127.0.0.1:4222"))
        n = Notifier(transport, rooms=rooms, wake_cmd=args.wake_cmd, box=args.box,
                     debounce_s=args.debounce)
        await n.start()
        label = "all rooms" if args.all_rooms else ", ".join(rooms)
        print(f"[parley notify] watching {label} (Ctrl-C to stop)")
        try:
            while True:
                await asyncio.sleep(3600)
        finally:
            await n.stop()
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        print("\n[parley notify] stopped")


async def _watch(cfg, room, interval, push=False):
    from parley.client import Client
    c = Client(base_url=cfg["gw"], agent=cfg["agent"], token=cfg.get("token"))

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
    if args.cmd == "enroll":
        raise SystemExit(_enroll(args))
    if args.cmd == "notify":
        raise SystemExit(_notify(args))
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
