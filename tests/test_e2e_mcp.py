import httpx
import pytest

from parley.gateway.app import build_app
from parley.stores.sqlite import SqliteStore
from parley.transports.polling import PollingTransport


@pytest.mark.asyncio
async def test_token_identity_is_unspoofable_end_to_end():
    store = await SqliteStore.connect(":memory:")
    app = build_app(store, PollingTransport(), admin_token="adm")
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")

    async def mint(box):
        r = await c.post("/admin/agents", json={"box": box},
                         headers={"Authorization": "Bearer adm"})
        return r.json()["token"]

    w_tok, e_tok = await mint("work3"), await mint("elitebook2")

    def H(tok, handle, spoof_box=None):
        h = {"Authorization": f"Bearer {tok}", "X-Parley-Agent": handle}
        if spoof_box:
            h["X-Parley-Box"] = spoof_box  # attempt to impersonate another box
        return h

    # work3 agent creates a room while trying to spoof box=elitebook2; the token wins
    await c.post("/rooms", json={"name": "x"}, headers=H(w_tok, "work3-a#1", "elitebook2"))
    await c.post("/rooms/x/join", headers=H(e_tok, "elitebook2-a#1"))
    await c.post("/rooms/x/messages", json={"body": "from work3"},
                 headers=H(w_tok, "work3-a#1", "elitebook2"))
    poll = await c.get("/poll", headers=H(e_tok, "elitebook2-a#1"))
    msgs = poll.json()["conversations"][0]["messages"]
    assert msgs[0]["from"] == "work3-a#1"  # composed from the TOKEN's box, not the spoof
    members = (await c.get("/rooms/x/members", headers=H(e_tok, "elitebook2-a#1"))).json()
    assert set(members["members"]) == {"work3-a#1", "elitebook2-a#1"}

    await c.aclose(); await store.close()
