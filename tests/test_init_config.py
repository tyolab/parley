import json
from parley.cli.init_config import merge_mcp_entry


def test_merge_writes_http_entry(tmp_path):
    p = tmp_path / "cfg.json"
    merge_mcp_entry(str(p), name="parley", url="http://h:8791/mcp", token="tok")
    data = json.loads(p.read_text())
    e = data["mcpServers"]["parley"]
    assert e["type"] == "http" and e["url"] == "http://h:8791/mcp"
    assert e["headers"]["Authorization"] == "Bearer tok"
    assert e["headers"]["X-Parley-Agent"] == "${PARLEY_AGENT:-}"

def test_merge_preserves_other_keys_and_is_idempotent(tmp_path):
    p = tmp_path / "cfg.json"
    p.write_text(json.dumps({"mcpServers": {"other": {"x": 1}}, "keep": "me"}))
    merge_mcp_entry(str(p), name="parley", url="http://h/mcp", token="a")
    merge_mcp_entry(str(p), name="parley", url="http://h/mcp", token="b")  # rewrite
    data = json.loads(p.read_text())
    assert data["keep"] == "me" and data["mcpServers"]["other"] == {"x": 1}
    assert data["mcpServers"]["parley"]["headers"]["Authorization"] == "Bearer b"
