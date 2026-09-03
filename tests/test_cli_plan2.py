from parley.cli.__main__ import build_parser


def test_serve_has_mcp_port_default():
    args = build_parser().parse_args(["serve", "--port", "9000"])
    assert args.mcp_port is None  # resolved to port+1 at run time when None

def test_token_parses():
    args = build_parser().parse_args(
        ["token", "--gw", "http://h:8790", "--admin-token", "adm", "--box", "work3"])
    assert args.cmd == "token" and args.box == "work3" and args.admin_token == "adm"
