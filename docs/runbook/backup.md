# SQLite Backup Runbook

## Daily SQLite backup to OSS

The backup runs as a **host cron job** (not inside the Docker container) — simpler, no cron daemon needed in the slim image.

### Prerequisites

1. Install `ossutil64` on the host:
   ```bash
   wget https://gosspublic.alicdn.com/ossutil/1.7.17/ossutil64
   chmod +x ossutil64
   mv ossutil64 /usr/local/bin/ossutil64
   ossutil64 config   # enter AccessKey ID / Secret + endpoint
   ```

2. Ensure `sqlite3` is installed:
   ```bash
   apt install -y sqlite3
   ```

### Add host cron entry

```cron
0 3 * * * cd /opt/news_pipeline && \
  OSS_BUCKET=news-charts OSS_ENDPOINT=oss-cn-hangzhou.aliyuncs.com \
  NEWS_PIPELINE_DB=data/news.db ./scripts/backup_sqlite.sh \
  >> logs/backup.log 2>&1
```

Add with `crontab -e`.

Verify after the first run:
```bash
tail -f logs/backup.log
```

Expected output:
```
backup OK: news_20260425T030000Z.db.gz
```

### Retention

The script automatically deletes backups older than 30 days from the OSS bucket.

### Manual restore

To restore a specific backup:
```bash
./scripts/restore_sqlite.sh oss://news-charts/backups/news_20260425T030000Z.db.gz
# optionally specify a target path:
./scripts/restore_sqlite.sh oss://news-charts/backups/news_20260425T030000Z.db.gz data/news.db
```

The previous database file is saved as `data/news.db.before-restore` before overwriting.

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `NEWS_PIPELINE_DB` | `data/news.db` | Path to SQLite database |
| `OSS_BUCKET` | _(required)_ | OSS bucket name |
| `OSS_ENDPOINT` | _(required)_ | OSS endpoint (e.g. `oss-cn-hangzhou.aliyuncs.com`) |
| `OSSUTIL` | `ossutil64` | Path to ossutil binary |
