import httpx


class Client:
    """Thin async SDK over the Parley REST gateway. `agent` is this client's handle
    (sent as X-Parley-Agent); `box` optionally sets X-Parley-Box; `token` sets the
    gateway bearer. Pass `_http` to inject a pre-built AsyncClient (used in tests)."""

    def __init__(self, base_url: str = "http://127.0.0.1:8790", agent: str = "",
                 box: str | None = None, token: str | None = None, _http=None):
        self.agent = agent
        headers = {}
        if agent:
            headers["X-Parley-Agent"] = agent
        if box:
            headers["X-Parley-Box"] = box
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._http = _http or httpx.AsyncClient(base_url=base_url)
        self._http.headers.update(headers)

    async def create_room(self, name: str, title: str | None = None) -> dict:
        return (await self._http.post("/rooms", json={"name": name, "title": title})).json()

    async def join(self, name: str) -> dict:
        return (await self._http.post(f"/rooms/{name}/join")).json()

    async def leave(self, name: str) -> dict:
        return (await self._http.post(f"/rooms/{name}/leave")).json()

    async def say(self, name: str, body: str, kind: str = "say") -> dict:
        return (await self._http.post(f"/rooms/{name}/messages",
                                      json={"body": body, "kind": kind})).json()

    async def members(self, name: str) -> list[str]:
        return (await self._http.get(f"/rooms/{name}/members")).json()["members"]

    async def poll(self, room: str | None = None) -> list[dict]:
        params = {"room": room} if room else None
        return (await self._http.get("/poll", params=params)).json()["conversations"]

    async def peek(self, room: str | None = None) -> list[dict]:
        params = {"room": room} if room else None
        return (await self._http.get("/peek", params=params)).json()["conversations"]

    async def deliver(self, room: str | None = None) -> list[dict]:
        """Catch-all delivery poll (box_view). Used by the Stop-hook / notifier."""
        params = {"room": room} if room else None
        return (await self._http.get("/deliver", params=params)).json()["conversations"]

    async def listen(self, transport, rooms, on_nudge):
        """Subscribe to each room's nudge topic; call on_nudge(signal) per nudge.
        Returns the list of subscriptions (close each to stop). Works with any
        Transport (FakeTransport in tests; tyo-mq/redis/nats in production)."""
        subs = []
        for room in rooms:
            subs.append(await transport.subscribe(room, on_nudge))
        return subs

    async def list_rooms(self) -> list[dict]:
        return (await self._http.get("/rooms")).json()["conversations"]

    async def all_rooms(self) -> list[dict]:
        return (await self._http.get("/rooms-all")).json()["conversations"]

    async def close(self) -> None:
        await self._http.aclose()
