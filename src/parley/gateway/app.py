import asyncio
import datetime
import hmac
import re

from fastapi import FastAPI, HTTPException, Request

from parley.core.store import extract_mentions
from parley.gateway.identity import _bearer, resolve_identity

_BOX_RE = r"[A-Za-z0-9._-]+"

# Default per-room message cap for the read endpoints, so one busy room's backlog
# can't overflow a caller's output budget. A caller can override with ?limit=N
# (limit=0 means "no cap"). See store._collect for the drain-oldest/"more" semantics.
DEFAULT_POLL_LIMIT = 50


def build_app(store, transport, admin_token: str | None = None,
              *, token: str | None = None,
              join_code: str | None = None, mcp_port: int | None = None) -> FastAPI:
    # `token=` is a back-compat alias for the Plan-1 shared-secret parameter.
    admin_token = admin_token if admin_token is not None else token
    app = FastAPI(title="Parley")

    async def _identify(request: Request):
        agent_id, box, is_admin = await resolve_identity(store, request.headers, admin_token)
        if agent_id is None:
            if admin_token and not is_admin:
                raise HTTPException(status_code=401, detail="missing/invalid token")
            # Room operations always need a concrete agent identity, even for an admin
            # caller. Admin-only, agent-agnostic endpoints (e.g. minting) resolve
            # identity themselves and must NOT go through _identify.
            raise HTTPException(status_code=400, detail="no agent identity (set X-Parley-Agent)")
        return agent_id, box, is_admin

    def _str_field(payload: dict, key: str, *, required: bool = True,
                   nonblank: bool = False) -> str | None:
        val = payload.get(key)
        if val is None:
            if required:
                raise HTTPException(status_code=400, detail=f"missing '{key}'")
            return None
        if not isinstance(val, str):
            raise HTTPException(status_code=400, detail=f"'{key}' must be a string")
        if nonblank and not val.strip():
            raise HTTPException(status_code=400, detail=f"'{key}' must not be blank")
        return val

    # Background nudge tasks are tracked so they are not garbage-collected mid-flight.
    _nudge_tasks: set = set()

    def _spawn_nudge(topic, signal):
        """Fire-and-forget the push nudge with a hard timeout. Never awaited by the
        request, so a slow/stuck/erroring transport cannot delay or fail a say."""
        async def _run():
            try:
                await asyncio.wait_for(transport.publish(topic, signal), timeout=3.0)
            except Exception:  # noqa: BLE001, S110 - nudge is best-effort
                pass
        t = asyncio.create_task(_run())
        _nudge_tasks.add(t)
        t.add_done_callback(_nudge_tasks.discard)

    @app.get("/healthz")
    async def healthz():
        return {"ok": True}

    @app.post("/admin/agents")
    async def mint_agent(request: Request, payload: dict):
        # Minting is admin-only but agent-agnostic: resolve identity directly (an
        # admin caller need not carry an X-Parley-Agent handle) rather than via
        # _identify, which requires a concrete agent identity.
        _aid, _box, is_admin = await resolve_identity(store, request.headers, admin_token)
        if not is_admin:
            raise HTTPException(status_code=403, detail="admin only")
        if not admin_token:
            # In open-dev mode (no shared secret) everyone is 'admin'; refuse to mint
            # so tokens can't be created now and silently survive a later lock-down.
            raise HTTPException(status_code=403,
                                detail="minting disabled in open mode (start with --token)")
        box = _str_field(payload, "box", nonblank=True)
        if not re.fullmatch(_BOX_RE, box):
            # A box is a machine id. Reject '#'/spaces so a minted box can never equal
            # a composed session handle (e.g. 'work3-agent#1') and impersonate it.
            raise HTTPException(status_code=400,
                                detail="box must match [A-Za-z0-9._-] (no '#' or spaces)")
        label = _str_field(payload, "label", required=False)
        token = await store.mint_agent_token(box, label)
        return {"token": token, "box": box}

    @app.post("/enroll")
    async def enroll(request: Request, payload: dict):
        # Self-serve enrollment: a box claims itself with the shared join code and
        # gets a per-agent token in one call. This is the token-tier middle ground
        # between open (no token) and admin-only minting. Anti-spoof is preserved by
        # the first-come claim below: only an unclaimed box may self-enroll.
        if not join_code:
            raise HTTPException(status_code=403,
                                detail="enrollment disabled (set PARLEY_JOIN_CODE)")
        supplied = _bearer(request.headers)
        if not hmac.compare_digest(supplied, join_code):
            # Constant-time compare so a wrong code leaks no timing signal.
            raise HTTPException(status_code=403, detail="invalid join code")
        box = _str_field(payload, "box", nonblank=True)
        if not re.fullmatch(_BOX_RE, box):
            raise HTTPException(status_code=400,
                                detail="box must match [A-Za-z0-9._-] (no '#' or spaces)")
        if await store.box_has_token(box):
            # First-come claim: a box that already has any token can only be re-issued
            # by an admin (via /admin/agents). This stops a leaked join code from
            # minting a second token for an existing box and impersonating it.
            raise HTTPException(
                status_code=409,
                detail=f"box '{box}' is already enrolled; ask an admin to rotate its token")
        label = _str_field(payload, "label", required=False)
        token = await store.mint_agent_token(box, label)
        return {"token": token, "box": box, "mcp_port": mcp_port}

    @app.post("/rooms")
    async def create_room(request: Request, payload: dict):
        agent_id, _box, _is_admin = await _identify(request)
        name = _str_field(payload, "name", nonblank=True)
        title = _str_field(payload, "title", required=False)
        return await store.create_room(name, agent_id, title)

    @app.post("/rooms/{name}/join")
    async def join(request: Request, name: str):
        agent_id, _box, _is_admin = await _identify(request)
        return await store.join(name, agent_id)

    @app.post("/rooms/{name}/leave")
    async def leave(request: Request, name: str):
        agent_id, _box, _is_admin = await _identify(request)
        return await store.leave(name, agent_id)

    @app.post("/rooms/{name}/messages")
    async def say(request: Request, name: str, payload: dict):
        agent_id, _box, _is_admin = await _identify(request)
        body = _str_field(payload, "body")
        # join=true: join-and-send in one call for a room the sender isn't in yet.
        if payload.get("join") and not await store.is_member(name, agent_id):
            j = await store.join(name, agent_id)
            if not j.get("exists"):
                return {"ok": False, "reason":
                        f"No conversation named '{name}' exists; cannot join. Create it first."}
        res = await store.say(name, agent_id, body, payload.get("kind", "say"))
        if res.get("ok"):
            # Fire-and-forget the push nudge: schedule it so a slow or stuck transport
            # can never delay or fail the response. The row is already committed, so a
            # nudge that errors/hangs must not turn a successful send into an ambiguous
            # 500 (which is what made a retry's safety unknowable).
            at = datetime.datetime.now(datetime.UTC).isoformat()
            _spawn_nudge(name, {"room": name, "from": agent_id, "at": at})
            members = await store.members(name)
            # Warn a sender who is alone in the room: the message is stored but nobody
            # else will receive it. A send into the void is otherwise invisible.
            if not [m for m in members if m != agent_id]:
                res = {**res, "warning":
                       f"You are the only member of '{name}'. No one else will receive "
                       f"this until someone joins."}
            # Flag @mentions of agents who are NOT in this room: the message posted, but
            # the person it was addressed to will never receive it (the mention-to-a-
            # non-member failure that a healthy member count does not catch).
            mset = set(members)
            unknown = [h for h in extract_mentions(body) if h != agent_id and h not in mset]
            if unknown:
                res = {**res, "unknown_mentions": unknown}
        return res

    @app.get("/rooms/{name}/members")
    async def members(request: Request, name: str):
        await _identify(request)
        return {"members": await store.members(name)}

    @app.get("/rooms/{name}/mine")
    async def mine(request: Request, name: str, limit: int = 20):
        # Read back my OWN recent messages in a room, so after an ambiguous send error
        # I can see what actually landed before deciding to retry (peek/poll never
        # return my own messages).
        agent_id, _box, _is_admin = await _identify(request)
        block = await _room_block(agent_id, name)
        if block:
            return block
        return {"messages": await store.recent(agent_id, name, limit)}

    async def _room_block(agent_id, room):
        """For a NAMED read: an error payload if the room is unknown or the caller is
        not a member (distinguishing the two), else None. So a named poll/peek says
        "no such room" vs "join first" instead of an empty result that looks the same
        as "nothing unread"."""
        if not room:
            return None
        if await store.get_room(room) is None:
            return {"conversations": [],
                    "error": f"No conversation named '{room}' exists. "
                             f"Use /rooms-all to list rooms, or create it first."}
        if not await store.is_member(room, agent_id):
            return {"conversations": [],
                    "error": f"You are not a member of '{room}'. Join it first."}
        return None

    @app.get("/poll")
    async def poll(request: Request, room: str | None = None, limit: int | None = None,
                   only_new: bool = False):
        agent_id, box, _is_admin = await _identify(request)
        block = await _room_block(agent_id, room)
        if block:
            return block
        lim = DEFAULT_POLL_LIMIT if limit is None else limit
        return {"conversations": await store.poll(agent_id, room, box=box, limit=lim,
                                                  only_new=only_new)}

    @app.get("/deliver")
    async def deliver(request: Request, room: str | None = None, limit: int | None = None):
        agent_id, box, _is_admin = await _identify(request)
        lim = DEFAULT_POLL_LIMIT if limit is None else limit
        return {"conversations": await store.poll(agent_id, room, box=box,
                                                  box_view=True, limit=lim)}

    @app.get("/peek")
    async def peek(request: Request, room: str | None = None, limit: int | None = None,
                   only_new: bool = False):
        agent_id, box, _is_admin = await _identify(request)
        block = await _room_block(agent_id, room)
        if block:
            return block
        lim = DEFAULT_POLL_LIMIT if limit is None else limit
        return {"conversations": await store.peek(agent_id, room, box=box, limit=lim,
                                                  only_new=only_new)}

    @app.get("/rooms")
    async def list_rooms(request: Request):
        agent_id, box, _is_admin = await _identify(request)
        return {"conversations": await store.list_rooms(agent_id, box=box)}

    @app.get("/rooms-all")
    async def all_rooms(request: Request):
        await _identify(request)
        return {"conversations": await store.all_rooms()}

    return app
