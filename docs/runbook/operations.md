# Operations Runbook

## Bootstrapping a new server

1. SSH into 阿里云轻量服务器 (Ubuntu 22.04, 2c2g+).
2. `apt update && apt install -y docker.io docker-compose-v2 sqlite3 ossutil`
3. `git clone <repo> /opt/news_pipeline && cd /opt/news_pipeline`
4. `cp config/secrets.yml.example config/secrets.yml && vim config/secrets.yml` — fill in real tokens
5. `mkdir -p data logs secrets`
6. Move secrets to its own dir: `mv config/secrets.yml secrets/secrets.yml`
7. `docker compose -f docker/compose.yml up -d`
8. `docker compose logs -f`
9. Configure host cron (see `backup.md`)

## Routine ops

- Add a stock: send `/watch NVDA` to your TG/飞书 bot
- See cost: send `/cost`
- Force a digest: send `/digest now`
- Pause a flaky source: `/pause xueqiu 60`
- Tail logs: `docker compose logs -f --tail=200`
- Inspect SQLite: `sqlite3 data/news.db "SELECT count(*) FROM raw_news;"`

## Upgrading

```bash
git pull
docker compose -f docker/compose.yml build
docker compose -f docker/compose.yml up -d
```

## Troubleshooting

| Symptom | Action |
|---|---|
| Bark alerts saying "scrape_recent_15min" | Check `select source, count(*) from raw_news where fetched_at > datetime('now','-30min') group by source;` |
| Repeated 401 from xueqiu/ths | Cookie expired; refresh `secrets.yml` xueqiu_cookie/ths_cookie + restart |
| Cost ceiling tripped daily | Check `daily_metrics` for which tier is over-spending; consider tier2 → tier1 demotion via prompt change |
| Telegram "Bad Request: chat not found" | Ensure bot was added to the chat; verify chat_id |

## Smoke deploy to 阿里云轻量 (manual steps — Task 75)

These steps require real SSH access and secrets and cannot be automated here.

### Step 1: Sync repo to server

```bash
ssh user@server "mkdir -p /opt/news_pipeline"
rsync -avz --exclude='.venv' --exclude='__pycache__' --exclude='data' \
  --exclude='secrets' ./ user@server:/opt/news_pipeline/
```

### Step 2: Configure secrets

```bash
ssh user@server
cd /opt/news_pipeline
mkdir -p secrets data logs
cp config/secrets.yml.example secrets/secrets.yml
vim secrets/secrets.yml   # paste real values
chmod 600 secrets/secrets.yml
```

### Step 3: First run

```bash
docker compose -f docker/compose.yml build
docker compose -f docker/compose.yml up -d
docker compose -f docker/compose.yml logs -f
```

Expected within 5 min:
- `scheduler_started` log line listing ~12 jobs
- `scrape_done` lines for each enabled source
- Eventually: `archive_failed` warning if 飞书 bitable token wrong, but main pipeline still moves
- After ~30 min: an actual push lands in your TG/飞书

### Step 4: Validate end-to-end

Send `/list` to your bot — expect watchlist response.
Send `/cost` — expect "今日 LLM 成本: 0.XX CNY".
Wait for first critical news — confirm three platforms received it.

### Step 5: Configure host cron + finalize

```bash
crontab -e
# Add backup cron from docs/runbook/backup.md
```

Send Bark notification: `curl https://api.day.app/$BARK_TOKEN/MVP%20deployed/news_pipeline%20live`.

Tag production deployment:

```bash
git tag -a v0.1.0-deployed -m "MVP deployed to production"
git push --tags
```
