import re
from typing import Callable


def compose_agent_id(box: str | None, handle: str | None) -> str | None:
    """Compose the effective agent identity from an authenticated box id and an
    optional client-supplied handle. Anti-spoof: a handle is honored only when it
    equals `box` or starts with `box + '-'` (the '-' separator prevents a
    prefix-collision like box 'work3' honoring 'work300-evil'). Otherwise the bare
    box id is used. Returns None if there is no authenticated box."""
    if not box:
        return None
    if handle:
        h = handle.strip()
        if h == box or h.startswith(box + "-"):
            return h
    return box


def slugify_name(name: str | None) -> str:
    """Sanitize a requested session name to a safe slug ([A-Za-z0-9._-], <=32 chars),
    or '' for a missing/blank/punctuation-only name."""
    if name is None:
        return ""
    return re.sub(r"[^A-Za-z0-9._-]+", "-", str(name)).strip("-")[:32].strip("-")


def next_handle(box: str, name: str | None, bump: Callable[[str, str], int]) -> str:
    """Allocate a distinct per-session identity for a box, numbered by a monotonic
    counter keyed on (box, slug(name)). `bump(box, slug) -> n` is the caller-supplied
    counter (the store, in production). no name -> '<box>-agent#<n>'; name X ->
    '<box>-agent-<slug(X)>#<n>'."""
    slug = slugify_name(name)
    n = bump(box, slug)
    stem = f"{box}-agent-{slug}" if slug else f"{box}-agent"
    return f"{stem}#{n}"
