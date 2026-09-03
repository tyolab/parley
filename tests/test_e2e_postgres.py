import httpx
import pytest

from parley.client import Client
from parley.gateway.app import build_app
from parley.transports.polling import PollingTransport
from tests.pg_util import fresh_store

pytestmark = pytest.mark.asyncio


async def test_two_agents_converse_over_postgres():
    store = await fresh_store()
    app = build_app(store, PollingTransport())

    def mk(a):
        t = httpx.ASGITransport(app=app)
        return Client(base_url="http://t", agent=a,
                      _http=httpx.AsyncClient(transport=t, base_url="http://t"))

    alice, bob = mk("alice"), mk("bob")
    try:
        await alice.create_room("standup", title="Daily")
        await bob.join("standup")
        await alice.say("standup", "what did you ship?")
        await bob.say("standup", "the postgres store")
        a = await alice.poll(); b = await bob.poll()
        assert [m["body"] for c in a for m in c["messages"]] == ["the postgres store"]
        assert [m["body"] for c in b for m in c["messages"]] == ["what did you ship?"]
        assert (await alice.all_rooms())[0] == {
            "conv": "standup", "members": 2, "messages": 2, "title": "Daily"}
    finally:
        await alice.close(); await bob.close(); await store.close()
