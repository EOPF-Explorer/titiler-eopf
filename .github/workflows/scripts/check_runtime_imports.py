"""Import every deployed ASGI app using only the production dependency closure.

The Docker image installs `--no-dev --extra server --extra cache --extra openeo`,
so anything that reaches the runtime *only* through the dev group is missing in
production. That is not hypothetical: titiler-openeo 0.18 moved `httpx` behind its
`oidc` extra, `bump-my-version` kept pulling httpx into the dev group, and the
openEO app crashed at import in staging while CI stayed green.

Run this in an environment synced WITHOUT the dev group. Nothing here touches the
network at import time; the settings below are placeholders that only need to be
well-formed enough for each module body to run to the end.
"""

import os
import sys

REPO = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
)

os.environ.setdefault("TITILER_EOPF_STAC_API_URL", "https://example.invalid/stac")
os.environ.setdefault("TITILER_OPENEO_STAC_API_URL", "https://example.invalid/stac")
os.environ.setdefault(
    "TITILER_OPENEO_STORE_URL", os.path.join(REPO, "services", "eopf-explorer.json")
)
# Exercise the cache backend. It is off by default, and while it is off the
# `cache` extra (redis, boto3) is never imported -- so a dependency dropped there
# would slip past this check exactly as httpx did. s3-redis is what production
# runs and it pulls both. Constructing the backends opens no connection.
os.environ.setdefault("TITILER_EOPF_CACHE_ENABLE", "true")
os.environ.setdefault("TITILER_EOPF_CACHE_BACKEND", "s3-redis")
os.environ.setdefault("TITILER_EOPF_CACHE_REDIS_HOST", "localhost")
os.environ.setdefault("TITILER_EOPF_CACHE_REDIS_PORT", "6379")
os.environ.setdefault("TITILER_EOPF_CACHE_S3_BUCKET", "ci-not-a-real-bucket")
os.environ.setdefault("TITILER_EOPF_CACHE_S3_REGION", "de")

# Our deployments run OIDC, and the OIDC branch is the one carrying optional-
# dependency guards, so exercise it rather than the "basic" default.
os.environ.setdefault("TITILER_OPENEO_AUTH_METHOD", "oidc")
os.environ.setdefault("TITILER_OPENEO_AUTH_OIDC_CLIENT_ID", "ci")
os.environ.setdefault(
    "TITILER_OPENEO_AUTH_OIDC_WK_URL",
    "https://example.invalid/.well-known/openid-configuration",
)
os.environ.setdefault(
    "TITILER_OPENEO_AUTH_OIDC_REDIRECT_URL", "https://example.invalid/"
)

APPS = ["titiler.eopf.main", "titiler.eopf.openeo.main"]

failures = []
for name in APPS:
    try:
        __import__(name)
    # Deliberately broad: the failure this guards against was an AssertionError
    # from an optional-dependency check, not an ImportError.
    except Exception as exc:
        failures.append(name)
        print(f"FAIL {name}\n     {type(exc).__name__}: {exc}", file=sys.stderr)
    else:
        print(f"ok   {name}")

if failures:
    print(
        f"\n{len(failures)} deployed app(s) cannot be imported from the production "
        "dependency closure. A runtime dependency is probably reaching the tests "
        "through the dev group only.",
        file=sys.stderr,
    )
    sys.exit(1)

print(f"\nall {len(APPS)} deployed apps import cleanly without the dev group")
