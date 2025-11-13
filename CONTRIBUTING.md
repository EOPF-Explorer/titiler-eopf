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
