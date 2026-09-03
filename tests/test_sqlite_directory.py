import pytest
from parley.stores.sqlite import SqliteStore


@pytest.fixture
async def store():
    s = await SqliteStore.connect(":memory:")
    yield s
    await s.close()


async def test_list_rooms_unread_counts_exclude_self(store):
    await store.create_room("r", "alice"); await store.join("r", "bob")
    await store.say("r", "alice", "1"); await store.say("r", "alice", "2")
    await store.say("r", "bob", "mine")  # bob's own -> not counted for bob
    rooms = await store.list_rooms("bob", box=None)
    assert rooms == [{"conv": "r", "unread": 2}]

async def test_all_rooms_global_directory(store):
    await store.create_room("r", "alice", title="Room R"); await store.join("r", "bob")
    await store.say("r", "alice", "hi")
    d = await store.all_rooms()
    assert d == [{"conv": "r", "members": 2, "messages": 1, "title": "Room R"}]

async def test_box_rooms_aggregates_sessions(store):
    await store.create_room("r1", "work3")
    await store.create_room("r2", "work3-agent#1")
    await store.create_room("r3", "elitebook2")
    assert await store.box_rooms("work3") == ["r1", "r2"]
