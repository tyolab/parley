# tyo-mq broker image for the Parley stack (multi-stage, glibc).
#
# Built from the tyo-mq source tree, supplied as the named build context
# `tyomqsrc` (see docker-compose.yml -> tyomq.build.additional_contexts, default
# /data/tyolab/node/tyo-mq). We keep this Dockerfile inside the Parley repo so
# the stack is self-describing, while still building the broker from its own
# source.
#
# NB: a glibc base (bookworm-slim) is required — tyo-mq depends on
# @signalapp/libsignal-client, whose prebuilt native binary is linked against
# glibc and fails to load on a musl/Alpine base.

# --- builder: has the toolchain to compile any native module from source ------
FROM node:22-bookworm-slim AS builder
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 make g++ \
    && rm -rf /var/lib/apt/lists/*
COPY --from=tyomqsrc package.json package-lock.json* ./
RUN npm install --omit=dev && npm cache clean --force

# --- runtime: slim, no compilers -----------------------------------------------
FROM node:22-bookworm-slim
WORKDIR /app

# wget is used by the compose healthcheck against GET /health.
RUN apt-get update \
    && apt-get install -y --no-install-recommends wget ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Prebuilt/compiled dependencies from the builder stage.
COPY --from=builder /app/node_modules ./node_modules

# Copy just the runtime source (not the host's node_modules or .git — named
# build contexts don't honour .dockerignore, so we select paths explicitly).
COPY --from=tyomqsrc package.json package-lock.json* ./
COPY --from=tyomqsrc server.js index.js ./
COPY --from=tyomqsrc lib ./lib
COPY --from=tyomqsrc web ./web
COPY --from=tyomqsrc bin ./bin
COPY --from=tyomqsrc scripts ./scripts

RUN mkdir -p /data

EXPOSE 17352

# docker-compose overrides the entrypoint to render the Parley realm/token
# settings before launching; this CMD is the plain fallback.
CMD ["node", "server.js"]
