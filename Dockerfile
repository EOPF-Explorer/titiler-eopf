# Chainguard Wolfi base. Wolfi's apk repository is fully open — no Chainguard
# subscription is needed for anything in this file.
#
# ":latest" is the only free Chainguard tag, so the digest below IS the version
# pin, not a belt-and-braces extra: without it this line would float. Dependabot
# bumps it weekly via the "docker" ecosystem in .github/dependabot.yml — if that
# entry is ever removed, this pin silently rots instead of failing loudly.
# The digest is the multi-arch OCI index, so it resolves on amd64 and arm64.
FROM cgr.dev/chainguard/wolfi-base:latest@sha256:003627df3c1e1bba0c4116afcddb314aca9594ee2328c7e876a8081a6c988b2e

# Declared AFTER "FROM" on purpose. An ARG before the first FROM is in scope for
# FROM only, so referencing it in the RUN below would expand to the empty string
# and quietly run `apk add python- py-pip`. python-3.13/py3.13-pip also exist in
# Wolfi, so this stays a real knob.
ARG PYTHON_VERSION=3.12

# apk versions are deliberately NOT pinned. Wolfi rolls forward and garbage-
# collects old versions, so an "=<version>" pin breaks the build within days.
# The guardrails are the version-scoped package NAMES below plus the digest pin
# above; a hadolint run here would need --ignore DL3018.
#
#   libstdc++  REQUIRED, and not for anything obvious. The manylinux wheels list
#              libstdc++.so.6 in DT_NEEDED for rasterio.libs/libgdal-*.so.38,
#              pyproj.libs/libproj-*.so.25 and duckdb, and auditwheel does not
#              vendor it. Nothing installed here declares so:libstdc++.so.6
#              except mpdecimal, which is present only because python-3.12-base
#              wants it for the `decimal` module — so without this line the
#              whole geo stack hangs off an unrelated stdlib module's
#              dependency. A green build proves nothing about this. Do not
#              remove.
#   bash       Parity with the Debian base: /bin/sh here is busybox, so
#              `kubectl exec -- bash` would break without it.
#   tzdata     Parity: the Debian base shipped /usr/share/zoneinfo, Wolfi does
#              not. Python's zoneinfo happens to survive via the PyPI tzdata
#              that pandas drags in, but C-level localtime/TZ would silently
#              become UTC.
#   curl       Parity for in-pod debugging. Kubernetes probes use httpGet, so
#              this is not on the liveness path — it is for humans.
RUN apk add --no-cache \
      python-${PYTHON_VERSION} py${PYTHON_VERSION}-pip \
      libstdc++ bash tzdata curl

WORKDIR /tmp

COPY titiler/ titiler/
COPY pyproject.toml README.md LICENSE ./

# No venv and no PATH wiring: Wolfi's python-3.12 ships no EXTERNALLY-MANAGED
# marker and apk's pip puts console scripts straight in /usr/bin, so `uvicorn`
# resolves as a bare binary. That matters because all three HelmReleases run
# `command: ["uvicorn"]` — a venv without PATH wiring would pass every build and
# fail only on rollout. docker/smoke-test.sh asserts it (check C1).
RUN python -m pip install --no-cache-dir uvicorn uvicorn-worker gunicorn \
 && python -m pip install --no-cache-dir ".[cache,openeo]" \
 && rm -rf titiler/ pyproject.toml README.md LICENSE

# There is deliberately NO "USER" directive. uid 0 is load-bearing: the in-repo
# chart renders securityContext:{} and passes --port 80, and a non-root uid
# cannot bind <1024 without NET_BIND_SERVICE. Adding USER here would crashloop
# titiler-eopf (40 replicas) and titiler-eopf-test on rollout. Hardening to
# nonroot is a coordinated, per-release change across helm/charts/values.yaml
# and platform-deploy core/titiler-eopf/hr-titiler-eopf{,-test}.yaml. The
# upstream titiler-openeo chart already sets
# net.ipv4.ip_unprivileged_port_start=0, so that one release would survive on
# its own — which is precisely why this cannot be fixed image-side.

###################################################
# For compatibility (might be removed at one point)
ENV MODULE_NAME=titiler.eopf.main
ENV VARIABLE_NAME=app
ENV HOST=0.0.0.0
ENV PORT=80
ENV WEB_CONCURRENCY=1
CMD gunicorn -k uvicorn.workers.UvicornWorker ${MODULE_NAME}:${VARIABLE_NAME} --bind ${HOST}:${PORT} --workers ${WEB_CONCURRENCY}
