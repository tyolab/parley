import asyncio

import httpx
import pytest

from parley.client import Client
from parley.gateway.app import build_app
from parley.stores.sqlite import SqliteStore
from parley.transports.fake import FakeTransport


@pytest.mark.asyncio
async def test_listen_polls_on_nudge():
    store = await SqliteStore.connect(":memory:")
    transport = FakeTransport()
    app = build_app(store, transport)

    def mk(agent):
        t = httpx.ASGITransport(app=app)
        return Client(base_url="http://t", agent=agent,
                      _http=httpx.AsyncClient(transport=t, base_url="http://t"))

    alice, bob = mk("alice"), mk("bob")
    await alice.create_room("r"); await bob.join("r")

    delivered = []
    async def on_nudge(sig):
        for conv in await bob.poll():
            for m in conv["messages"]:
                delivered.append(m["body"])
    subs = await bob.listen(transport, ["r"], on_nudge)

    await alice.say("r", "ping")  # gateway publishes a nudge to topic "r"
    await asyncio.sleep(0.05)
    assert delivered == ["ping"]

    await subs[0].close()
    await alice.close(); await bob.close(); await store.close()
