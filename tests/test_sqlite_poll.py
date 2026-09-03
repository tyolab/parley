import pytest

from parley.stores.sqlite import SqliteStore


@pytest.fixture
async def store():
    s = await SqliteStore.connect(":memory:")
    yield s
    await s.close()


async def test_poll_returns_others_messages_and_advances_cursor(store):
    await store.create_room("r", "alice")
    await store.join("r", "bob")
    await store.say("r", "alice", "hello bob")
    out = await store.poll("bob", box=None)
    assert out == [{"conv": "r", "messages": [
        {"from": "alice", "body": "hello bob", "at": out[0]["messages"][0]["at"]}]}]
    # cursor advanced -> second poll is empty
    assert await store.poll("bob", box=None) == []

async def test_poll_excludes_my_own_messages(store):
    await store.create_room("r", "alice")
    await store.say("r", "alice", "to nobody")
    assert await store.poll("alice", box=None) == []

async def test_peek_does_not_advance_cursor(store):
    await store.create_room("r", "alice")
    await store.join("r", "bob")
    await store.say("r", "alice", "hi")
    assert len((await store.peek("bob"))[0]["messages"]) == 1
    # peek twice -> still there
    assert len((await store.peek("bob"))[0]["messages"]) == 1
    # poll then sees it once
    assert len((await store.poll("bob"))[0]["messages"]) == 1

async def test_poll_single_room_filter(store):
    await store.create_room("r1", "alice"); await store.join("r1", "bob")
    await store.create_room("r2", "alice"); await store.join("r2", "bob")
    await store.say("r1", "alice", "in r1")
    await store.say("r2", "alice", "in r2")
    out = await store.poll("bob", room="r1")
    assert [o["conv"] for o in out] == ["r1"]

async def test_bare_box_hears_own_sessions_by_default(store):
    # CORRECTED semantics: distinct identities hear each other, so bare-box 'work3'
    # DOES hear its same-box session by default (box_view defaults False).
    await store.create_room("r", "work3")
    await store.join("r", "work3-agent-antelope#1")
    await store.say("r", "work3-agent-antelope#1", "hi from a same-box session")
    out = await store.poll("work3", box="work3")
    assert [m["body"] for o in out for m in o["messages"]] == ["hi from a same-box session"]

async def test_session_hears_sibling_and_bare_box(store):
    await store.create_room("r", "work3-agent#1")
    await store.join("r", "work3-agent#2")
    await store.join("r", "work3")
    await store.say("r", "work3", "bare box — now heard (distinct identity)")
    await store.say("r", "work3-agent#2", "sibling session — heard")
    out = await store.poll("work3-agent#1", box="work3")
    bodies = sorted(m["body"] for o in out for m in o["messages"])
    assert bodies == ["bare box — now heard (distinct identity)", "sibling session — heard"]

async def test_box_view_suppresses_own_sessions_for_delivery(store):
    # The Layer-1 catch-all delivery mode opts into box_view=True: the bare box then
    # suppresses its own '<box>-*' sessions, while still hearing OTHER boxes.
    await store.create_room("r", "work3")
    await store.join("r", "work3-agent#1")
    await store.join("r", "elitebook2")
    await store.say("r", "work3-agent#1", "my own session — suppressed in box_view")
    await store.say("r", "elitebook2", "another box — still delivered")
    out = await store.poll("work3", box="work3", box_view=True)
    assert [m["body"] for o in out for m in o["messages"]] == ["another box — still delivered"]
    # exact-self is always excluded, even in box_view
    await store.say("r", "work3", "my own bare-box message")
    assert await store.peek("work3", box="work3", box_view=True) == []
