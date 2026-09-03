import asyncio

import pytest

pytestmark = pytest.mark.asyncio


async def _port_up(host, port):
    try:
        _r, w = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=1.0)
        w.close(); return True
    except Exception:  # noqa: BLE001 - liveness probe: any failure means "down"
        return False


async def test_redis_roundtrip():
    pytest.importorskip("redis")
    if not await _port_up("127.0.0.1", 6379):
        pytest.skip("no local redis")
    from parley.transports.redis import RedisTransport
    t = RedisTransport(url="redis://127.0.0.1:6379")
    got = asyncio.Event(); box = {}
    await t.subscribe("r", lambda s: (box.update(s), got.set()))
    await asyncio.sleep(0.3)
    await t.publish("r", {"room": "r", "from": "z"})
    await asyncio.wait_for(got.wait(), timeout=3); await t.close()
    assert box.get("from") == "z"


async def test_nats_roundtrip():
    pytest.importorskip("nats")
    if not await _port_up("127.0.0.1", 4222):
        pytest.skip("no local nats")
    from parley.transports.nats import NatsTransport
    t = NatsTransport(servers="nats://127.0.0.1:4222")
    got = asyncio.Event(); box = {}
    await t.subscribe("r", lambda s: (box.update(s), got.set()))
    await asyncio.sleep(0.3)
    await t.publish("r", {"room": "r", "from": "z"})
    await asyncio.wait_for(got.wait(), timeout=3); await t.close()
    assert box.get("from") == "z"
