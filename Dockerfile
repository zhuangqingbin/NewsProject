# Multi-stage build. Compatible with both classic Docker builder and BuildKit.
#
# CN network? Speed up with:
#   docker build --build-arg UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ .

FROM python:3.12-slim AS builder

ARG UV_INDEX_URL=
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_INDEX_URL=${UV_INDEX_URL} \
    UV_HTTP_TIMEOUT=300

# gcc needed for C-extension wheels (pyahocorasick) on platforms with no prebuilt wheel.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install uv via pip (works on any builder; no BuildKit-only features).
RUN pip install --no-cache-dir ${UV_INDEX_URL:+--index-url ${UV_INDEX_URL}} uv==0.5.11

WORKDIR /app

# Resolve deps first (cacheable layer)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Install the project itself (alembic migrations live under src/news_pipeline/storage/migrations/)
COPY src/ ./src/
COPY alembic.ini ./
RUN uv sync --frozen --no-dev


FROM python:3.12-slim AS runtime

# CJK fonts so matplotlib charts render Chinese characters
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    NEWS_PIPELINE_CONFIG_DIR=/app/config \
    NEWS_PIPELINE_DB=/app/data/news.db

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src
COPY --from=builder /app/alembic.ini /app/alembic.ini

RUN mkdir -p /app/config /app/data /app/logs

COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["python", "-m", "news_pipeline.main"]
