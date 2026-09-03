import asyncio
import pytest
from parley.transports.fake import FakeTransport
from parley.transports.polling import PollingTransport


async def test_fake_delivers_to_subscribers_of_topic():
    t = FakeTransport()
    got = []
    await t.subscribe("roomA", lambda sig: got.append(sig))
    await t.publish("roomA", {"room": "roomA", "from": "x", "at": "now"})
    await asyncio.sleep(0)  # let the callback task run
    assert got == [{"room": "roomA", "from": "x", "at": "now"}]

async def test_fake_isolates_topics():
    t = FakeTransport()
    got = []
    await t.subscribe("roomA", lambda s: got.append(s))
    await t.publish("roomB", {"room": "roomB"})
    await asyncio.sleep(0)
    assert got == []

async def test_fake_supports_async_callback_and_unsubscribe():
    t = FakeTransport()
    got = []
    async def cb(sig): got.append(sig)
    sub = await t.subscribe("r", cb)
    await t.publish("r", {"n": 1}); await asyncio.sleep(0)
    await sub.close()
    await t.publish("r", {"n": 2}); await asyncio.sleep(0)
    assert got == [{"n": 1}]
    await t.close()

async def test_polling_transport_still_satisfies_close():
    t = PollingTransport()
    await t.publish("r", {})  # no-op
    sub = await t.subscribe("r", lambda s: None)
    await sub.close(); await t.close()
