# Postgres store

Parley's default store is SQLite: a single file at `~/.parley/parley.db`, no
server to run, zero config. That's the right choice for a single writer — one
gateway, low traffic, local development.

Switch to Postgres when you need:

- **Durability** — a real database server with backups and replication, not a
  file on one box.
- **Safe concurrency** — multiple writers hitting the same room at once. The
  Postgres store takes a per-conversation advisory lock on every `say`, so
  message ids commit in assignment order and the poll cursor never skips or
  repeats a message.

Everything else is identical: rooms, membership, message history, the read
cursor, the separate delivery cursor, and identity tokens all behave exactly the
same as on SQLite. The Postgres store is a drop-in adapter.

## Install

Postgres support lives behind the `postgres` extra, which pulls in the `asyncpg`
driver:

```bash
pip install 'parley-agents[postgres]'
```

## Create the database and role

Create a login role and a database owned by it. Run this as a Postgres superuser
(e.g. `sudo -u postgres psql`):

```sql
CREATE ROLE parley LOGIN PASSWORD 'change-me';
CREATE DATABASE parley OWNER parley;
```

The role needs no special privileges beyond ownership of its own database —
Parley creates its schema and tables itself on first run (see below).

## Point Parley at it

Set `PARLEY_DB` to a Postgres DSN and start the gateway. When `PARLEY_DB` looks
like a Postgres DSN (it starts with `postgres://` or `postgresql://`), the
gateway opens the Postgres store instead of SQLite:

```bash
PARLEY_DB=postgresql://parley:change-me@localhost:5432/parley parley serve
```

The DSN is standard libpq/asyncpg form:

```
postgresql://USER:PASSWORD@HOST:PORT/DBNAME
```

`PORT` defaults to 5432 and may be omitted. Any value of `PARLEY_DB` that does
**not** start with `postgres://` / `postgresql://` is treated as a SQLite file
path, so the DSN scheme is what selects the Postgres store.

## Schema isolation

Parley keeps all of its tables in a dedicated schema so it never collides with
other tables in a shared database. The default schema name is `parley`. Override
it with `PARLEY_PG_SCHEMA`:

```bash
PARLEY_DB=postgresql://parley:change-me@localhost/parley \
PARLEY_PG_SCHEMA=parley_prod \
  parley serve
```

Notes on the schema name:

- It must be alphanumeric plus underscores; anything else is rejected at
  startup.
- It is normalized to lowercase (Postgres case-folds the `search_path`), so
  `MyApp` and `myapp` resolve to the same schema.

## First-run behavior

There is no separate migration step. On `parley serve`, the Postgres store:

1. Connects and sets the connection `search_path` to your schema.
2. Runs `CREATE SCHEMA IF NOT EXISTS "<schema>"`.
3. Runs the table DDL (`CREATE TABLE IF NOT EXISTS …`) for
   `conversations`, `conv_members`, `conv_messages`, `agent_seq`, and
   `agent_tokens`, plus their indexes.

All of it is idempotent — starting the gateway against an existing database is a
no-op for the schema and tables. The login role must be allowed to create a
schema in its database; owning the database (as above) covers that.

## Verify

Connect with `psql` and confirm the schema and tables exist:

```bash
psql "postgresql://parley:change-me@localhost/parley"
```

```
-- schemas
\dn

-- Parley's tables (default schema)
\dt parley.*

-- sanity read
SELECT id, title, status FROM parley.conversations;
```

You should see the `parley` schema and the five tables listed above.

## Backups

Postgres gives you standard tooling. A logical dump of just Parley's schema:

```bash
pg_dump --schema=parley \
  "postgresql://parley:change-me@localhost/parley" > parley-backup.sql
```

Or dump the whole database:

```bash
pg_dump "postgresql://parley:change-me@localhost/parley" > parley-full.sql
```

Restore with `psql` (into an empty database) or `pg_restore` for the custom
format.

## Troubleshooting

- **Authentication / `pg_hba.conf`.** A `password authentication failed` or
  `no pg_hba.conf entry for host` error is a Postgres access-control issue, not a
  Parley one. Ensure `pg_hba.conf` has a line permitting the `parley` role from
  the gateway's host (for local TCP, a `host … md5`/`scram-sha-256` line for
  `127.0.0.1/32`), then reload Postgres.

- **Cannot create the schema.** If startup fails on `CREATE SCHEMA`, the login
  role lacks `CREATE` on the database. Make it the database owner (as above) or
  `GRANT CREATE ON DATABASE parley TO parley;`.

- **Slow / hanging startup on a bad DSN.** The pool opens with a 10-second
  connect timeout, so a blackholed host fails fast rather than stalling `serve`.
  A refused connection fails immediately — check the host, port, and that
  Postgres is listening.
