from parley.core.identity import compose_agent_id


def _bearer(headers) -> str:
    auth = headers.get("authorization", "") or ""
    return auth[len("Bearer "):].strip() if auth.startswith("Bearer ") else ""


async def resolve_identity(store, headers, admin_token: str | None
                           ) -> tuple[str | None, str | None, bool]:
    """(agent_id, box, is_admin). Prefers a per-agent bearer token resolved to its
    box server-side (anti-spoof); the X-Parley-Box header is trusted only in the
    admin/open dev paths. Four branches, see plan Task 2."""
    handle = headers.get("x-parley-agent")
    bearer = _bearer(headers)
    if bearer:
        box = await store.box_for_token(bearer)
        if box:
            return compose_agent_id(box, handle), box, False
    if admin_token and bearer == admin_token:
        hbox = headers.get("x-parley-box")
        aid = compose_agent_id(hbox, handle) if hbox else (handle or None)
        return aid, hbox, True
    if not admin_token:
        hbox = headers.get("x-parley-box")
        aid = compose_agent_id(hbox, handle) if hbox else (handle or None)
        return aid, hbox, True
    return None, None, False
