from parley.transports.polling import PollingTransport


async def test_publish_is_noop_and_never_raises():
    t = PollingTransport()
    await t.publish("room", {"room": "room", "from": "alice", "at": "now"})  # no error

async def test_subscribe_returns_closable_subscription():
    t = PollingTransport()
    got = []
    sub = await t.subscribe("room", lambda sig: got.append(sig))
    await sub.close()
    await t.close()
    assert got == []  # polling never pushes
