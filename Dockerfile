# Wolfi's apk repo is fully open — no Chainguard subscription needed. ":latest"
# is the only free tag, so the digest below is the version pin; Dependabot's
# "docker" ecosystem (.github/dependabot.yml) is the only thing that moves it
# (and the uv pin below). Keep it fresh: the apk packages added below are
# unpinned and built against Wolfi's *current* glibc, while this rootfs keeps
# the glibc it shipped with (nothing here runs `apk upgrade`). A stale digest
# fails docker/smoke-test.sh with "version `GLIBC_x.yy' not found".
FROM cgr.dev/chainguard/wolfi-base:latest@sha256:103eb3f4444c68ea2453bf3aad09d860eaa5a698effb3e656cd607f630f0e46d AS base

# Declared AFTER "FROM" on purpose: an ARG before the first FROM is in scope for
# FROM only, so the RUN below would expand it to "" and run `apk add python-`.
ARG PYTHON_VERSION=3.12

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Install runtime dependencies. Versions deliberately unpinned: Wolfi rolls
# forward and garbage-collects old versions, so an "=<version>" pin breaks the
# build within days. The guardrails are the version-scoped names plus the
# digest above. No pip: uv (below) installs everything.
#   libstdc++  NOT optional: the rasterio/pyproj/duckdb manylinux wheels list
#              libstdc++.so.6 in DT_NEEDED and auditwheel does not vendor it.
#   bash, tzdata, curl  parity with the old Debian base: /bin/sh is busybox,
#              Wolfi ships no /usr/share/zoneinfo, curl is for in-pod debugging.
RUN apk add --no-cache \
      python-${PYTHON_VERSION} \
      libstdc++ bash tzdata curl

# uv, pinned to the version that wrote uv.lock. A named stage rather than a
# direct COPY --from=<image> because Dependabot only parses FROM lines — it
# ignores images in COPY (dependabot-core#5103) — and a digest pin nothing
# moves would rot.
FROM ghcr.io/astral-sh/uv:0.11.17@sha256:03bdc89bb9798628846e60c3a9ad19006c8c3c724ccd2985a33145c039a0577b AS uv

# Build stage
FROM base AS builder

ARG PYTHON_VERSION

# Set build labels
LABEL stage=builder
LABEL org.opencontainers.image.source="https://github.com/EOPF-Explorer/titiler-eopf"
LABEL org.opencontainers.image.description="TiTiler application for EOPF datasets"
LABEL org.opencontainers.image.licenses="Apache-2.0"

# Install uv
COPY --from=uv /uv /uvx /usr/local/bin/

# Configure uv-managed virtual environment
#   UV_PYTHON: the apk python above, so the venv's interpreter symlinks resolve
#     against the same path in the runtime stage
#   UV_COMPILE_BYTECODE: .pyc at install time, as pip did, so cold starts
#     don't pay the compile on first import
ENV UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON=python${PYTHON_VERSION} \
    UV_COMPILE_BYTECODE=1 \
    PATH="/opt/venv/bin:${PATH}"

WORKDIR /tmp/app

# Copy project metadata and install dependencies from the lockfile (--frozen:
# uv.lock is authoritative, out-of-date fails the build). The `server` extra
# carries uvicorn/gunicorn/uvicorn-worker — the chart and the CMD below need
# them as locked deps, not ad-hoc installs.
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --frozen --no-dev --extra server --extra cache --extra openeo --no-install-project

# Copy and install runtime source code to the builder image
COPY titiler/ titiler/
RUN uv pip install --no-deps .

# Runtime stage
FROM base

# Set runtime labels
LABEL org.opencontainers.image.source="https://github.com/EOPF-Explorer/titiler-eopf"
LABEL org.opencontainers.image.description="TiTiler application for EOPF datasets"
LABEL org.opencontainers.image.licenses="Apache-2.0"

# The chart execs `command: ["uvicorn"]` — a bare binary, resolved against the
# image's PATH; smoke-test C1 asserts it.
ENV PATH="/opt/venv/bin:${PATH}"

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv

WORKDIR /tmp

# Run as the wolfi-base nonroot user (uid 65532). On Kubernetes the chart sets 
# the net.ipv4.ip_unprivileged_port_start sysctl per pod. 
# Other deployments must allow unprivileged low ports the same way,
# or override PORT to something >=1024.
USER nonroot

###################################################
# For compatibility (might be removed at one point)
ENV MODULE_NAME=titiler.eopf.main
ENV VARIABLE_NAME=app
ENV HOST=0.0.0.0
ENV PORT=80
ENV WEB_CONCURRENCY=1
CMD gunicorn -k uvicorn.workers.UvicornWorker ${MODULE_NAME}:${VARIABLE_NAME} --bind ${HOST}:${PORT} --workers ${WEB_CONCURRENCY}
