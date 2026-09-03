import datetime
from fastapi import FastAPI, Request, HTTPException
from parley.gateway.identity import resolve_identity


def build_app(store, transport, token: str | None = None) -> FastAPI:
    app = FastAPI(title="Parley")

    def _auth(request: Request):
        if token:
            got = request.headers.get("authorization", "")
            if got != f"Bearer {token}":
                raise HTTPException(status_code=401, detail="missing/invalid gateway token")

    def _ident(request: Request):
        agent_id, box = resolve_identity(request.headers)
        if not agent_id:
            raise HTTPException(status_code=400, detail="no agent identity (set X-Parley-Agent)")
        return agent_id, box

    @app.get("/healthz")
    async def healthz():
        return {"ok": True}

    @app.post("/rooms")
    async def create_room(request: Request, payload: dict):
        _auth(request); agent_id, _ = _ident(request)
        return await store.create_room(payload["name"], agent_id, payload.get("title"))

    @app.post("/rooms/{name}/join")
    async def join(request: Request, name: str):
        _auth(request); agent_id, _ = _ident(request)
        return await store.join(name, agent_id)

    @app.post("/rooms/{name}/leave")
    async def leave(request: Request, name: str):
        _auth(request); agent_id, _ = _ident(request)
        return await store.leave(name, agent_id)

    @app.post("/rooms/{name}/messages")
    async def say(request: Request, name: str, payload: dict):
        _auth(request); agent_id, _ = _ident(request)
        res = await store.say(name, agent_id, payload["body"], payload.get("kind", "say"))
        if res.get("ok"):
            at = datetime.datetime.now(datetime.timezone.utc).isoformat()
            try:
                await transport.publish(name, {"room": name, "from": agent_id, "at": at})
            except Exception:
                pass  # nudge is best-effort
        return res

    @app.get("/rooms/{name}/members")
    async def members(request: Request, name: str):
        _auth(request); _ident(request)
        return {"members": await store.members(name)}

    @app.get("/poll")
    async def poll(request: Request, room: str | None = None):
        _auth(request); agent_id, box = _ident(request)
        if room and not await store.is_member(room, agent_id):
            return {"conversations": [],
                    "error": f"You are not a member of '{room}' (or it does not exist). "
                             f"Use /rooms or list to find the right room, then join."}
        return {"conversations": await store.poll(agent_id, room, box=box)}

    @app.get("/peek")
    async def peek(request: Request, room: str | None = None):
        _auth(request); agent_id, box = _ident(request)
        return {"conversations": await store.peek(agent_id, room, box=box)}

    @app.get("/rooms")
    async def list_rooms(request: Request):
        _auth(request); agent_id, box = _ident(request)
        return {"conversations": await store.list_rooms(agent_id, box=box)}

    @app.get("/rooms-all")
    async def all_rooms(request: Request):
        _auth(request); _ident(request)
        return {"conversations": await store.all_rooms()}

    return app
