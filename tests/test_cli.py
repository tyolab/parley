from parley.cli.__main__ import build_parser, resolve_config


def test_parser_serve_defaults():
    args = build_parser().parse_args(["serve"])
    assert args.cmd == "serve" and args.port == 8790

def test_parser_say():
    args = build_parser().parse_args(["say", "room1", "hello world"])
    assert args.cmd == "say" and args.room == "room1" and args.text == "hello world"

def test_resolve_config_prefers_flag_over_env(monkeypatch):
    monkeypatch.setenv("PARLEY_GW", "http://env:1")
    monkeypatch.setenv("PARLEY_AGENT", "envagent")
    args = build_parser().parse_args(["say", "r", "t", "--gw", "http://flag:2", "--agent", "flagagent"])
    cfg = resolve_config(args)
    assert cfg["gw"] == "http://flag:2" and cfg["agent"] == "flagagent"

def test_resolve_config_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("PARLEY_GW", "http://env:1")
    monkeypatch.setenv("PARLEY_AGENT", "envagent")
    args = build_parser().parse_args(["say", "r", "t"])
    cfg = resolve_config(args)
    assert cfg["gw"] == "http://env:1" and cfg["agent"] == "envagent"
