#!/usr/bin/env bash
#
# smoke-test.sh — assert the *runtime contract* of the titiler-eopf image.
#
#   ./docker/smoke-test.sh <image-ref>
#
# Checks what a green `docker build` does not: what callers of the image rely on.
# The expectations come from helm/charts/, docker-compose.yml, and the
# HelmReleases in platform-deploy that run this image (deliberately written down
# here rather than read from the chart — a contract test that derives its
# expectations from the thing under test asserts nothing).
#
# Every `docker run` passes --platform: the published image is amd64-only, so an
# unqualified run on an arm64 laptop tests a different image than ships.
#
# Env:
#   SMOKE_PLATFORM   platform to test (default linux/amd64)
#   SMOKE_TIMEOUT    seconds to wait for a container to serve HTTP (default 180;
#                    generous because amd64-on-arm64 runs under QEMU)

set -euo pipefail

IMAGE="${1:-}"
if [[ -z "$IMAGE" ]]; then
  echo "usage: $0 <image-ref>" >&2
  exit 2
fi

PLATFORM="${SMOKE_PLATFORM:-linux/amd64}"
HTTP_TIMEOUT="${SMOKE_TIMEOUT:-180}"

for tool in docker curl; do
  command -v "$tool" >/dev/null || { echo "$0: required tool not found: $tool" >&2; exit 2; }
done

# ---------------------------------------------------------------- scaffolding

PASS=0
FAILED_NAMES=()
CONTAINERS=()
WORKDIR="$(mktemp -d)"

cleanup() {
  if ((${#CONTAINERS[@]})); then
    docker rm -f "${CONTAINERS[@]}" >/dev/null 2>&1 || true
  fi
  rm -rf "$WORKDIR"
}
trap cleanup EXIT

# run_check <name> <function>  — the function's exit status is the verdict, and
# its combined output is shown only on failure.
run_check() {
  local name="$1" fn="$2" out
  if out="$("$fn" 2>&1)"; then
    PASS=$((PASS + 1))
    printf 'ok:   %s\n' "$name"
  else
    FAILED_NAMES+=("$name")
    printf 'FAIL: %s\n' "$name"
    if [[ -n "$out" ]]; then
      printf '%s\n' "$out" | sed 's/^/        /'
    fi
  fi
}

drun() { docker run --rm --platform "$PLATFORM" "$@"; }

# pyrun [docker-opts...] — reads the Python program on stdin. Uses an explicit
# --entrypoint so it exercises the same override path Kubernetes uses.
pyrun() { docker run --rm -i --platform "$PLATFORM" "$@" --entrypoint python "$IMAGE" -; }

# start_server <label> [docker-opts...] -- [cmd...]
# Publishes container port 80 on an ephemeral loopback port and echoes the
# container name. The caller polls it with the host's curl, as a real client would.
start_server() {
  local label="$1"; shift
  local name="smoke-${label}-$$"
  docker rm -f "$name" >/dev/null 2>&1 || true
  docker run -d --name "$name" --platform "$PLATFORM" -p 127.0.0.1::80 "$@" >/dev/null
  CONTAINERS+=("$name")
  echo "$name"
}

# wait_http <container> <path> — polls the container's published port until
# <path> answers 2xx/3xx, giving up early if the container has already died so a
# broken image fails fast instead of burning the whole timeout.
wait_http() {
  local name="$1" path="$2" url deadline
  url="http://127.0.0.1:$(docker port "$name" 80/tcp | head -n1 | sed 's/.*://')${path}"
  deadline=$((SECONDS + HTTP_TIMEOUT))
  while ((SECONDS < deadline)); do
    if [[ "$(docker inspect -f '{{.State.Running}}' "$name" 2>/dev/null)" != "true" ]]; then
      echo "container $name exited before serving $url; logs:"
      docker logs "$name" 2>&1 | tail -n 30
      return 1
    fi
    if curl -fsS -o /dev/null --max-time 3 "$url"; then
      return 0
    fi
    sleep 1
  done
  echo "timed out after ${HTTP_TIMEOUT}s waiting for $url; logs:"
  docker logs "$name" 2>&1 | tail -n 30
  return 1
}

# The apps instantiate their pydantic Settings at *module* scope, so importing
# them without these raises ValidationError. That is true of the current image
# too — it is app behaviour, not image behaviour, so the contract test supplies
# the env rather than treating it as a failure.
#   titiler/eopf/dependencies.py  -> DataStoreSettings()
#   titiler/eopf/openeo/main.py   -> BackendSettings()
RASTER_ENV=(-e TITILER_API_STAC_API_URL=https://api.explorer.eopf.copernicus.eu/stac)
OPENEO_ENV=(
  -e TITILER_OPENEO_STAC_API_URL=https://api.explorer.eopf.copernicus.eu/stac
  -e TITILER_OPENEO_STORE_URL=/services/store.json
)

# ---------------------------------------------------------------- fixtures

mkdir -p "$WORKDIR/config" "$WORKDIR/services"

# A minimal service store, so the openeo app can be exercised without reaching
# the network or depending on the repo's services/*.json fixtures.
echo '{"services": {}}' > "$WORKDIR/services/store.json"

# Shaped like the ConfigMap the titiler-openeo release mounts at /config and
# passes to `uvicorn --log-config`.
cat > "$WORKDIR/config/log_config.yaml" <<'YAML'
version: 1
disable_existing_loggers: false
formatters:
  default:
    format: '%(asctime)s %(levelname)s %(name)s %(message)s'
handlers:
  default:
    class: logging.StreamHandler
    formatter: default
    stream: ext://sys.stdout
loggers:
  uvicorn:
    handlers: [default]
    level: INFO
    propagate: false
  uvicorn.access:
    handlers: [default]
    level: INFO
    propagate: false
root:
  handlers: [default]
  level: INFO
YAML

CONFIG_MOUNT=(-v "$WORKDIR/config:/config:ro")
SERVICES_MOUNT=(-v "$WORKDIR/services:/services:ro")

# ---------------------------------------------------------------- the checks

# C1 — Kubernetes runs `command: ["uvicorn"]`, i.e. a binary, not a module. A
# venv without PATH wiring breaks production on rollout while every build and
# unit test stays green. Running it as the entrypoint proves PATH resolution.
check_c1_uvicorn_on_path() {
  drun --entrypoint uvicorn "$IMAGE" --version
}

# C1b — the image's own CMD uses gunicorn with the uvicorn worker class.
check_c1b_gunicorn_and_worker() {
  drun --entrypoint gunicorn "$IMAGE" --version
  pyrun <<'PY'
import uvicorn.workers  # noqa: F401  the class named in the CMD
import uvicorn_worker   # noqa: F401  the maintained replacement package
PY
}

# C2 — the module both titiler-eopf releases pass to uvicorn.
check_c2_raster_app_importable() {
  pyrun "${RASTER_ENV[@]}" <<'PY'
from fastapi import FastAPI
from titiler.eopf.main import app
assert isinstance(app, FastAPI), type(app)
assert any(getattr(r, "path", None) == "/_mgmt/ping" for r in app.routes), "no /_mgmt/ping route"
PY
}

# C3 — the module the titiler-openeo release passes to uvicorn, and the only
# consumer of the `openeo` extra.
check_c3_openeo_app_importable() {
  pyrun "${OPENEO_ENV[@]}" "${SERVICES_MOUNT[@]}" <<'PY'
from fastapi import FastAPI
from titiler.eopf.openeo.main import app
assert isinstance(app, FastAPI), type(app)
PY
}

# C4 — /bin/sh must exist: the image's CMD is shell-form and expands
# ${MODULE_NAME} etc., so a distroless base would break the bare `docker run`
# path even though Kubernetes (which overrides command/args) would not notice.
check_c4_shell_present() {
  # Runs *via* /bin/sh, so reaching the test at all proves the shell exists.
  # Single quotes are deliberate: these must be expanded by the container's
  # shell against the image's ENV, not by ours.
  # shellcheck disable=SC2016
  drun --entrypoint sh "$IMAGE" -c 'test -n "${MODULE_NAME}" && test -n "${VARIABLE_NAME}" && test "${PORT}" = 80'
}

# C4b — the default CMD end to end: shell expansion + gunicorn + uvicorn
# worker + binding :80 as nonroot. This is the `docker run <image>` contract.
# Note it does NOT cover the Kubernetes path: Docker defaults
# net.ipv4.ip_unprivileged_port_start to 0, so :80 binds here with no sysctl,
# whereas containerd does not — that is what the chart's podSecurityContext is
# for, and only a real rollout exercises it.
check_c4b_default_cmd_serves() {
  local name
  name="$(start_server cmd "${RASTER_ENV[@]}" "$IMAGE")"
  wait_http "$name" /_mgmt/ping
}

# C5 — the image runs as wolfi-base's `nonroot` (uid 65532), not root. Binding
# :80 as an unprivileged user needs the runtime to allow low ports: the chart
# sets net.ipv4.ip_unprivileged_port_start=80 per pod, and Docker already
# defaults it to 0 (which is why C4b and C8 bind :80 here without help).
# The uid is pinned rather than merely asserted non-zero because the chart's
# podSecurityContext and any runAsUser/PSA policy name that number — a base
# image that renumbered `nonroot` would break the deployment while a bare
# "not 0" check stayed green.
check_c5_runs_as_nonroot() {
  local uid
  uid="$(drun --entrypoint id "$IMAGE" -u)"
  [[ "$uid" == "65532" ]] || { echo "expected uid 65532 (nonroot), got '$uid'"; return 1; }
}

# C6 — GDAL/VSI scratch space. CPL_TMPDIR=/tmp in compose, and WORKDIR is /tmp.
check_c6_tmp_writable() {
  drun --entrypoint sh "$IMAGE" -c 'echo probe > /tmp/.smoke && test -s /tmp/.smoke && rm /tmp/.smoke'
}

# C7 — the releases set GDAL_*/VSI_*/CPL_* env vars. Assert they reach the
# *vendored* GDAL inside the rasterio wheel. The raw env var is
# not observable without a remote dataset, so read it back through
# rasterio.Env(), which is the layer that actually consumes it.
check_c7_gdal_config_honoured() {
  pyrun -e GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR -e GDAL_INGESTED_BYTES_AT_OPEN=32768 <<'PY'
import rasterio
with rasterio.Env():
    got = rasterio.env.get_gdal_config("GDAL_DISABLE_READDIR_ON_OPEN")
    assert got == "EMPTY_DIR", f"GDAL_DISABLE_READDIR_ON_OPEN not honoured: {got!r}"
    got = rasterio.env.get_gdal_config("GDAL_INGESTED_BYTES_AT_OPEN")
    assert str(got) == "32768", f"GDAL_INGESTED_BYTES_AT_OPEN not honoured: {got!r}"
print("gdal", rasterio.__gdal_version__, "proj", rasterio.__proj_version__)
PY
}

# C8 — the liveness/readiness probe of both titiler-eopf releases, reached the
# way Kubernetes reaches it: `command: uvicorn`, args from values.yaml, :80.
check_c8_raster_probe_on_80() {
  local name
  name="$(start_server raster "${RASTER_ENV[@]}" --entrypoint uvicorn "$IMAGE" \
    titiler.eopf.main:app --host 0.0.0.0 --port 80 --workers 1)"
  wait_http "$name" /_mgmt/ping
}

# C8b — the openeo release probes /api, NOT /_mgmt/ping: that route exists only
# in titiler/eopf/main.py and the openeo app does not have it. Also runs the
# release's real extra args (--log-config against the read-only /config mount,
# --forwarded-allow-ips, --timeout-keep-alive), so a log config that fails to
# parse shows up here rather than as a pod that never becomes Ready.
check_c8b_openeo_probe_on_80() {
  local name
  name="$(start_server openeo "${OPENEO_ENV[@]}" "${SERVICES_MOUNT[@]}" "${CONFIG_MOUNT[@]}" \
    --entrypoint uvicorn "$IMAGE" \
    titiler.eopf.openeo.main:app --host 0.0.0.0 --port 80 --workers 1 \
    --proxy-headers --forwarded-allow-ips '*' \
    --log-config /config/log_config.yaml --timeout-keep-alive 600)"
  wait_http "$name" /api
}

# C9 — the /config read-only mount is a live dependency of the openeo release.
# Only the mount semantics are checked here; C8b already parses the same file for
# real by handing it to `uvicorn --log-config`.
# The write must be rejected with EROFS specifically. Now that the image runs
# as nonroot, a plain `except OSError` would also swallow the EACCES you get
# from a read-WRITE mount whose host directory belongs to another uid — which
# is exactly the case on CI, where the runner owns the fixture. That would let
# the check pass while proving nothing about :ro.
check_c9_config_mount_readable() {
  pyrun "${CONFIG_MOUNT[@]}" <<'PY'
import errno

assert open("/config/log_config.yaml").read(), "/config/log_config.yaml unreadable or empty"

try:
    open("/config/.smoke-write", "w").close()
except OSError as exc:
    if exc.errno != errno.EROFS:
        raise AssertionError(
            f"/config rejected the write with {errno.errorcode.get(exc.errno, exc.errno)}, "
            "not EROFS; the mount is not read-only"
        ) from exc
else:
    raise AssertionError("/config was writable; the release mounts it read-only")
PY
}

# C10 — asserted as a NEGATIVE on purpose. Nothing in titiler/ or tests/
# imports osgeo, and GDAL reaches this image only as the copy vendored inside
# the rasterio wheel. If a future change pulls in apk gdal-py3.12 or the GDAL
# PyPI package, two GDALs would be loaded in one process; this makes that loud
# instead of a mysterious segfault.
check_c10_osgeo_absent() {
  pyrun <<'PY'
try:
    import osgeo
except ImportError:
    pass
else:
    raise AssertionError(f"osgeo is unexpectedly present at {osgeo.__file__}")
PY
}

# C11 — the openeo release runs against a real Postgres (bitnami subchart).
# psycopg2-binary is a wheel with a vendored libpq, so assert the extension
# module loads and reports a libpq version rather than just importing.
check_c11_openeo_extras() {
  pyrun <<'PY'
import psycopg2
import sqlalchemy

assert psycopg2.__libpq_version__ >= 90000, psycopg2.__libpq_version__
url = sqlalchemy.engine.url.make_url("postgresql+psycopg2://u:p@db:5432/openeo")
assert sqlalchemy.create_engine(url).dialect.driver == "psycopg2"

import duckdb

assert duckdb.connect().execute("select 1").fetchone() == (1,)
PY
}

# --- native libraries, exercised rather than imported -----------------------
# `import rasterio` succeeds with a broken driver or a missing proj.db. These
# checks are the ones that would actually catch a base-image change breaking
# the manylinux wheels' vendored .so files.

check_native_pyproj_transform() {
  pyrun <<'PY'
from pyproj import Transformer

x, y = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True).transform(2.3522, 48.8566)
assert abs(x - 261845.7) < 1.0, x
assert abs(y - 6250564.3) < 1.0, y
PY
}

check_native_rasterio_gtiff_roundtrip() {
  pyrun <<'PY'
import numpy as np
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

want = np.arange(64, dtype="uint8").reshape(8, 8)
with MemoryFile() as mem:
    with mem.open(
        driver="GTiff", width=8, height=8, count=1, dtype="uint8",
        crs="EPSG:4326", transform=from_origin(-180, 90, 1, 1),
    ) as dst:
        dst.write(want, 1)
    with mem.open() as src:
        assert src.crs.to_epsg() == 4326, src.crs
        np.testing.assert_array_equal(src.read(1), want)
PY
}

check_native_zarr_roundtrip() {
  pyrun <<'PY'
import tempfile

import zarr

path = tempfile.mkdtemp()
arr = zarr.open(path, mode="w", shape=(8, 8), chunks=(4, 4), dtype="i4")
arr[:] = 7
del arr
assert zarr.open(path, mode="r")[0, 0] == 7

import obstore  # noqa: F401  the object-store backend zarr reads S3 through
PY
}

check_native_crypto_and_orjson() {
  pyrun <<'PY'
import orjson
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes

digest = hashes.Hash(hashes.SHA256(), backend=default_backend())
digest.update(b"smoke")
assert len(digest.finalize()) == 32

assert orjson.loads(orjson.dumps({"a": [1, 2.5, None]})) == {"a": [1, 2.5, None]}
PY
}

# ---------------------------------------------------------------- run

echo "smoke-testing $IMAGE (platform $PLATFORM)"
echo

CHECKS=(
  "C1   uvicorn is an executable on PATH|check_c1_uvicorn_on_path"
  "C1b  gunicorn on PATH, uvicorn worker importable|check_c1b_gunicorn_and_worker"
  "C2   titiler.eopf.main:app imports, has /_mgmt/ping|check_c2_raster_app_importable"
  "C3   titiler.eopf.openeo.main:app imports|check_c3_openeo_app_importable"
  "C4   /bin/sh present and CMD vars expand|check_c4_shell_present"
  "C4b  default shell-form CMD serves /_mgmt/ping|check_c4b_default_cmd_serves"
  "C5   runs as nonroot (uid 65532)|check_c5_runs_as_nonroot"
  "C6   /tmp is writable|check_c6_tmp_writable"
  "C7   GDAL_* env reaches the vendored GDAL|check_c7_gdal_config_honoured"
  "C8   uvicorn serves /_mgmt/ping on :80|check_c8_raster_probe_on_80"
  "C8b  openeo serves /api on :80 with --log-config|check_c8b_openeo_probe_on_80"
  "C9   /config mount is readable and read-only|check_c9_config_mount_readable"
  "C10  osgeo is ABSENT|check_c10_osgeo_absent"
  "C11  psycopg2 + sqlalchemy + duckdb work|check_c11_openeo_extras"
  "NAT  pyproj 4326->3857 numerically correct|check_native_pyproj_transform"
  "NAT  rasterio GTiff write/read roundtrip|check_native_rasterio_gtiff_roundtrip"
  "NAT  zarr write/open roundtrip, obstore imports|check_native_zarr_roundtrip"
  "NAT  cryptography backend + orjson|check_native_crypto_and_orjson"
)

for entry in "${CHECKS[@]}"; do
  run_check "${entry%%|*}" "${entry##*|}"
done

echo
echo "passed: $PASS   failed: ${#FAILED_NAMES[@]}"
if ((${#FAILED_NAMES[@]})); then
  echo "failing checks:"
  printf '  - %s\n' "${FAILED_NAMES[@]}"
  exit 1
fi
echo "runtime contract satisfied by $IMAGE"
