# NewsProject

财经新闻与 A 股盯盘两个子系统，共用配置、交易日历、心跳和飞书发送层。新闻提供规则兜底、事件聚类、可选 LLM 评估、持久投递与摘要；盯盘使用腾讯个股行情和东财全市场/行业扫描。

v0.7.0 的默认配置是 **`pipeline.mode: legacy`、`llm.enabled: false`**。新事件路径通过 shadow/v2 显式启用。8 条已知案例是未审核 seed；150 条人工标注和付费模型 benchmark 尚未完成，本仓库不宣称已经达到模型或生产验收指标。

## Docker Compose 启动

需要 Docker 与 Compose v2。生产目录 `/opt/NewsProject`，持久数据在 `data`，配置在 `config`。

```bash
cd /opt/NewsProject
umask 077
cp config/common/secrets.yml.example config/common/secrets.yml
chmod 600 config/common/secrets.yml
$EDITOR config/common/secrets.yml
$EDITOR config/news_pipeline/sources.yml
$EDITOR config/news_pipeline/watchlist.yml
$EDITOR config/common/channels.yml
docker compose build app
docker compose up -d
docker compose ps
docker compose logs --tail=100 app quote_watcher
```

先填写启用频道的飞书密钥，Finnhub token 按需配置。SEC User-Agent 必须包含真实联系人与邮箱，不能保留模板占位符。默认 LLM 关闭时不需要 DashScope key；启用前需获得付费评测授权，并为评估/摘要模型填写控制台核对的正数 input/output 单价（人民币 / 百万 token）。

只有 `app` 启动入口迁移新闻库，`quote_watcher` 不重复迁移。Datasette 在 `127.0.0.1:8001` 只读浏览。新闻配置修改后重启 `app`；盯盘只有 `alerts.yml` 通过现有 reloader 热加载，持仓与盯盘列表修改后重启盯盘。

## 灰度与回滚

B0 先完成 150 条人工标注与获授权的模型选型。shadow 运行 2–3 个交易日：旧路径发新闻，新事件/摘要不发，系统运维卡片仍发。检查日报后切 v2；回滚改回 legacy、关闭 LLM 并重启，不删新表。

v2 稳定一周后才执行 C1/C2 旧模块和依赖删除；阶段 D 扩源至少等待两周稳定运行。完整的备份、回滚和删除清单见 [部署指南](docs/getting-started/deployment-current.md) 与 [清理门槛](docs/operations/staged-cleanup.md)。

## 文档与验证

- [架构](docs/architecture.md) · [新闻源](docs/components/scrapers.md) · [规则](docs/components/rules.md)
- [事件与去重](docs/components/dedup.md) · [评估与回放](docs/components/llm-pipeline.md)
- [Outbox 与摘要](docs/components/dispatch-router.md) · [监控](docs/components/observability.md)
- [新闻配置](config/news_pipeline/README.md) · [共用配置](config/common/README.md) · [盯盘配置](config/quote_watcher/README.md)
- [变更记录](CHANGELOG.md)

```bash
uv sync
uv run pytest
uv run mkdocs build --strict
docker compose exec app python -m news_pipeline.health.smoke --no-report
```

手工 smoke 默认输出 JSON 并发送运维卡片；使用 `--no-report` 才只输出 JSON，数据库始终只读、不入库。规则回放使用只读数据库副本；`--eval --mode rules` 不调用模型。`--mode llm` 或未显式指定 mode 的 `--eval --model ID` 会调用付费模型。
