FROM ghcr.io/astral-sh/uv@sha256:0f36cb9361a3346885ca3677e3767016687b5a170c1a6b88465ec14aefec90aa AS uv

FROM python:3.11.11-slim@sha256:081075da77b2b55c23c088251026fb69a7b2bf92471e491ff5fd75c192fd38e5 AS builder

WORKDIR /backend

RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    libssl-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

COPY --from=uv /uv /uvx /usr/local/bin/

COPY pyproject.toml uv.lock ./
RUN NO_EXT=1 uv sync --frozen --no-dev \
    --no-binary-package cryptography \
    --no-binary-package pymongo

FROM python:3.11.11-slim@sha256:081075da77b2b55c23c088251026fb69a7b2bf92471e491ff5fd75c192fd38e5

WORKDIR /backend

RUN apt-get update && apt-get install -y \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system app \
    && useradd --system --gid app --home-dir /nonexistent --shell /usr/sbin/nologin app \
    && mkdir -p /backend/logs \
    && chown app:app /backend/logs

COPY --from=builder --chown=app:app /backend/.venv ./.venv
COPY --chown=app:app app ./app
COPY --chown=app:app migration ./migration
COPY --chown=app:app alembic.ini ./

ENV PATH="/backend/.venv/bin:${PATH}"
ENV PYTHONPATH="/backend"

USER app

EXPOSE 8000 9090
# 8000 = 사용자 트래픽 (FastAPI). 9090 = /metrics
# 9090 은 docker-compose 의 expose: 만 두고 ports: 절대 금지. monitoring-network 내부 / k8s NetworkPolicy 로만 도달.

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
