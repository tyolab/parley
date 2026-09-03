import asyncio

import httpx
import pytest

from parley.client import Client
from parley.gateway.app import build_app
from parley.notify.daemon import Notifier
from parley.stores.sqlite import SqliteStore
from parley.transports.fake import FakeTransport


@pytest.mark.asyncio
async def test_say_nudges_notifier_and_delivery_cursor_is_independent():
    store = await SqliteStore.connect(":memory:")
    transport = FakeTransport()
    app = build_app(store, transport)

    def mk(a):
        t = httpx.ASGITransport(app=app)
        return Client(base_url="http://t", agent=a,
                      _http=httpx.AsyncClient(transport=t, base_url="http://t"))

    alice, bob = mk("alice"), mk("bob")
    await alice.create_room("r"); await bob.join("r")

    woke = []
    n = Notifier(transport, rooms=["r"], wake_cmd="x", runner=lambda c: woke.append(c),
                 debounce_s=0)
    await n.start()

    await alice.say("r", "hello")     # publishes a nudge to topic "r"
    await asyncio.sleep(0.05)
    assert woke == ["x"]              # notifier fired

    d = await bob.deliver()
    assert [m["body"] for c in d for m in c["messages"]] == ["hello"]
    i = await bob.poll()
    assert [m["body"] for c in i for m in c["messages"]] == ["hello"]  # independent cursor

    await n.stop(); await alice.close(); await bob.close(); await store.close()
