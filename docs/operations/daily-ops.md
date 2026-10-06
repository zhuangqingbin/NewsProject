# Daily Ops

在 `/opt/NewsProject` 使用 Docker Compose。不要按历史 systemd 文档同时启动另一个新闻进程。

```bash
docker compose ps
docker compose logs --tail=100 app quote_watcher
docker compose exec app python -m news_pipeline.healthcheck
docker compose exec quote_watcher python -m news_pipeline.healthcheck --subsystem quote_watcher
```

## 源与漏抓检查

```bash
docker compose exec app python -m news_pipeline.health.smoke --no-report
docker compose exec app python -m news_pipeline.health.leak_check
```

smoke 默认输出 JSON 并发送运维卡片；上面的 `--no-report` 只输出 JSON，`--report` 保留为显式别名。数据库始终只读、不入库。启动和周日 20:00 自动冒烟经 outbox 排队，系统日报每天 08:20；这些运维卡片在 shadow 仍发，shadow 新闻/摘要不发。

检查日报里的来源状态、新旧独有事件、费用和推送失败。heartbeats healthy 只说明进程活着；源 silent/failing 和 pending/failed delivery 需要分别排查。Datasette 通过本机或 SSH 隧道只读浏览。

## 修改、重启与一次性处理

修改新闻配置后 `docker compose restart app`；修改盯盘列表/持仓后重启 quote_watcher，只有 alerts 规则专门热加载。`NEWS_PIPELINE_ONCE=1` 按当前模式真实抓取、处理和运行一次 outbox，可能发送新闻，不能当只读检查。

备份与灰度切换严格按 [部署指南](../getting-started/deployment-current.md)。规则 replay 读数据库副本；LLM/eval 回放会花费供应商余额，先获授权并完成真实定价配置。
