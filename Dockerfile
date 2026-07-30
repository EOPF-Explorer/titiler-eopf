# Wolfi's apk repo is fully open — no Chainguard subscription needed. ":latest"
# is the only free tag, so the digest below is the version pin; Dependabot's
# "docker" ecosystem (.github/dependabot.yml) is the only thing that moves it.
FROM cgr.dev/chainguard/wolfi-base:latest@sha256:003627df3c1e1bba0c4116afcddb314aca9594ee2328c7e876a8081a6c988b2e

# Declared AFTER "FROM" on purpose: an ARG before the first FROM is in scope for
# FROM only, so the RUN below would expand it to "" and run `apk add python-`.
ARG PYTHON_VERSION=3.12

# Versions deliberately unpinned: Wolfi rolls forward and garbage-collects old
# versions, so an "=<version>" pin breaks the build within days (hadolint would
# need --ignore DL3018). The guardrails are the version-scoped names plus the
# digest above.
#   libstdc++  NOT optional, and not obviously needed: the rasterio/pyproj/duckdb
#              manylinux wheels list libstdc++.so.6 in DT_NEEDED and auditwheel
#              does not vendor it. Nothing else here pulls it in deliberately —
#              only mpdecimal, via python-3.12-base's `decimal` module.
#   bash, tzdata, curl  parity with the old Debian base: /bin/sh is busybox,
#              Wolfi ships no /usr/share/zoneinfo, curl is for in-pod debugging.
RUN apk add --no-cache \
      python-${PYTHON_VERSION} py${PYTHON_VERSION}-pip \
      libstdc++ bash tzdata curl

# Ahead of the COPY below so a code change does not reinstall these. No venv and
# no PATH wiring needed: Wolfi's python ships no EXTERNALLY-MANAGED marker and
# apk's pip puts console scripts in /usr/bin, so `uvicorn` resolves as a bare
# binary — which is what the chart's `command: ["uvicorn"]` requires.
RUN python -m pip install --no-cache-dir uvicorn uvicorn-worker gunicorn

WORKDIR /tmp

COPY titiler/ titiler/
COPY pyproject.toml README.md LICENSE ./

RUN python -m pip install --no-cache-dir ".[cache,openeo]" \
 && rm -rf titiler/ pyproject.toml README.md LICENSE

# No USER directive on purpose: the chart renders securityContext:{} and passes
# --port 80, so uid 0 is load-bearing (non-root cannot bind <1024 without
# NET_BIND_SERVICE). Hardening needs a coordinated change across
# helm/charts/values.yaml and platform-deploy
# core/titiler-eopf/hr-titiler-eopf{,-test}.yaml.

###################################################
# For compatibility (might be removed at one point)
ENV MODULE_NAME=titiler.eopf.main
ENV VARIABLE_NAME=app
ENV HOST=0.0.0.0
ENV PORT=80
ENV WEB_CONCURRENCY=1
CMD gunicorn -k uvicorn.workers.UvicornWorker ${MODULE_NAME}:${VARIABLE_NAME} --bind ${HOST}:${PORT} --workers ${WEB_CONCURRENCY}
