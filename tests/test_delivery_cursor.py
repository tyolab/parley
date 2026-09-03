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
