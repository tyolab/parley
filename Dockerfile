# Parley gateway — slim, single-stage image.
#
# Default run is the "just works" variant: zero-config SQLite store + polling
# transport, no external services. Everything is overridable purely by env/args:
#
#   PARLEY_ADMIN_TOKEN   admin secret (mapped to `parley serve --token`); unset => open dev mode
#   PARLEY_DB            unset => SQLite at $HOME/.parley/parley.db;
#                        a postgresql://… DSN => Postgres store (needs the [postgres] extra, baked in)
#   PARLEY_PG_SCHEMA     Postgres schema (default: parley)
#   PARLEY_TRANSPORT     polling (default) | tyomq | redis | nats
#   PARLEY_MQ_HOST/PORT  tyo-mq broker (when PARLEY_TRANSPORT=tyomq)
#   MQ_TOKEN             tyo-mq auth token (when PARLEY_TRANSPORT=tyomq)
#   PARLEY_HOST          bind host (default 0.0.0.0)
#   PARLEY_PORT          REST port (default 8790); MCP is served on PARLEY_PORT+1
#
# Extra CLI args passed to `docker run` are appended to `parley serve`.
FROM python:3.12-slim

# Faster, quieter, reproducible-ish Python in a container.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/data \
    PARLEY_HOST=0.0.0.0 \
    PARLEY_PORT=8790

WORKDIR /app

# Copy only what the build backend (hatchling) needs to build+install the wheel,
# so a source-only edit doesn't force a dependency reinstall.
COPY pyproject.toml README.md LICENSE ./
COPY src ./src

# Install the package WITH the postgres + tyomq adapters so a single image can
# run any store/transport combo purely by env. The polling+SQLite default needs
# none of these, but baking them in keeps one image for every deployment.
RUN pip install '.[postgres,tyomq]'

# Non-root. HOME=/data is this user's home, so the zero-config SQLite file lands
# at /data/.parley/parley.db and is covered by the VOLUME below.
RUN useradd --create-home --home-dir /data --uid 10001 parley \
    && mkdir -p /data/.parley \
    && chown -R parley:parley /data

COPY --chown=parley:parley docker/entrypoint.sh /usr/local/bin/parley-entrypoint
RUN chmod +x /usr/local/bin/parley-entrypoint

USER parley

# Persist the SQLite store (and anything else the agent writes under HOME).
VOLUME ["/data"]

# REST on PARLEY_PORT, MCP on PARLEY_PORT+1.
EXPOSE 8790 8791

# Lightweight healthcheck against the REST /healthz endpoint.
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=5 \
    CMD python -c "import os,urllib.request,sys; \
url='http://127.0.0.1:%s/healthz' % os.environ.get('PARLEY_PORT','8790'); \
sys.exit(0 if urllib.request.urlopen(url, timeout=2).status==200 else 1)"

ENTRYPOINT ["parley-entrypoint"]
CMD []
