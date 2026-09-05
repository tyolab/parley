#!/bin/sh
# Parley container entrypoint.
#
# Runs `parley serve --host $PARLEY_HOST --port $PARLEY_PORT`, translating the
# PARLEY_ADMIN_TOKEN env var into the `--token` flag (serve reads the admin
# secret from the flag, not the env). Store/transport are selected entirely by
# the PARLEY_* / MQ_TOKEN env the process already reads. Any extra args are
# appended, so `docker run … parley-image --no-mcp` still works.
set -eu

HOST="${PARLEY_HOST:-0.0.0.0}"
PORT="${PARLEY_PORT:-8790}"

set -- serve --host "$HOST" --port "$PORT" "$@"

# Only pass --token when a non-empty admin secret is provided; otherwise the
# gateway starts in open dev mode.
if [ -n "${PARLEY_ADMIN_TOKEN:-}" ]; then
    set -- "$@" --token "$PARLEY_ADMIN_TOKEN"
fi

exec parley "$@"
