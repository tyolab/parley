import httpx
import pytest

from parley.gateway.app import build_app
from parley.stores.sqlite import SqliteStore
from parley.transports.polling import PollingTransport


@pytest.fixture
async def client():
    store = await SqliteStore.connect(":memory:")
    app = build_app(store, PollingTransport())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        c.headers["X-Parley-Agent"] = "alice"
        yield c
    await store.close()


def bob_headers():
    return {"X-Parley-Agent": "bob"}


async def test_healthz(client):
    r = await client.get("/healthz")
    assert r.status_code == 200 and r.json()["ok"] is True

async def test_full_room_flow(client):
    assert (await client.post("/rooms", json={"name": "r"})).json() == {"created": True, "conv": "r"}
    r = await client.post("/rooms/r/join", headers=bob_headers())
    assert r.json() == {"joined": True, "exists": True}
    assert (await client.post("/rooms/r/messages", json={"body": "hi bob"})).json()["ok"] is True
    poll = await client.get("/poll", headers=bob_headers())
    convs = poll.json()["conversations"]
    assert convs[0]["conv"] == "r" and convs[0]["messages"][0]["body"] == "hi bob"

async def test_say_to_unjoined_room_reports_reason(client):
    await client.post("/rooms", json={"name": "r"})
    r = await client.post("/rooms/r/messages", json={"body": "x"}, headers=bob_headers())
    assert r.json()["ok"] is False

async def test_poll_named_unjoined_room_returns_error_not_empty(client):
    await client.post("/rooms", json={"name": "r"})
    r = await client.get("/poll", params={"room": "r"}, headers=bob_headers())
    body = r.json()
    assert body["conversations"] == [] and "error" in body

async def test_members_and_who(client):
    await client.post("/rooms", json={"name": "r"})
    await client.post("/rooms/r/join", headers=bob_headers())
    r = await client.get("/rooms/r/members")
    assert set(r.json()["members"]) == {"alice", "bob"}

async def test_create_room_missing_name_is_400(client):
    assert (await client.post("/rooms", json={})).status_code == 400

async def test_create_room_blank_name_is_400(client):
    assert (await client.post("/rooms", json={"name": "   "})).status_code == 400

async def test_create_room_nonstring_name_is_400(client):
    assert (await client.post("/rooms", json={"name": 123})).status_code == 400

async def test_say_missing_body_is_400(client):
    await client.post("/rooms", json={"name": "r"})
    assert (await client.post("/rooms/r/messages", json={})).status_code == 400


@pytest.mark.asyncio
async def test_token_required_when_configured():
    store = await SqliteStore.connect(":memory:")
    app = build_app(store, PollingTransport(), token="s3cret")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        assert (await c.get("/poll", headers={"X-Parley-Agent": "a"})).status_code == 401
        ok = await c.get("/poll", headers={"X-Parley-Agent": "a", "Authorization": "Bearer s3cret"})
        assert ok.status_code == 200
    await store.close()
