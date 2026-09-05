import json
import os
import shutil
import tempfile


def _atomic_write(path: str, text: str, *, mode: int | None = None) -> None:
    """Atomically write `text` to `path` (temp file + os.replace). Stdlib only.
    If `mode` is given, the file ends up with exactly that permission."""
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".parley-cfg.", suffix=".tmp")
    try:
        if mode is not None:
            os.fchmod(fd, mode)
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


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
    _atomic_write(path, json.dumps(data, indent=2) + "\n")


def write_hook_env(path: str, *, gw: str, token: str, agent: str,
                   stop_mode: str = "notify") -> None:
    """Write the Stop-hook env file (PARLEY_GW/TOKEN/AGENT/STOP_MODE) at mode 0600.
    It carries the agent bearer token, so it must never be world-readable."""
    path = os.path.expanduser(path)
    lines = [
        f"PARLEY_GW={gw}",
        f"PARLEY_TOKEN={token}",
        f"PARLEY_AGENT={agent}",
        f"PARLEY_STOP_MODE={stop_mode}",
    ]
    _atomic_write(path, "\n".join(lines) + "\n", mode=0o600)


_STOP_HOOK_MARKER = "parley.hooks.stop_hook"


def register_stop_hook(path: str, *, command: str, backup: bool = True) -> None:
    """Idempotently register a Claude Code Stop hook running `command`. Any existing
    Stop hook whose command references parley.hooks.stop_hook is removed first, so
    re-running never leaves a duplicate; unrelated Stop hooks are preserved. The
    settings file is backed up once to `<path>.bak-parley` before the first rewrite.
    Stdlib only, atomic write."""
    path = os.path.expanduser(path)
    data = {}
    if os.path.exists(path) and os.path.getsize(path) > 0:
        with open(path) as f:
            data = json.load(f)
        if backup:
            bak = path + ".bak-parley"
            if not os.path.exists(bak):
                shutil.copy2(path, bak)
    hooks = data.setdefault("hooks", {})
    stop = hooks.get("Stop")
    stop = stop if isinstance(stop, list) else []
    cleaned = []
    for group in stop:
        if not isinstance(group, dict):
            cleaned.append(group)
            continue
        inner = group.get("hooks")
        if isinstance(inner, list):
            kept = [h for h in inner
                    if not (isinstance(h, dict) and _STOP_HOOK_MARKER in (h.get("command") or ""))]
            if not kept:
                continue  # drop a group that held only the (now removed) parley hook
            group = {**group, "hooks": kept}
        cleaned.append(group)
    cleaned.append({"hooks": [{"type": "command", "command": command}]})
    hooks["Stop"] = cleaned
    data["hooks"] = hooks
    _atomic_write(path, json.dumps(data, indent=2) + "\n")
