# News Pipeline

Financial news scraper → LLM summarizer → multi-platform pusher.

Sources (Caixin / SEC EDGAR / Finnhub / Juchao / Akshare / 雪球 / 同花顺 …) → dedup → rules engine (Aho-Corasick keyword match, v0.3.0) → optional LLM enrichment → push to Telegram / Feishu webhook + digest.

---

## One-shot deploy (Docker)

**Requirements:** Docker 24+ with Compose v2. ~2 GB RAM. Linux/macOS host.

```bash
git clone https://github.com/<you>/NewsProject.git
cd NewsProject

# 1. Fill in secrets (Telegram bot token, DashScope key, etc.)
cp config/secrets.yml.example config/secrets.yml
$EDITOR config/secrets.yml

# 2. (Optional) tweak watchlist / sources / channels
$EDITOR config/watchlist.yml
$EDITOR config/channels.yml

# 3. Start
docker compose up -d

# 4. Check it's alive
docker compose ps
docker compose logs -f app
```

That's it. The app runs as a long-lived process; Datasette browses the SQLite at <http://127.0.0.1:8001>.

### Slow build in CN networks?

```bash
docker compose build --build-arg UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
docker compose up -d
```

---

## What gets persisted

Three bind-mounts, all under the cloned repo dir:

| Path | Contents | Notes |
|---|---|---|
| `./config/` | yaml configs (you edit) | mounted **read-only** into container |
| `./data/` | `news.db` SQLite + state | persists across restarts; back this up |
| `./logs/` | structlog JSON output | rotate yourself or let it grow |

`docker compose down` keeps these. `docker compose down -v` does not affect bind mounts (only named volumes — we don't use any).

---

## Common ops

```bash
# Tail logs
docker compose logs -f app

# Restart after editing config (hot-reload also works for app.yml/watchlist.yml)
docker compose restart app

# Pull latest code + rebuild + restart
git pull
docker compose up -d --build

# Stop everything (data preserved)
docker compose down

# Inspect SQLite via Datasette
open http://127.0.0.1:8001          # local
ssh -L 8001:localhost:8001 server   # remote tunnel

# One-off CLI inside container (e.g. manual backfill)
docker compose exec app python -m news_pipeline.commands.<...>
```

---

## Local dev (without Docker)

```bash
uv sync --group dev
cp config/secrets.yml.example config/secrets.yml && $EDITOR config/secrets.yml
uv run alembic upgrade head
uv run python -m news_pipeline.main
```

Tests + lint:

```bash
uv run pytest
uv run ruff check src/ tests/
uv run mypy src/
```

---

## Documentation

Comprehensive docs at `docs/` — browse via mkdocs:

```bash
uv run mkdocs serve   # open http://localhost:8000
```

Key pages:
- [Overview](docs/getting-started/overview.md) — what the system does
- [Architecture](docs/getting-started/architecture.md) — data flow + component map
- [Rules Engine](docs/components/rules.md) — v0.3.0 keyword matching
- [LLM Pipeline](docs/components/llm-pipeline.md) — 4-tier routing + cost tracking
- [Daily Ops](docs/operations/daily-ops.md) — common commands
- [Troubleshooting](docs/operations/troubleshooting.md) — known issues
- [Configuration](docs/operations/configuration.md) — every yaml file explained
