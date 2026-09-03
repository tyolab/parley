import asyncio
import inspect
import shlex


async def _default_runner(cmd: str):
    """Run a wake command in a subprocess (fire-and-forget)."""
    proc = await asyncio.create_subprocess_exec(
        *shlex.split(cmd), stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL)
    await proc.wait()


class Notifier:
    """Subscribes to a box's room topics and runs a wake command on a nudge, so an
    idle agent session gets woken to poll. Leading-edge debounce: the FIRST nudge
    fires the wake immediately, and further nudges within `debounce_s` are
    suppressed (an idle agent only needs one poke). `wake_cmd` is a template with
    {box}/{room}/{from}; `runner` (sync OR async) is injectable for tests."""
    def __init__(self, transport, rooms, wake_cmd, box="", runner=None, debounce_s=0.5):
        self._t, self._rooms, self._cmd = transport, rooms, wake_cmd
        self._box, self._runner = box, runner or _default_runner
        self._debounce = debounce_s
        self._subs = []
        self._cooling = False
        self._cool_task = None

    async def start(self):
        for room in self._rooms:
            self._subs.append(await self._t.subscribe(room, self._on_nudge))

    async def _on_nudge(self, sig):
        if self._cooling:
            return  # inside the cooldown window from a recent wake
        self._cooling = True
        try:
            await self._fire(sig)
        finally:
            # Always schedule the cooldown, even if _fire raised, so a single failed
            # wake can never leave the notifier stuck in the cooling state (which
            # would silently suppress every future nudge).
            self._cool_task = asyncio.create_task(self._cooldown())

    async def _cooldown(self):
        await asyncio.sleep(self._debounce)
        self._cooling = False

    async def _fire(self, sig):
        try:
            cmd = self._cmd.format(box=self._box, room=sig.get("room", ""),
                                   **{"from": sig.get("from", "")})
            res = self._runner(cmd)          # runner may be sync or async
            if inspect.isawaitable(res):
                await res
        except Exception:  # noqa: BLE001, S110 - a failed wake must not wedge the notifier or kill the subscription
            pass

    async def stop(self):
        for s in self._subs:
            await s.close()
        if self._cool_task and not self._cool_task.done():
            self._cool_task.cancel()
