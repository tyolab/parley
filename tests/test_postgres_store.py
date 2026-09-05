import pytest

from tests.pg_util import fresh_store

pytestmark = pytest.mark.asyncio


async def test_rooms_membership_say():
    s = await fresh_store()
    try:
        assert await s.create_room("r", "alice", title="Hi") == {"created": True, "conv": "r"}
        assert await s.create_room("r", "bob") == {"created": False, "conv": "r"}
        assert set(await s.members("r")) == {"alice", "bob"}
        assert await s.join("ghost", "x") == {"joined": False, "exists": False}
        assert (await s.say("r", "stranger", "no"))["ok"] is False
        a = await s.say("r", "alice", "one"); b = await s.say("r", "alice", "two")
        assert a["ok"] and b["id"] > a["id"]
        assert await s.is_member("r", "alice") is True
        await s.leave("r", "bob")
        assert await s.is_member("r", "bob") is False
    finally:
        await s.close()


async def test_tokens_and_seq():
    s = await fresh_store()
    try:
        t1 = await s.mint_agent_token("work3"); t2 = await s.mint_agent_token("work3")
        assert t1 != t2
        assert await s.box_for_token(t1) == "work3"
        assert await s.box_for_token("nope") is None
        assert await s.next_agent_seq("work3", "") == 1
        assert await s.next_agent_seq("work3", "") == 2
        assert await s.box_has_token("work3") is True   # claimed by t1/t2 above
        assert await s.box_has_token("neverseen") is False
    finally:
        await s.close()


async def test_poll_cursor_and_delivery_independence():
    s = await fresh_store()
    try:
        await s.create_room("r", "work3")
        await s.join("r", "work3-agent#1")
        await s.join("r", "elitebook2")
        await s.say("r", "work3-agent#1", "same-box session")
        await s.say("r", "elitebook2", "other box")
        i = await s.poll("work3", box="work3", box_view=False)
        assert sorted(m["body"] for o in i for m in o["messages"]) == \
            ["other box", "same-box session"]
        assert await s.poll("work3", box="work3", box_view=False) == []
        d = await s.poll("work3", box="work3", box_view=True)
        assert [m["body"] for o in d for m in o["messages"]] == ["other box"]
    finally:
        await s.close()


async def test_peek_and_directory():
    s = await fresh_store()
    try:
        await s.create_room("r", "alice", title="Room R")
        await s.join("r", "bob")
        await s.say("r", "alice", "hi")
        assert len((await s.peek("bob"))[0]["messages"]) == 1
        assert len((await s.peek("bob"))[0]["messages"]) == 1
        assert await s.list_rooms("bob", box=None) == [{"conv": "r", "unread": 1}]
        assert await s.all_rooms() == [
            {"conv": "r", "members": 2, "messages": 1, "title": "Room R"}]
        await s.create_room("r2", "work3-agent#9")
        assert set(await s.box_rooms("work3")) == {"r2"}
    finally:
        await s.close()
