import pytest
import httpx
from parley.stores.sqlite import SqliteStore
from parley.transports.polling import PollingTransport
from parley.gateway.app import build_app
from parley.client import Client


@pytest.fixture
async def make_client():
    store = await SqliteStore.connect(":memory:")
    app = build_app(store, PollingTransport())
    def _mk(agent):
        transport = httpx.ASGITransport(app=app)
        http = httpx.AsyncClient(transport=transport, base_url="http://t")
        return Client(base_url="http://t", agent=agent, _http=http)
    yield _mk
    await store.close()


async def test_client_roundtrip(make_client):
    alice = make_client("alice")
    bob = make_client("bob")
    assert (await alice.create_room("r"))["created"] is True
    await bob.join("r")
    await alice.say("r", "hi bob")
    convs = await bob.poll()
    assert convs[0]["conv"] == "r"
    assert convs[0]["messages"][0]["body"] == "hi bob"
    await alice.close(); await bob.close()
