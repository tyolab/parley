import httpx
import pytest

from parley.client import Client
from parley.gateway.app import build_app
from parley.stores.sqlite import SqliteStore
from parley.transports.polling import PollingTransport


@pytest.mark.asyncio
async def test_two_agents_converse_over_gateway():
    store = await SqliteStore.connect(":memory:")
    app = build_app(store, PollingTransport())

    def mk(agent):
        t = httpx.ASGITransport(app=app)
        return Client(base_url="http://t", agent=agent,
                      _http=httpx.AsyncClient(transport=t, base_url="http://t"))

    alice, bob = mk("alice"), mk("bob")
    await alice.create_room("standup", title="Daily")
    await bob.join("standup")
    await alice.say("standup", "what did you ship?")
    await bob.say("standup", "the poll cursor")

    # each hears the other exactly once, own messages excluded
    a = await alice.poll()
    b = await bob.poll()
    assert [m["body"] for c in a for m in c["messages"]] == ["the poll cursor"]
    assert [m["body"] for c in b for m in c["messages"]] == ["what did you ship?"]
    # cursors advanced
    assert await alice.poll() == [] and await bob.poll() == []
    # directory reflects the room
    assert (await alice.all_rooms())[0] == {
        "conv": "standup", "members": 2, "messages": 2, "title": "Daily"}

    await alice.close(); await bob.close(); await store.close()
