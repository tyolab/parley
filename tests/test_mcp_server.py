import pytest

from parley.mcp.server import _tool_names, build_mcp_app, current_agent_id, current_box
from parley.stores.sqlite import SqliteStore


@pytest.fixture
async def store():
    s = await SqliteStore.connect(":memory:")
    yield s
    await s.close()


async def test_expected_tools_registered(store):
    app = build_mcp_app(store, admin_token=None)
    names = await _tool_names(app)
    assert {"start_conv", "join_conv", "leave_conv", "say", "poll_convs",
            "peek_convs", "list_convs", "list_all_convs", "who"} <= set(names)


async def test_middleware_sets_identity_contextvars(store):
    tok = await store.mint_agent_token("work3")
    app = build_mcp_app(store, admin_token=None)
    seen = {}

    async def fake_inner(scope, receive, send):
        seen["agent"] = current_agent_id.get()
        seen["box"] = current_box.get()

    app.app = fake_inner  # replace the wrapped ASGI app with a probe
    scope = {"type": "http", "headers": [
        (b"authorization", f"Bearer {tok}".encode()),
        (b"x-parley-agent", b"work3-agent#1")]}
    await app(scope, None, None)
    assert seen == {"agent": "work3-agent#1", "box": "work3"}

async def test_non_http_scope_passes_through(store):
    app = build_mcp_app(store, admin_token=None)
    hit = {}
    async def fake_inner(scope, receive, send):
        hit["ok"] = True
    app.app = fake_inner
    await app({"type": "lifespan"}, None, None)
    assert hit == {"ok": True}
