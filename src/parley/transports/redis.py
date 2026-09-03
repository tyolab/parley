import asyncio
import inspect
import json


class _RedisSub:
    def __init__(self, transport, topic, cb, task, pubsub):
        self._t, self.topic, self.cb, self._task, self._pubsub = transport, topic, cb, task, pubsub

    async def close(self):
        self._task.cancel()
        try:
            await self._pubsub.unsubscribe(self.topic)
            await self._pubsub.aclose()
        except Exception:
            pass


class RedisTransport:
    """Beta push transport over Redis pub/sub. Topics map 1:1 to Redis channels;
    payloads are JSON. Callbacks may be sync or async."""
    def __init__(self, url="redis://127.0.0.1:6379"):
        import redis.asyncio as redis
        self._r = redis.from_url(url, decode_responses=True)

    async def publish(self, topic, signal):
        try:
            await self._r.publish(topic, json.dumps(signal))
        except Exception:
            pass  # best-effort

    async def subscribe(self, topic, cb):
        pubsub = self._r.pubsub()
        await pubsub.subscribe(topic)

        async def _reader():
            async for msg in pubsub.listen():
                if msg.get("type") != "message":
                    continue
                sig = json.loads(msg["data"])
                res = cb(sig)
                if inspect.isawaitable(res):
                    await res

        task = asyncio.create_task(_reader())
        return _RedisSub(self, topic, cb, task, pubsub)

    async def close(self):
        try:
            await self._r.aclose()
        except Exception:
            pass
