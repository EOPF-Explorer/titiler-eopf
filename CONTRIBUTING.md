# Development - Contributing

Issues and pull requests are more than welcome: https://github.com/EOPF-Explorer/titiler-eopf/issues

We recommand using [`uv`](https://docs.astral.sh/uv) as project manager for development.

See https://docs.astral.sh/uv/getting-started/installation/ for installation 

**dev install**

```bash
git clone https://github.com/EOPF-Explorer/titiler-eopf.git
cd titiler-eopf

uv sync
```

You can then run the tests with the following command:

```sh
uv run pytest --cov titiler.eopf --cov-report term-missing
```

This repo is set to use `pre-commit` to run for type and lint checks:

```bash
uv run pre-commit install

# If needed, you can run pre-commit script manually 
uv run pre-commit run --all-files 
```

**container image scanning**

The `Docker and Helm` workflow scans the image with [Trivy](https://trivy.dev)
before pushing it, and fails on any *fixable* `CRITICAL` vulnerability. To
reproduce that gate locally:

```bash
docker build -t titiler-eopf:scan .

# Same gate as CI: non-zero exit on a fixable CRITICAL
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
  aquasec/trivy:0.69.3 image \
  --ignore-unfixed --vuln-type os,library --severity CRITICAL --exit-code 1 \
  titiler-eopf:scan
```

Drop `--ignore-unfixed` to also see vulnerabilities with no upstream fix yet;
those are reported to the GitHub Security tab but never block a build.

**image runtime contract**

The image is consumed as an API, not just as a build artefact: the HelmReleases
that run it override the entrypoint with `command: ["uvicorn"]`, run as uid 0,
bind port 80, mount `/config` read-only, and set ~20 `GDAL_*`/`VSI_*`/`CPL_*`
environment variables. A successful `docker build` proves none of that.
`docker/smoke-test.sh` does, and CI runs it between the Trivy gates and the push:

```bash
docker build --platform linux/amd64 -t titiler-eopf:dev .
./docker/smoke-test.sh titiler-eopf:dev
```

It prints one `ok:`/`FAIL:` line per check and exits non-zero if any fail. To see
what a failure looks like without breaking anything, point it at a base image:

```bash
./docker/smoke-test.sh python:3.12   # exits 1; no uvicorn, no titiler, no GDAL
```

Two things to know before editing it:

- Every `docker run` inside passes `--platform linux/amd64`. The published image
  is amd64-only, so on an Apple-silicon machine an unqualified run would build
  and test arm64 — a different image than the one that reaches the cluster.
  Expect it to be slow locally: those runs are QEMU-emulated. `SMOKE_TIMEOUT`
  (default 180s) raises the per-container HTTP wait if that is not enough.
- **If a change to the Dockerfile requires editing this script, the runtime
  contract changed.** That is not a reason to reach for the script — it is
  something to say out loud in the pull request, because a caller somewhere
  relies on whatever the check was asserting.
