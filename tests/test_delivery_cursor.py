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

async def test_session_handle_delivery_no_theft_no_echo(store):
    # A per-session handle (agent_id != box) now has an independent delivery cursor,
    # coupled ASYMMETRICALLY so the Stop-hook (/deliver=box_view) and the agent's own
    # interactive poll never starve each other, yet the hook still never echoes a
    # message the session already read:
    #   - hook delivery advances ONLY delivery_read_id -> it can't consume a peer
    #     message out from under the interactive poll (the reach-apple stall).
    #   - interactive poll advances BOTH cursors -> the hook won't re-notify a
    #     message the session already read explicitly (the engage-mode echo/loop).
    await store.create_room("r", "work3-agent#1")
    await store.join("r", "work3-agent#2")
    await store.say("r", "work3-agent#2", "m1")
    # deliver (box_view=True) as the session handle surfaces m1 via the hook...
    d = await store.poll("work3-agent#1", box="work3", box_view=True)
    assert [m["body"] for o in d for m in o["messages"]] == ["m1"]
    # ...and the interactive poll STILL sees m1 (no theft): the hook only touched
    # the delivery cursor, not the read cursor the agent's poll_convs depends on.
    i = await store.poll("work3-agent#1", box="work3", box_view=False)
    assert [m["body"] for o in i for m in o["messages"]] == ["m1"]
    # that interactive read advanced both cursors, so the hook won't re-notify m1.
    assert await store.poll("work3-agent#1", box="work3", box_view=True) == []
    # reverse direction: interactive read of a new message then delivery must dedupe.
    await store.say("r", "work3-agent#2", "m2")
    i2 = await store.poll("work3-agent#1", box="work3", box_view=False)
    assert [m["body"] for o in i2 for m in o["messages"]] == ["m2"]
    assert await store.poll("work3-agent#1", box="work3", box_view=True) == []


async def test_hook_delivery_does_not_starve_interactive_poll(store):
    # Regression for the reach-apple live stall: two handled peers on different boxes,
    # each with the box-wide engage Stop-hook installed. The hook (box_view=True)
    # firing on every turn must NOT consume the peer message the agent reads via its
    # own interactive poll_convs — otherwise both sides poll and see nothing and the
    # conversation deadlocks even though delivery "happened".
    await store.create_room("reach-apple", "devmac-reach-mac")
    await store.join("reach-apple", "work3-agent-reach#4")
    await store.say("reach-apple", "work3-agent-reach#4", "hello from work3")
    # devmac's Stop-hook fires first and delivers the message...
    h = await store.poll("devmac-reach-mac", box="devmac", box_view=True)
    assert [m["body"] for o in h for m in o["messages"]] == ["hello from work3"]
    # ...devmac's agent then explicitly polls and STILL receives it (was: empty).
    p = await store.poll("devmac-reach-mac", box="devmac", box_view=False)
    assert [m["body"] for o in p for m in o["messages"]] == ["hello from work3"]


async def test_only_new_skips_hook_delivered_backlog_and_dedupes(store):
    # A hook-driven session: the Stop-hook (box_view) delivers a backlog, then the
    # session catches up with poll(only_new=True), which must NOT re-serve what the hook
    # already gave it (reads past the delivery cursor too) — unlike the DEFAULT poll,
    # which still returns everything (the no-theft invariant, covered above).
    await store.create_room("r", "work3-agent#1")
    await store.join("r", "work3-agent#2")
    await store.say("r", "work3-agent#2", "m1")
    await store.say("r", "work3-agent#2", "m2")
    d = await store.poll("work3-agent#1", box="work3", box_view=True)  # hook delivers
    assert [m["body"] for o in d for m in o["messages"]] == ["m1", "m2"]
    # only_new: the hook already delivered m1,m2 -> nothing new to catch up on
    assert await store.poll("work3-agent#1", box="work3", box_view=False,
                            only_new=True) == []
    # a genuinely new message -> only_new returns just it, and advances BOTH cursors
    await store.say("r", "work3-agent#2", "m3")
    i = await store.poll("work3-agent#1", box="work3", box_view=False, only_new=True)
    assert [m["body"] for o in i for m in o["messages"]] == ["m3"]
    # so the hook won't re-deliver m3 either (only_new advanced the delivery cursor)
    assert await store.poll("work3-agent#1", box="work3", box_view=True) == []


async def test_default_poll_still_reserves_hook_delivered_no_theft(store):
    # Guard: the DEFAULT (only_new=False) is unchanged — after the hook delivers m1,
    # the interactive poll STILL returns it. only_new must be strictly opt-in.
    await store.create_room("r", "work3-agent#1")
    await store.join("r", "work3-agent#2")
    await store.say("r", "work3-agent#2", "m1")
    assert len(await store.poll("work3-agent#1", box="work3", box_view=True)) == 1
    i = await store.poll("work3-agent#1", box="work3", box_view=False)  # default
    assert [m["body"] for o in i for m in o["messages"]] == ["m1"]


async def test_bare_box_catchall_cursor_is_independent(store):
    # The bare-box catch-all (agent_id == box) keeps a delivery cursor independent
    # from the interactive cursor: it can share a conv_members row with a
    # handle-less MCP session, so the two paths must not consume each other.
    await store.create_room("r", "work3")
    await store.join("r", "elitebook2")
    await store.say("r", "elitebook2", "m1")
    assert len(await store.poll("work3", box="work3", box_view=True)) == 1
    assert await store.poll("work3", box="work3", box_view=True) == []
    # the interactive cursor was untouched by the delivery poll above
    assert len(await store.poll("work3", box="work3", box_view=False)) == 1
    assert await store.poll("work3", box="work3", box_view=False) == []


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
