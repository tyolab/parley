#!/bin/sh
# tyo-mq broker entrypoint for the Parley stack.
#
# tyo-mq keeps realms/tokens in a JSON settings file. To keep a single source of
# truth, we RENDER that file from env on every start so MQ_TOKEN is the only knob
# an operator needs to set (it must match the token Parley connects with).
#
# Realms:
#   default  -> open (required:false) so unrelated token-less clients still work
#   <realm>  -> required:true; Parley's token (role "both") is scoped to it
# Plus a wildcard admin token (TYO_MQ_ADMIN_TOKEN) for manager/ops.
set -eu

SETTINGS_FILE="${TYO_MQ_SETTINGS_FILE:-/data/tyo-mq.settings.json}"
REALM="${PARLEY_MQ_REALM:-parley}"
MQ_TOKEN="${MQ_TOKEN:?MQ_TOKEN must be set (the token Parley authenticates with)}"
ADMIN_TOKEN="${TYO_MQ_ADMIN_TOKEN:?TYO_MQ_ADMIN_TOKEN must be set}"

mkdir -p "$(dirname "$SETTINGS_FILE")"

cat > "$SETTINGS_FILE" <<EOF
{
  "serveClient": false,
  "auth": {
    "enabled": true,
    "realms": {
      "default": { "required": false },
      "${REALM}": { "required": true }
    },
    "tokens": [
      { "token": "${ADMIN_TOKEN}", "realm": "*", "role": "admin" },
      { "token": "${MQ_TOKEN}", "realm": "${REALM}", "role": "both" }
    ]
  },
  "http_api": { "enabled": true },
  "storage": "sqlite",
  "storage_options": {}
}
EOF

echo "[tyomq-entrypoint] rendered $SETTINGS_FILE (realm=${REALM}, auth=enabled)"

cd /app
exec node server.js
