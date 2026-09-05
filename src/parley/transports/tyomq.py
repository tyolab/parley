import asyncio
import threading


class _TyoSub:
    def __init__(self, transport, topic, cb):
        self._t, self.topic, self.cb = transport, topic, cb

    async def close(self):
        self._t._subs.get(self.topic, set()).discard(self)


class TyoMqTransport:
    """First-class push transport over tyo-mq.

    tyo_mq_client wraps a synchronous python-socketio Client. Its own
    ``connect()`` call is non-blocking (python-socketio spins up its own
    background reader thread internally) but object construction and the
    connect/auth handshake still happen synchronously, so we do that setup
    on a dedicated background thread rather than on the asyncio loop's
    thread. publish() hands a broadcast to that thread and returns
    immediately (best-effort); inbound messages arrive on tyo_mq_client's
    own background thread and are dispatched to async callbacks on the main
    event loop via run_coroutine_threadsafe. Nudges carry only
    {room, from, at}.

    One client acts as both publisher and subscriber (tyo_mq_client's
    Publisher is-a Subscriber, matching the upstream client's own usage
    pattern), subscribed once to (PRODUCER, EVENT); per-room fan-out is done
    on our side by filtering each inbound message's "room" field against
    the topics passed to subscribe().
    """

    PRODUCER = "parley"
    EVENT = "msg"

    def __init__(self, host="localhost", port=17352, token=None):
        self._host, self._port, self._token = host, port, token
        # Capture the RUNNING loop (the adapter is always constructed inside an
        # async context). get_event_loop() could bind a different, non-running loop
        # if constructed before asyncio.run(), leaving run_coroutine_threadsafe
        # dispatches on a loop that never services them.
        self._loop = asyncio.get_running_loop()
        self._subs: dict[str, set] = {}
        self._pub = None
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run_client, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5)

    def _run_client(self):
        try:
            from tyo_mq_client import MessageQueue

            auth = {"token": self._token} if self._token else None
            # host must be a bare hostname (e.g. "oldnuc") — the client
            # builds "protocol://host:port/" itself; protocol defaults to
            # "http" (upgraded to a websocket connection internally).
            mq = MessageQueue(host=self._host, port=self._port, auth=auth)
            self._pub = mq.createPublisher(self.PRODUCER, self.EVENT)

            def _on_msg(data):
                room = (data or {}).get("room")
                # Deliver to exact-room subscribers plus any catch-all ("*")
                # subscriber (used by an all-rooms idle-wake notifier).
                targets = self._subs.get(room, set()) | self._subs.get("*", set())
                for s in list(targets):
                    asyncio.run_coroutine_threadsafe(self._dispatch(s, data), self._loop)

            # A publisher is also a subscriber in tyo_mq_client; subscribe
            # once for the fixed (producer, event) pair — per-room routing
            # happens client-side in _on_msg above.
            self._pub.subscribe(self.PRODUCER, self.EVENT, _on_msg, True)

            # connect() itself is non-blocking: python-socketio.Client owns
            # a background thread that services the connection (and drives
            # the AUTH/CONSUME callbacks above) independently of this one.
            self._pub.connect(-1)
        except Exception:  # noqa: BLE001 - never hang/fail the constructor
            self._pub = None
        finally:
            self._ready.set()  # never hang the constructor

    async def _dispatch(self, sub, data):
        res = sub.cb(data)
        if asyncio.iscoroutine(res) or asyncio.isfuture(res):
            await res

    async def publish(self, topic, signal):
        if not self._pub:
            return
        try:
            # broadcast (not the unicast default of produce()) delivers one
            # copy to every realm subscriber — what a fan-out nudge needs.
            await asyncio.to_thread(self._pub.broadcast, signal, self.EVENT)
        except Exception:  # noqa: BLE001, S110 - best-effort
            pass  # best-effort

    async def subscribe(self, topic, cb):
        sub = _TyoSub(self, topic, cb)
        self._subs.setdefault(topic, set()).add(sub)
        return sub

    async def close(self):
        self._subs.clear()
        if self._pub is not None:
            try:
                await asyncio.to_thread(self._pub.disconnect)
            except Exception:  # noqa: BLE001, S110 - best-effort
                pass
