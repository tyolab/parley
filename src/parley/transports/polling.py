class _NoopSubscription:
    async def close(self) -> None:
        return None


class PollingTransport:
    """The zero-broker baseline: publish is a no-op, delivery is pull-only via the
    gateway's /poll endpoint. Every push transport degrades to this behaviour when
    no broker is configured."""

    async def publish(self, topic: str, signal: dict) -> None:
        return None

    async def subscribe(self, topic, cb):
        return _NoopSubscription()

    async def close(self) -> None:
        return None
