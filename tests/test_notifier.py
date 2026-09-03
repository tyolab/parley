import asyncio

import pytest

from parley.notify.daemon import Notifier
from parley.transports.fake import FakeTransport


@pytest.mark.asyncio
async def test_notifier_runs_wake_command_on_nudge():
    transport = FakeTransport()
    calls = []
    async def fake_runner(cmd):  # capture instead of executing
        calls.append(cmd)
    n = Notifier(transport, rooms=["r"], wake_cmd="wake {box} {room} {from}",
                 runner=fake_runner)
    await n.start()
    await transport.publish("r", {"room": "r", "from": "bob", "at": "now"})
    await asyncio.sleep(0.05)
    await n.stop()
    assert calls == ["wake  r bob"]  # {box} empty here; {room}/{from} filled


@pytest.mark.asyncio
async def test_notifier_debounces_rapid_nudges():
    transport = FakeTransport()
    calls = []
    async def runner(cmd): calls.append(cmd)
    n = Notifier(transport, rooms=["r"], wake_cmd="w", runner=runner, debounce_s=0.1)
    await n.start()
    for _ in range(5):
        await transport.publish("r", {"room": "r", "from": "x"})
    await asyncio.sleep(0.05)   # within the debounce window
    await n.stop()
    assert len(calls) == 1  # 5 rapid nudges collapse to one wake


@pytest.mark.asyncio
async def test_notifier_survives_a_failing_wake_command():
    # A wake that raises must not wedge the notifier: the cooling flag has to reset
    # so a later nudge still fires.
    transport = FakeTransport()
    calls = []
    boom = {"fail": True}
    async def runner(cmd):
        if boom["fail"]:
            raise RuntimeError("bad wake")
        calls.append(cmd)
    n = Notifier(transport, rooms=["r"], wake_cmd="w", runner=runner, debounce_s=0)
    await n.start()
    await transport.publish("r", {"room": "r", "from": "x"})  # first wake raises
    await asyncio.sleep(0.05)
    boom["fail"] = False
    await transport.publish("r", {"room": "r", "from": "y"})  # must fire despite prior failure
    await asyncio.sleep(0.05)
    await n.stop()
    assert calls == ["w"]
