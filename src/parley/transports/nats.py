import inspect
import json


class _NatsSub:
    def __init__(self, sub):
        self._sub = sub

    async def close(self):
        try:
            await self._sub.unsubscribe()
        except Exception:  # noqa: BLE001, S110 - best-effort
            pass


class NatsTransport:
    """Beta push transport over NATS. Topic -> subject; payload JSON. Lazily
    connects on first use."""
    def __init__(self, servers="nats://127.0.0.1:4222"):
        self._servers = servers
        self._nc = None

    async def _conn(self):
        if self._nc is None:
            import nats
            self._nc = await nats.connect(self._servers)
        return self._nc

    async def publish(self, topic, signal):
        try:
            nc = await self._conn()
            await nc.publish(topic, json.dumps(signal).encode())
        except Exception:  # noqa: BLE001, S110 - best-effort
            pass

    async def subscribe(self, topic, cb):
        nc = await self._conn()
        async def _handler(msg):
            try:
                sig = json.loads(msg.data.decode())
                res = cb(sig)
                if inspect.isawaitable(res):
                    await res
            except Exception:  # noqa: BLE001, S110 - one bad message/callback must not kill the subscription
                pass
        sub = await nc.subscribe(topic, cb=_handler)
        return _NatsSub(sub)

    async def close(self):
        if self._nc is not None:
            try:
                await self._nc.drain()
            except Exception:  # noqa: BLE001, S110 - best-effort
                pass
