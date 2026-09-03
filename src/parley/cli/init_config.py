import json
import os
import tempfile


def merge_mcp_entry(path: str, *, name: str, url: str, token: str,
                    handle_env: str = "PARLEY_AGENT") -> None:
    """Idempotently add/replace an HTTP MCP server entry, preserving all other keys.
    Stdlib only. Atomic write via a temp file + os.replace."""
    path = os.path.expanduser(path)
    data = {}
    if os.path.exists(path) and os.path.getsize(path) > 0:
        with open(path) as f:
            data = json.load(f)
    if not isinstance(data.get("mcpServers"), dict):
        data["mcpServers"] = {}
    data["mcpServers"][name] = {
        "type": "http",
        "url": url,
        "headers": {
            "Authorization": "Bearer " + token,
            "X-Parley-Agent": "${" + handle_env + ":-}",
        },
    }
    d = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".parley-cfg.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
