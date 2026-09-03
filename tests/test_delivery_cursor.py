import pytest

from parley.stores.sqlite import SqliteStore


@pytest.fixture
async def store():
    s = await SqliteStore.connect(":memory:")
    yield s
    await s.close()


async def test_delivery_poll_does_not_move_interactive_cursor(store):
    await store.create_room("r", "work3")
    await store.join("r", "work3-agent#1")
    await store.join("r", "elitebook2")
    await store.say("r", "work3-agent#1", "same-box session msg")
    await store.say("r", "elitebook2", "other-box msg")
    d = await store.poll("work3", box="work3", box_view=True)
    assert [m["body"] for o in d for m in o["messages"]] == ["other-box msg"]
    i = await store.poll("work3", box="work3", box_view=False)
    assert sorted(m["body"] for o in i for m in o["messages"]) == \
        ["other-box msg", "same-box session msg"]

async def test_cursors_are_independent_both_directions(store):
    await store.create_room("r", "a")
    await store.join("r", "b")
    await store.say("r", "b", "m1")
    assert len(await store.poll("a", box=None, box_view=False)) == 1
    assert await store.poll("a", box=None, box_view=False) == []
    assert len(await store.poll("a", box=None, box_view=True)) == 1
    assert await store.poll("a", box=None, box_view=True) == []


async def test_connect_migrates_old_db_missing_delivery_column(tmp_path):
    # A DB created before the delivery cursor (no delivery_read_id) must be migrated
    # by connect(), not crash on the box_view delivery path.
    import aiosqlite
    p = str(tmp_path / "old.db")
    db = await aiosqlite.connect(p)
    await db.execute(
        "CREATE TABLE conv_members (conv_id TEXT NOT NULL, agent_id TEXT NOT NULL, "
        "joined_at TEXT NOT NULL, last_read_id INTEGER NOT NULL DEFAULT 0, "
        "PRIMARY KEY (conv_id, agent_id))")
    await db.commit()
    await db.close()
    s = await SqliteStore.connect(p)  # must ALTER-add delivery_read_id, not raise
    await s.create_room("r", "a")
    await s.join("r", "b")
    await s.say("r", "b", "hi")
    d = await s.poll("a", box=None, box_view=True)  # delivery path uses delivery_read_id
    assert [m["body"] for o in d for m in o["messages"]] == ["hi"]
    await s.close()
