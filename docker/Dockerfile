# docker/Dockerfile
FROM python:3.12-slim AS builder
WORKDIR /app
# Use Aliyun mirrors for faster apt + pip in CN network. Harmless elsewhere
# (just slightly slower if not on aliyun network).
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g; s|security.debian.org|mirrors.aliyun.com/debian-security|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y --no-install-recommends gcc git \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml uv.lock ./
ENV UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ uv && uv sync --frozen --no-dev

FROM python:3.12-slim
WORKDIR /app
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g; s|security.debian.org|mirrors.aliyun.com/debian-security|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y --no-install-recommends fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*
COPY --from=builder /app/.venv /app/.venv
COPY src/ ./src/
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENV PATH="/app/.venv/bin:$PATH" PYTHONPATH=/app/src
ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "-m", "news_pipeline.main"]
