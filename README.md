# News Pipeline

Financial news scraper → LLM summarizer → multi-platform pusher.

## Documentation

Comprehensive docs at `docs/` (browse via mkdocs):

```bash
uv sync --group dev
uv run mkdocs serve
# open http://localhost:8000
```

Or browse the published site: (link tbd if hosted later)

Key pages:
- [Overview](docs/getting-started/overview.md) — what the system does
- [Architecture](docs/getting-started/architecture.md) — data flow and component map
- [LLM Pipeline](docs/components/llm-pipeline.md) — 4-tier routing and cost tracking
- [Daily Ops](docs/operations/daily-ops.md) — common commands
- [Troubleshooting](docs/operations/troubleshooting.md) — known issues and fixes

## Quick start

```bash
uv sync
cp config/secrets.yml.example config/secrets.yml && vim config/secrets.yml
uv run alembic upgrade head
uv run python -m news_pipeline.main
```

## Operations

See `docs/runbook/operations.md` for bootstrapping and routine ops.
See `docs/runbook/backup.md` for backup configuration.
See `docs/` for comprehensive mkdocs documentation.
