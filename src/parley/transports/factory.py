def make_transport(kind: str = "polling", **opts):
    """Build a Transport by name. Broker adapters are imported lazily so their
    optional deps are only required when actually selected."""
    kind = (kind or "polling").lower()
    if kind == "polling":
        from parley.transports.polling import PollingTransport
        return PollingTransport()
    if kind == "fake":
        from parley.transports.fake import FakeTransport
        return FakeTransport()
    if kind == "tyomq":
        from parley.transports.tyomq import TyoMqTransport
        return TyoMqTransport(host=opts.get("host", "localhost"),
                              port=int(opts.get("port", 17352)), token=opts.get("token"))
    if kind == "redis":
        from parley.transports.redis import RedisTransport
        return RedisTransport(url=opts.get("url", "redis://127.0.0.1:6379"))
    if kind == "nats":
        from parley.transports.nats import NatsTransport
        return NatsTransport(servers=opts.get("servers", "nats://127.0.0.1:4222"))
    raise ValueError(f"unknown transport '{kind}' (polling|fake|tyomq|redis|nats)")
