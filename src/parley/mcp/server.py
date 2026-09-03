import contextvars

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
    async def say(conv: str, text: str) -> dict:
        """Post a message to a conversation I've joined."""
        return await store.say(conv, _agent(), text)

    @mcp.tool()
    async def poll_convs(conv: str | None = None) -> dict:
        """Unread messages across my conversations (or one), delivered once."""
        agent = _agent()
        if conv and not await store.is_member(conv, agent):
            return {"conversations": [], "error":
                    f"You are not a member of '{conv}' (or it does not exist). "
                    f"Use list_convs / list_all_convs, then join_conv."}
        return {"conversations": await store.poll(agent, conv, box=current_box.get())}

    @mcp.tool()
    async def peek_convs(conv: str | None = None) -> dict:
        """Like poll_convs but read-only (does not advance the read cursor)."""
        return {"conversations": await store.peek(_agent(), conv, box=current_box.get())}

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
