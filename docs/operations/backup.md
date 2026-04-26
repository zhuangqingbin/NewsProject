# Backup

这一页描述 SQLite 数据库的每日备份流程（host cron + 阿里云 OSS）。

---

## 备份策略

| 项目 | 策略 |
|---|---|
| 备份目标 | `/opt/news_pipeline/data/news.db` |
| 存储位置 | 阿里云 OSS Bucket |
| 触发方式 | Host cron（每天 03:00 UTC） |
| 格式 | gzip 压缩（`news_YYYYMMDDTHHMMSSZ.db.gz`） |
| 保留期 | 30 天（脚本自动清理旧备份） |

---

## 前置准备

### 1. 安装 ossutil64

```bash
wget https://gosspublic.alicdn.com/ossutil/1.7.17/ossutil64
chmod +x ossutil64
sudo mv ossutil64 /usr/local/bin/ossutil64

# 配置 AccessKey（只需做一次）
ossutil64 config
# 输入：AccessKeyId / AccessKeySecret / endpoint（如 oss-cn-hangzhou.aliyuncs.com）
```

### 2. 确认 sqlite3 已安装

```bash
which sqlite3 || sudo apt install -y sqlite3
```

---

## 配置 Cron

```bash
crontab -e
```

添加：

```cron
0 3 * * * cd /opt/news_pipeline && \
  OSS_BUCKET=your-bucket-name \
  OSS_ENDPOINT=oss-cn-hangzhou.aliyuncs.com \
  NEWS_PIPELINE_DB=data/news.db \
  ./scripts/backup_sqlite.sh >> logs/backup.log 2>&1
```

验证第一次运行：

```bash
tail -f /opt/news_pipeline/logs/backup.log
# 预期: backup OK: news_20260425T030000Z.db.gz
```

---

## 备份脚本环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `NEWS_PIPELINE_DB` | `data/news.db` | SQLite 数据库路径 |
| `OSS_BUCKET` | 必填 | OSS bucket 名称 |
| `OSS_ENDPOINT` | 必填 | OSS 区域 endpoint |
| `OSSUTIL` | `ossutil64` | ossutil binary 路径 |

---

## 手动备份

```bash
cd /opt/news_pipeline
OSS_BUCKET=your-bucket OSS_ENDPOINT=oss-cn-hangzhou.aliyuncs.com \
  ./scripts/backup_sqlite.sh
```

---

## 还原备份

```bash
# 还原特定备份（会先保留原文件为 .before-restore）
./scripts/restore_sqlite.sh \
  oss://your-bucket/backups/news_20260425T030000Z.db.gz

# 指定目标路径
./scripts/restore_sqlite.sh \
  oss://your-bucket/backups/news_20260425T030000Z.db.gz \
  data/news.db
```

还原后重启服务：

```bash
sudo systemctl restart news-pipeline
```

---

## 列出现有备份

```bash
ossutil64 ls oss://your-bucket/backups/ | grep "\.db\.gz"
```

---

## OSS 成本

OSS 备份成本极低：
- 每个 news.db 压缩后约 1-5 MB（取决于数据量）
- 保留 30 个备份 = 30-150 MB 存储
- 标准存储 ¥0.12/GB/月 → 每月 < ¥0.02

---

## 相关

- [Operations → Upgrading](upgrading.md) — 升级前备份
- [Operations → Daily Ops](daily-ops.md) — 手动操作
