ARG PYTHON_VERSION=3.12

FROM python:${PYTHON_VERSION}
RUN apt update && apt upgrade -y \
  && apt install curl -y \
  && rm -rf /var/lib/apt/lists/*

RUN python -m pip install -U pip
RUN python -m pip install uvicorn uvicorn-worker gunicorn

WORKDIR /tmp

COPY titiler/ titiler/
COPY pyproject.toml pyproject.toml
COPY README.md README.md
COPY LICENSE LICENSE

RUN echo "yo"
RUN python -m pip install ".[cache,openeo]" --no-cache-dir --upgrade
RUN rm -rf titiler/ pyproject.toml README.md LICENSE

###################################################
# For compatibility (might be removed at one point)
ENV MODULE_NAME=titiler.eopf.main
ENV VARIABLE_NAME=app
ENV HOST=0.0.0.0
ENV PORT=80
ENV WEB_CONCURRENCY=1
CMD gunicorn -k uvicorn.workers.UvicornWorker ${MODULE_NAME}:${VARIABLE_NAME} --bind ${HOST}:${PORT} --workers ${WEB_CONCURRENCY}
