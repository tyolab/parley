#!/usr/bin/env python3
"""Claude Code Stop hook: at each turn boundary, pull queued peer messages from the
Parley gateway's catch-all delivery endpoint and surface them. Fail-open: any error
exits 0 so a session is never wedged.

Env: PARLEY_GW (default http://127.0.0.1:8790), PARLEY_TOKEN (agent bearer),
PARLEY_AGENT (handle), PARLEY_STOP_MODE (engage|notify, default engage)."""
import json
import os
import sys
import urllib.request


def format_messages(conversations):
    lines = []
    for c in conversations:
        for m in c.get("messages", []):
            lines.append(f"[{c.get('conv', '?')}] {m.get('from', '?')}: {m.get('body', '')}")
    return "\n".join(lines)


def decide(poll_result, stop_hook_active, mode):
    convs = (poll_result or {}).get("conversations") or []
    if not any(c.get("messages") for c in convs):
        return {"kind": "allow"}
    text = format_messages(convs)
    if mode == "notify" or stop_hook_active:
        return {"kind": "notify", "text": text}
    reason = ("New Parley messages:\n" + text +
              "\n\nReply with the `say` tool if a response is warranted; otherwise you may stop.")
    return {"kind": "block", "reason": reason}


def fetch_deliver(gw, token, handle, timeout=2.0):
    headers = {"Authorization": "Bearer " + token} if token else {}
    if handle:
        headers["X-Parley-Agent"] = handle
    req = urllib.request.Request(gw.rstrip("/") + "/deliver", headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def main():
    try:
        stdin = json.load(sys.stdin) if not sys.stdin.isatty() else {}
    except Exception:
        stdin = {}
    stop_hook_active = bool(stdin.get("stop_hook_active"))
    gw = os.environ.get("PARLEY_GW", "http://127.0.0.1:8790")
    token = os.environ.get("PARLEY_TOKEN")
    handle = os.environ.get("PARLEY_AGENT")
    mode = os.environ.get("PARLEY_STOP_MODE", "engage")
    try:
        poll = fetch_deliver(gw, token, handle)
    except Exception:
        sys.exit(0)  # fail-open
    action = decide(poll, stop_hook_active, mode)
    if action["kind"] == "block":
        print(json.dumps({"decision": "block", "reason": action["reason"]}))
    elif action["kind"] == "notify":
        print(action["text"])
    sys.exit(0)


if __name__ == "__main__":
    main()
