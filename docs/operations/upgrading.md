# Upgrading

这一页描述标准升级流程：git pull → uv sync → alembic upgrade → systemctl restart。

---

## 标准升级流程

```bash
# 1. 拉最新代码
cd /opt/news_pipeline
git pull

# 2. 更新依赖（只安装 production 依赖）
uv sync --no-dev

# 3. 运行数据库迁移（幂等，安全）
uv run alembic upgrade head

# 4. 重启服务
sudo systemctl restart news-pipeline

# 5. 确认服务正常
sudo systemctl status news-pipeline
sudo journalctl -u news-pipeline -n 50 --no-pager
# 看 scheduler_started 日志行
```

---

## 升级前检查清单

- [ ] 查看 [CHANGELOG](../reference/changelog.md) 确认是否有 breaking changes
- [ ] 确认 `config/secrets.yml` 是否需要新增字段（查看 `secrets.yml.example` diff）
- [ ] 确认是否有新的 Alembic 迁移（`git log alembic/versions/`）
- [ ] 确认测试通过：`uv run pytest -q`（可选，但推荐）

---

## 有 breaking changes 时的处理

### secrets.yml 新增字段

```bash
# 查看模板差异
diff config/secrets.yml.example config/secrets.yml

# 将新字段添加到你的 secrets.yml
vim config/secrets.yml
```

### 新 Alembic 迁移

```bash
# 查看待应用的迁移
uv run alembic history --verbose

# 应用（幂等）
uv run alembic upgrade head
```

### 配置文件新增字段

如果 `app.yml` 有新的必填字段，服务启动时会报 Pydantic ValidationError。查看日志：

```bash
sudo journalctl -u news-pipeline -n 20
# 找 ValidationError
```

按提示在 `config/app.yml` 中添加对应字段。

---

## 回滚

```bash
# 回滚代码到上一个 tag
git checkout v0.1.7
uv sync --no-dev

# 如果有数据库迁移需要回滚
uv run alembic downgrade -1  # 回滚一步
# 或
uv run alembic downgrade <revision_id>

sudo systemctl restart news-pipeline
```

!!! warning "数据库回滚有风险"
    `alembic downgrade` 如果 migration 包含 DROP TABLE / DROP COLUMN，会丢失数据。
    升级前建议先备份：`./scripts/backup_sqlite.sh`

---

## 只更新配置（不更新代码）

热加载配置（无需重启）：
```bash
vim /opt/news_pipeline/config/app.yml    # 改 watchlist 相关或 cost ceiling
# watchdog 自动检测变化，2-3 秒内生效
```

需要重启的配置改动：
```bash
vim /opt/news_pipeline/config/sources.yml   # 启用/禁用 source
vim /opt/news_pipeline/config/channels.yml  # 改推送通道
vim /opt/news_pipeline/config/secrets.yml   # 改 API key
sudo systemctl restart news-pipeline
```

---

## 升级 Python 依赖（不升级代码）

```bash
# 在本地开发机上
uv lock --upgrade-package mkdocs-material  # 更新特定包
uv lock                                     # 更新所有

# 提交 uv.lock 到 git
git add uv.lock && git commit -m "chore: update deps"

# 服务器上
git pull && uv sync --no-dev && sudo systemctl restart news-pipeline
```

---

## 相关

- [Reference → Changelog](../reference/changelog.md) — 各版本变更
- [Operations → Backup](backup.md) — 升级前备份
- [Operations → Troubleshooting](troubleshooting.md) — 升级后问题处理
