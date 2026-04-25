# News Pipeline

Financial news scraper → LLM summarizer → multi-platform pusher.
See `docs/superpowers/specs/2026-04-25-news-pipeline-design.md`.

## Quick start
uv sync
cp config/secrets.yml.example config/secrets.yml && vim config/secrets.yml
uv run alembic upgrade head
uv run python -m news_pipeline.main
