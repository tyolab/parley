import asyncio
import inspect


class _Sub:
    def __init__(self, transport, topic, cb):
        self._t, self.topic, self.cb = transport, topic, cb

    async def close(self):
        self._t._subs.get(self.topic, set()).discard(self)


class FakeTransport:
    """In-process pub/sub for tests and as the reference Transport contract.
    publish() is fire-and-forget: it dispatches each subscriber callback as a
    background task and returns immediately, so a nudge never blocks the caller
    (matching how a real broker publish behaves) and never re-enters it. Callbacks
    may be sync or async. Tests observe delivery after one `await asyncio.sleep(0)`."""
    def __init__(self):
        self._subs: dict[str, set] = {}
        self._tasks: set = set()

    async def publish(self, topic: str, signal: dict) -> None:
        for sub in list(self._subs.get(topic, set())):
            task = asyncio.ensure_future(self._invoke(sub, signal))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _invoke(self, sub, signal):
        res = sub.cb(signal)
        if inspect.isawaitable(res):
            await res

    async def subscribe(self, topic: str, cb):
        sub = _Sub(self, topic, cb)
        self._subs.setdefault(topic, set()).add(sub)
        return sub

    async def close(self) -> None:
        self._subs.clear()
        for t in list(self._tasks):
            t.cancel()
