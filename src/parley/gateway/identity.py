from parley.core.identity import compose_agent_id


def resolve_identity(headers) -> tuple[str | None, str | None]:
    """(agent_id, box) for a request. MVP: box comes from the trusted X-Parley-Box
    header (LAN tool, guarded by the optional shared token); handle from
    X-Parley-Agent. If a box is present, the effective id is the anti-spoof
    compose_agent_id(box, handle); otherwise the handle stands alone as a bare id.
    A later plan replaces this with per-agent bearer-token resolution."""
    handle = headers.get("x-parley-agent")
    box = headers.get("x-parley-box")
    if box:
        return compose_agent_id(box, handle), box
    return (handle or None), None
