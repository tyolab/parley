from parley.hooks.stop_hook import decide, format_messages


def _convs():
    return [{"conv": "r", "messages": [{"from": "bob", "body": "hi"}]}]


def test_format_messages():
    assert format_messages(_convs()) == "[r] bob: hi"

def test_decide_allow_when_empty():
    assert decide({"conversations": []}, stop_hook_active=False, mode="engage")["kind"] == "allow"

def test_decide_block_engage():
    a = decide({"conversations": _convs()}, stop_hook_active=False, mode="engage")
    assert a["kind"] == "block" and "bob: hi" in a["reason"]

def test_decide_notify_mode_or_reentry():
    a = decide({"conversations": _convs()}, stop_hook_active=False, mode="notify")
    assert a["kind"] == "notify"
    b = decide({"conversations": _convs()}, stop_hook_active=True, mode="engage")
    assert b["kind"] == "notify"  # reentry does not block again
