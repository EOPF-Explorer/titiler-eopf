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
