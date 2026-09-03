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
    finally:
        await s.close()
