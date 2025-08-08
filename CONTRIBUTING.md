# Development - Contributing

Issues and pull requests are more than welcome: https://github.com/EOPF-Explorer/titiler-eopf/issues

**dev install**

```bash
git clone https://github.com/EOPF-Explorer/titiler-eopf.git
cd titiler-eopf

python -m pip install -e .["dev,test"]
```

You can then run the tests with the following command:

```sh
python -m pytest --cov titiler.eopf --cov-report term-missing
```

This repo is set to use `pre-commit` to run for type and lint checks:

```bash
$ pre-commit install
```
