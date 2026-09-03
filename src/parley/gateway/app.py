import datetime

from fastapi import FastAPI, HTTPException, Request

from parley.gateway.identity import resolve_identity


def build_app(store, transport, admin_token: str | None = None,
              *, token: str | None = None) -> FastAPI:
    # `token=` is a back-compat alias for the Plan-1 shared-secret parameter.
    admin_token = admin_token if admin_token is not None else token
    app = FastAPI(title="Parley")

    async def _identify(request: Request):
        agent_id, box, is_admin = await resolve_identity(store, request.headers, admin_token)
        if agent_id is None:
            if admin_token and not is_admin:
                raise HTTPException(status_code=401, detail="missing/invalid token")
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

    @app.get("/healthz")
    async def healthz():
        return {"ok": True}

    @app.post("/rooms")
    async def create_room(request: Request, payload: dict):
        agent_id, box, _is_admin = await _identify(request)
        name = _str_field(payload, "name", nonblank=True)
        title = _str_field(payload, "title", required=False)
        return await store.create_room(name, agent_id, title)

    @app.post("/rooms/{name}/join")
    async def join(request: Request, name: str):
        agent_id, box, _is_admin = await _identify(request)
        return await store.join(name, agent_id)

    @app.post("/rooms/{name}/leave")
    async def leave(request: Request, name: str):
        agent_id, box, _is_admin = await _identify(request)
        return await store.leave(name, agent_id)

    @app.post("/rooms/{name}/messages")
    async def say(request: Request, name: str, payload: dict):
        agent_id, box, _is_admin = await _identify(request)
        body = _str_field(payload, "body")
        res = await store.say(name, agent_id, body, payload.get("kind", "say"))
        if res.get("ok"):
            at = datetime.datetime.now(datetime.UTC).isoformat()
            try:
                await transport.publish(name, {"room": name, "from": agent_id, "at": at})
            except Exception:  # noqa: BLE001, S110 - nudge is best-effort
                pass
        return res

    @app.get("/rooms/{name}/members")
    async def members(request: Request, name: str):
        await _identify(request)
        return {"members": await store.members(name)}

    @app.get("/poll")
    async def poll(request: Request, room: str | None = None):
        agent_id, box, _is_admin = await _identify(request)
        if room and not await store.is_member(room, agent_id):
            return {"conversations": [],
                    "error": f"You are not a member of '{room}' (or it does not exist). "
                             f"Use /rooms or list to find the right room, then join."}
        return {"conversations": await store.poll(agent_id, room, box=box)}

    @app.get("/peek")
    async def peek(request: Request, room: str | None = None):
        agent_id, box, _is_admin = await _identify(request)
        return {"conversations": await store.peek(agent_id, room, box=box)}

    @app.get("/rooms")
    async def list_rooms(request: Request):
        agent_id, box, _is_admin = await _identify(request)
        return {"conversations": await store.list_rooms(agent_id, box=box)}

    @app.get("/rooms-all")
    async def all_rooms(request: Request):
        await _identify(request)
        return {"conversations": await store.all_rooms()}

    return app
