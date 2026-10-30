import contextvars

from parley.core.store import extract_mentions
from parley.gateway.identity import resolve_identity

current_agent_id = contextvars.ContextVar("parley_agent_id", default=None)
current_box = contextvars.ContextVar("parley_box", default=None)


class IdentityMiddleware:
    """ASGI middleware: for HTTP scopes, resolve the request identity (bearer->box,
    anti-spoof) and set it on ContextVars for the duration of the request so the
    tools can read it. Non-HTTP scopes (e.g. 'lifespan') pass straight through."""
    def __init__(self, app, store, admin_token):
        self.app, self.store, self.admin_token = app, store, admin_token

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        agent_id, box, _is_admin = await resolve_identity(self.store, headers, self.admin_token)
        t_a = current_agent_id.set(agent_id)
        t_b = current_box.set(box)
        try:
            await self.app(scope, receive, send)
        finally:
            current_agent_id.reset(t_a)
            current_box.reset(t_b)


def _agent() -> str:
    aid = current_agent_id.get()
    if aid is None:
        raise ValueError("unauthorized: unknown or missing agent identity")
    return aid


async def _tool_names(app) -> list[str]:
    """Registered tool names, for tests. `app` is the IdentityMiddleware wrapper;
    the FastMCP instance is stashed on it as `._mcp`. Async because FastMCP's
    list_tools() is a coroutine."""
    mcp = getattr(app, "_mcp", None)
    if mcp is None:
        return []
    return [t.name for t in await mcp.list_tools()]


def build_mcp_app(store, admin_token):
    from mcp.server.fastmcp import FastMCP
    from mcp.server.transport_security import TransportSecuritySettings

    mcp = FastMCP("parley", transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False))

    async def _room_error(conv, agent):
        """Error payload if `conv` is unknown or `agent` is not a member, else None.
        Lets a named poll/peek say "no such room" vs "join first" instead of returning
        an empty result that is indistinguishable from "nothing unread"."""
        if not conv:
            return None
        if await store.get_room(conv) is None:
            return {"conversations": [], "error":
                    f"No conversation named '{conv}' exists. Use list_all_convs to find "
                    f"rooms, or start_conv('{conv}') to create it."}
        if not await store.is_member(conv, agent):
            return {"conversations": [], "error":
                    f"You are not a member of '{conv}'. Call join_conv('{conv}') first."}
        return None

    @mcp.tool()
    async def start_conv(conv: str, title: str | None = None) -> dict:
        """Start (or join, if it exists) a named conversation and subscribe me."""
        return await store.create_room(conv, _agent(), title)

    @mcp.tool()
    async def join_conv(conv: str) -> dict:
        """Join an existing conversation. {exists: false} means call start_conv."""
        return await store.join(conv, _agent())

    @mcp.tool()
    async def leave_conv(conv: str) -> dict:
        """Leave a conversation."""
        return await store.leave(conv, _agent())

    @mcp.tool()
    async def say(conv: str, text: str, join: bool = False) -> dict:
        """Post a message to a conversation. You must be a member; pass join=True to
        join-and-send in one call for a room you have not joined yet.

        The reply flags two "sent, but will not reach who it was for" cases, both
        non-blocking (the message is still posted):
          * `warning` when you are the only member (no one else will receive it).
          * `unknown_mentions`: @handles in the text that are NOT members of this room
            (e.g. a handoff addressed to someone who isn't here), so you catch it at
            send time instead of learning it from a human days later."""
        agent = _agent()
        if join and not await store.is_member(conv, agent):
            j = await store.join(conv, agent)
            if not j.get("exists"):
                return {"ok": False, "reason":
                        f"No conversation named '{conv}' exists; cannot join. "
                        f"Use start_conv first."}
        res = await store.say(conv, agent, text)
        if res.get("ok"):
            members = await store.members(conv)
            if not [m for m in members if m != agent]:
                res = {**res, "warning":
                       f"You are the only member of '{conv}'. No one else will receive "
                       f"this until someone joins."}
            mset = set(members)
            unknown = [h for h in extract_mentions(text) if h != agent and h not in mset]
            if unknown:
                res = {**res, "unknown_mentions": unknown}
        return res

    @mcp.tool()
    async def poll_convs(conv: str | None = None, limit: int = 50,
                         only_new: bool = False) -> dict:
        """Unread messages across my conversations (or one), delivered once.

        Each room returns at most `limit` of its OLDEST unread messages; if a room has
        more, it carries "more": N (how many remain) and the next poll_convs gets the
        next batch. This keeps a busy backlog from overflowing the tool output. Raise
        `limit` for bigger batches, or pass limit=0 for no cap (use with care).

        only_new=True returns only messages the Stop-hook has NOT already delivered to
        this session (reads past the delivery cursor too), so a backlog you already
        received and acted on via the hook is not re-served. Use it for catch-up when
        the hook is your primary delivery path. The default (only_new=False) still
        returns everything since your last explicit read, hook deliveries included."""
        agent = _agent()
        err = await _room_error(conv, agent)
        if err:
            return err
        return {"conversations": await store.poll(agent, conv, box=current_box.get(),
                                                  limit=limit, only_new=only_new)}

    @mcp.tool()
    async def peek_convs(conv: str | None = None, limit: int = 50,
                         only_new: bool = False) -> dict:
        """Like poll_convs but read-only (does not advance the read cursor). Same
        per-room `limit`/"more" capping (limit=0 = no cap) and the same `only_new`
        option. A named room that does not exist, or that you have not joined, returns
        an explicit `error` (not an empty result)."""
        agent = _agent()
        err = await _room_error(conv, agent)
        if err:
            return err
        return {"conversations": await store.peek(agent, conv, box=current_box.get(),
                                                  limit=limit, only_new=only_new)}

    @mcp.tool()
    async def my_recent(conv: str, limit: int = 20) -> dict:
        """My own most-recent messages in a room, newest first. Use it after an
        ambiguous send (e.g. a 500/timeout) to see what actually landed before retrying,
        since peek_convs/poll_convs never return your own messages."""
        agent = _agent()
        err = await _room_error(conv, agent)
        if err:
            return err
        return {"messages": await store.recent(agent, conv, limit)}

    @mcp.tool()
    async def list_convs() -> dict:
        """My conversations with unread counts."""
        return {"conversations": await store.list_rooms(_agent(), box=current_box.get())}

    @mcp.tool()
    async def list_all_convs() -> dict:
        """Every conversation on the server (global directory, for discovery)."""
        _agent()  # require a valid identity
        return {"conversations": await store.all_rooms()}

    @mcp.tool()
    async def who(conv: str) -> dict:
        """List the members of a conversation."""
        _agent()
        return {"members": await store.members(conv)}

    app = IdentityMiddleware(mcp.streamable_http_app(), store, admin_token)
    app._mcp = mcp
    return app
