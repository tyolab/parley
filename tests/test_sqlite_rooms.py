import pytest

from parley.stores.sqlite import SqliteStore


@pytest.fixture
async def store():
    s = await SqliteStore.connect(":memory:")
    yield s
    await s.close()


async def test_start_is_idempotent_and_joins_creator(store):
    r1 = await store.create_room("room1", "alice", title="Hi")
    assert r1 == {"created": True, "conv": "room1"}
    r2 = await store.create_room("room1", "bob")
    assert r2 == {"created": False, "conv": "room1"}
    assert set(await store.members("room1")) == {"alice", "bob"}

async def test_join_missing_room_reports_not_exists(store):
    assert await store.join("ghost", "alice") == {"joined": False, "exists": False}

async def test_join_existing_is_idempotent(store):
    await store.create_room("r", "alice")
    assert await store.join("r", "bob") == {"joined": True, "exists": True}
    assert await store.join("r", "bob") == {"joined": True, "exists": True}
    assert set(await store.members("r")) == {"alice", "bob"}

async def test_say_requires_membership(store):
    await store.create_room("r", "alice")
    res = await store.say("r", "stranger", "hello")
    assert res["ok"] is False and "member" in res["reason"]

async def test_say_appends_monotonic_ids(store):
    await store.create_room("r", "alice")
    a = await store.say("r", "alice", "one")
    b = await store.say("r", "alice", "two")
    assert a["ok"] and b["ok"] and b["id"] > a["id"]

async def test_is_member(store):
    await store.create_room("r", "alice")
    assert await store.is_member("r", "alice") is True
    assert await store.is_member("r", "bob") is False

async def test_leave(store):
    await store.create_room("r", "alice")
    await store.join("r", "bob")
    await store.leave("r", "bob")
    assert await store.is_member("r", "bob") is False
