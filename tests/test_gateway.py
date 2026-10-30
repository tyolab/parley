import httpx
import pytest

from parley.core.store import extract_mentions
from parley.gateway.app import build_app
from parley.stores.sqlite import SqliteStore
from parley.transports.polling import PollingTransport


def test_extract_mentions_basics():
    assert extract_mentions("hi @alice and @bob-x#2, see @alice again") == ["alice", "bob-x#2"]
    assert extract_mentions("email foo@bar.com is not a mention") == []
    assert extract_mentions("@devmac-reach-ios: build it.") == ["devmac-reach-ios"]
    assert extract_mentions("") == []


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

async def test_poll_unknown_room_errors_no_such_room(client):
    r = await client.get("/poll", params={"room": "ghost"})
    body = r.json()
    assert body["conversations"] == []
    assert "No conversation named 'ghost'" in body["error"]

async def test_peek_unknown_room_errors_not_empty(client):
    r = await client.get("/peek", params={"room": "ghost"})
    body = r.json()
    assert body["conversations"] == []
    assert "No conversation named 'ghost'" in body["error"]

async def test_peek_unjoined_existing_room_errors_join_first(client):
    await client.post("/rooms", json={"name": "r"})  # alice creates + joins
    r = await client.get("/peek", params={"room": "r"}, headers=bob_headers())
    body = r.json()
    assert body["conversations"] == []
    assert "not a member" in body["error"].lower()

async def test_say_alone_in_room_warns_sender(client):
    await client.post("/rooms", json={"name": "solo"})  # alice is the only member
    r = await client.post("/rooms/solo/messages", json={"body": "anyone?"})
    body = r.json()
    assert body["ok"] is True
    assert "only member" in body.get("warning", "")

async def test_say_with_other_members_has_no_warning(client):
    await client.post("/rooms", json={"name": "r"})
    await client.post("/rooms/r/join", headers=bob_headers())
    r = await client.post("/rooms/r/messages", json={"body": "hi bob"})
    body = r.json()
    assert body["ok"] is True
    assert "warning" not in body

async def test_say_flags_unknown_mention_of_non_member(client):
    await client.post("/rooms", json={"name": "r"})           # alice creates + joins
    await client.post("/rooms/r/join", headers=bob_headers())  # bob joins
    r = await client.post("/rooms/r/messages", json={"body": "@carol please take this"})
    body = r.json()
    assert body["ok"] is True
    assert body["unknown_mentions"] == ["carol"]

async def test_say_mention_of_member_not_flagged(client):
    await client.post("/rooms", json={"name": "r"})
    await client.post("/rooms/r/join", headers=bob_headers())
    r = await client.post("/rooms/r/messages", json={"body": "@bob over to you"})
    body = r.json()
    assert body["ok"] is True
    assert "unknown_mentions" not in body

async def test_say_join_true_joins_and_sends(client):
    await client.post("/rooms", json={"name": "r"})  # alice is a member; bob is not
    r = await client.post("/rooms/r/messages",
                          json={"body": "hi from bob", "join": True}, headers=bob_headers())
    assert r.json()["ok"] is True
    m = await client.get("/rooms/r/members")
    assert "bob" in set(m.json()["members"])

async def test_say_join_true_nonexistent_room_fails(client):
    r = await client.post("/rooms/ghost/messages",
                          json={"body": "x", "join": True}, headers=bob_headers())
    body = r.json()
    assert body["ok"] is False and "cannot join" in body["reason"]

async def test_mine_returns_own_messages_newest_first(client):
    await client.post("/rooms", json={"name": "r"})
    await client.post("/rooms/r/messages", json={"body": "first"})
    await client.post("/rooms/r/messages", json={"body": "second"})
    r = await client.get("/rooms/r/mine")
    assert [m["body"] for m in r.json()["messages"]] == ["second", "first"]

async def test_mine_excludes_other_agents(client):
    await client.post("/rooms", json={"name": "r"})
    await client.post("/rooms/r/join", headers=bob_headers())
    await client.post("/rooms/r/messages", json={"body": "from alice"})
    await client.post("/rooms/r/messages", json={"body": "from bob"}, headers=bob_headers())
    r = await client.get("/rooms/r/mine")  # alice's own only
    assert [m["body"] for m in r.json()["messages"]] == ["from alice"]

async def test_mine_unknown_room_errors(client):
    r = await client.get("/rooms/ghost/mine")
    assert "No conversation named 'ghost'" in r.json().get("error", "")

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
