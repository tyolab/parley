import json
import os
import stat

from parley.cli import __main__ as cli
from parley.cli.init_config import register_stop_hook, write_hook_env


def _fake_request(token="TOK", mcp_port=8891, status=200):
    async def _req(rest, join_code, box):
        if status != 200:
            return status, {"detail": "boom"}
        return 200, {"token": token, "box": box, "mcp_port": mcp_port}
    return _req


def test_parser_enroll_defaults():
    args = cli.build_parser().parse_args(
        ["enroll", "--gw", "http://h:8890", "--join-code", "jc", "--box", "work3"])
    assert args.cmd == "enroll" and args.box == "work3"
    assert args.name == "parley" and args.stop_mode == "notify"


def test_enroll_writes_mcp_entry(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_enroll_request", _fake_request())
    cfg = tmp_path / "claude.json"
    args = cli.build_parser().parse_args([
        "enroll", "--gw", "http://h:8890", "--join-code", "jc", "--box", "work3",
        "--config-file", str(cfg), "--no-hook"])
    assert cli._enroll(args) == 0
    e = json.loads(cfg.read_text())["mcpServers"]["parley"]
    assert e["url"] == "http://h:8891/mcp"  # derived from gw host + returned mcp_port
    assert e["headers"]["Authorization"] == "Bearer TOK"


def test_enroll_preserves_other_keys_and_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_enroll_request", _fake_request())
    cfg = tmp_path / "claude.json"
    cfg.write_text(json.dumps({"mcpServers": {"other": {"x": 1}}, "keep": "me"}))
    argv = ["enroll", "--gw", "http://h:8890", "--join-code", "jc", "--box", "work3",
            "--config-file", str(cfg), "--no-hook"]
    assert cli._enroll(cli.build_parser().parse_args(argv)) == 0
    assert cli._enroll(cli.build_parser().parse_args(argv)) == 0  # re-run
    data = json.loads(cfg.read_text())
    assert data["keep"] == "me" and data["mcpServers"]["other"] == {"x": 1}
    assert data["mcpServers"]["parley"]["url"] == "http://h:8891/mcp"


def test_enroll_no_hook_skips_hook(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(cli, "_enroll_request", _fake_request())
    cfg = tmp_path / "claude.json"
    settings = tmp_path / "settings.json"
    args = cli.build_parser().parse_args([
        "enroll", "--gw", "http://h:8890", "--join-code", "jc", "--box", "work3",
        "--config-file", str(cfg), "--settings-file", str(settings), "--no-hook"])
    assert cli._enroll(args) == 0
    assert not settings.exists()
    assert not (tmp_path / ".config" / "parley" / "parley.env").exists()


def test_enroll_hook_mode_writes_env_and_registers_hook(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(cli, "_enroll_request", _fake_request())
    cfg = tmp_path / "claude.json"
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"existing": True}))  # pre-existing -> should be backed up
    argv = ["enroll", "--gw", "http://h:8890", "--join-code", "jc", "--box", "work3",
            "--config-file", str(cfg), "--settings-file", str(settings)]
    assert cli._enroll(cli.build_parser().parse_args(argv)) == 0

    env_file = tmp_path / ".config" / "parley" / "parley.env"
    assert env_file.exists()
    mode = stat.S_IMODE(os.stat(env_file).st_mode)
    assert mode == 0o600  # never world-readable, it holds the token
    env_text = env_file.read_text()
    assert "PARLEY_TOKEN=TOK" in env_text
    assert "PARLEY_GW=http://h:8890" in env_text
    assert "PARLEY_AGENT=work3" in env_text  # handle defaults to box
    assert "PARLEY_STOP_MODE=notify" in env_text

    assert (settings.parent / "settings.json.bak-parley").exists()  # backed up
    data = json.loads(settings.read_text())
    assert data["existing"] is True  # preserved
    stop = data["hooks"]["Stop"]
    parley_hooks = [h for g in stop for h in g.get("hooks", [])
                    if "parley.hooks.stop_hook" in h.get("command", "")]
    assert len(parley_hooks) == 1

    # idempotent: re-running does not add a second parley Stop hook
    assert cli._enroll(cli.build_parser().parse_args(argv)) == 0
    data2 = json.loads(settings.read_text())
    stop2 = data2["hooks"]["Stop"]
    parley_hooks2 = [h for g in stop2 for h in g.get("hooks", [])
                     if "parley.hooks.stop_hook" in h.get("command", "")]
    assert len(parley_hooks2) == 1


def test_enroll_surfaces_server_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_enroll_request", _fake_request(status=409))
    cfg = tmp_path / "claude.json"
    args = cli.build_parser().parse_args([
        "enroll", "--gw", "http://h:8890", "--join-code", "jc", "--box", "work3",
        "--config-file", str(cfg), "--no-hook"])
    assert cli._enroll(args) == 1  # non-zero exit
    assert not cfg.exists()  # nothing wired on failure
    err = capsys.readouterr().err
    assert "boom" in err


def test_enroll_requires_gw(tmp_path):
    args = cli.build_parser().parse_args(
        ["enroll", "--join-code", "jc", "--box", "work3",
         "--config-file", str(tmp_path / "c.json"), "--no-hook"])
    assert cli._enroll(args) == 2  # usage error


def test_enroll_join_code_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("PARLEY_JOIN_CODE", "envjc")
    monkeypatch.setattr(cli, "_enroll_request", _fake_request())
    cfg = tmp_path / "claude.json"
    args = cli.build_parser().parse_args([
        "enroll", "--gw", "http://h:8890", "--box", "work3",
        "--config-file", str(cfg), "--no-hook"])
    assert cli._enroll(args) == 0


# --- direct unit tests for the reusable wiring helpers ---

def test_write_hook_env_is_0600(tmp_path):
    p = tmp_path / "sub" / "parley.env"
    write_hook_env(str(p), gw="http://h:8890", token="TOK", agent="work3", stop_mode="notify")
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o600
    assert "PARLEY_TOKEN=TOK" in p.read_text()


def test_register_stop_hook_replaces_existing(tmp_path):
    s = tmp_path / "settings.json"
    s.write_text(json.dumps({"hooks": {"Stop": [
        {"hooks": [{"type": "command", "command": "old python -m parley.hooks.stop_hook"}]},
        {"hooks": [{"type": "command", "command": "keep-me-unrelated"}]},
    ]}}))
    register_stop_hook(str(s), command="new python -m parley.hooks.stop_hook")
    stop = json.loads(s.read_text())["hooks"]["Stop"]
    cmds = [h["command"] for g in stop for h in g.get("hooks", [])]
    assert "keep-me-unrelated" in cmds  # unrelated hook preserved
    parley = [c for c in cmds if "parley.hooks.stop_hook" in c]
    assert parley == ["new python -m parley.hooks.stop_hook"]  # replaced, exactly one
