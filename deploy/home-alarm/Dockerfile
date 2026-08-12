FROM ghcr.io/astral-sh/uv:0.10.9 AS uv

FROM python:3.12-slim AS builder

COPY --from=uv /uv /uvx /bin/
WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY src ./src
RUN uv sync --frozen --no-dev

FROM python:3.12-slim AS runtime

RUN groupadd --gid 10001 alarm \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin alarm \
    && mkdir /data \
    && chown 10001:10001 /data

WORKDIR /app
COPY --from=builder --chown=10001:10001 /app/.venv ./.venv
COPY --from=builder --chown=10001:10001 /app/src ./src

USER 10001:10001
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["/app/.venv/bin/python", "-m", "ruview_alarm.healthcheck"]
CMD ["/app/.venv/bin/python", "-m", "ruview_alarm"]
