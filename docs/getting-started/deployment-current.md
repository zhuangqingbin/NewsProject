# Current Deployment

本页描述 v0.7.0 的部署与灰度步骤，不代表已经完成线上发布或模型验收。服务使用 **Docker Compose**，服务器工作目录为 `/opt/NewsProject`；容器内为 `/app`。仓库默认 `pipeline.mode: legacy`、`llm.enabled: false`。

## 当前状态

| 项目 | 配置与行为 |
|---|---|
| 服务 | `app` 新闻流水线、`quote_watcher` A 股盯盘、`datasette` 只读浏览 |
| 数据 | 宿主机 `data/news.db`、`data/quotes.db`，挂载到 `/app/data` |
| 配置 | `config/common`、`config/news_pipeline`、`config/quote_watcher`，只读挂载 |
| 密钥 | `config/common/secrets.yml`；已被 `.gitignore` 排除，示例和非密钥配置仍受版本管理 |
| 迁移 | 只有 `app` 的 `RUN_MIGRATIONS=1` 启动入口执行 Alembic；盯盘不重复迁移新闻库 |
| 日志 | `docker compose logs`；应用使用 JSON 日志，HTTP 客户端 INFO 日志关闭 |
| 健康检查 | 各子系统自己的心跳文件，最近 3 分钟内更新才 healthy；源健康另行监控 |

旧的 uv + systemd 和 `/opt/news_pipeline` 部署说明已由本页替代。不要同时启动旧 systemd 进程与 Compose，避免重复抓取或推送。

## 首次部署步骤

在 `/opt/NewsProject` 放置仓库后执行：

```bash
cd /opt/NewsProject
umask 077
cp config/common/secrets.yml.example config/common/secrets.yml
chmod 600 config/common/secrets.yml
$EDITOR config/common/secrets.yml
$EDITOR config/news_pipeline/sources.yml
$EDITOR config/news_pipeline/watchlist.yml
$EDITOR config/common/channels.yml
$EDITOR config/common/app.yml
mkdir -p data logs
docker compose build app
docker compose up -d
docker compose ps
docker compose logs --tail=100 app quote_watcher
```

只启用已配好密钥和联系信息的源与频道。默认规则路径不需要 DashScope key；Finnhub 需要其 token。两个子系统使用独立飞书机器人，盯盘只选 `_alert` 频道。

SEC 必须使用包含**真实联系人和邮箱**的 User-Agent。在 `sources.yml` 的 `sec_edgar.options.user_agent` 填入，例如 `NewsProject operator operator@example.org`，并用自己的真实邮箱替换示例。不能把 `<你的邮箱>` 原样上线。主进程也支持 `SEC_USER_AGENT` 覆盖；当前 Compose 的 `app.environment.SEC_USER_AGENT: ${SEC_USER_AGENT:-}` 会读取宿主 export 或仓库 `.env`，传入新闻容器。修改后需 `docker compose up -d app` 重建容器环境；仅 restart 不会更改容器环境。

新闻配置修改后执行 `docker compose restart app`。新闻没有运行中的 YAML 热加载；旧 `runtime.hot_reload` 和 watchdog 的新闻配置监听仅是待清理兼容项。盯盘只对 `alerts.yml` 使用 `AlertsReloader`，持仓和盯盘列表修改后重启 `quote_watcher`。

## 升级流程

### 备份与发布

每次迁移前先停止写入进程，保留旧镜像和配置。SQLite 备份使用 backup API，不能只复制正在写入的 `.db` 而遗漏 WAL。

```bash
cd /opt/NewsProject
umask 077
docker compose stop app quote_watcher
docker image tag news-pipeline:latest news-pipeline:rollback-before-0.7.0
mkdir -p data/backups
chmod 700 data/backups
tar -czf data/backups/config-before-0.7.0.tar.gz config
docker compose run --rm --no-deps -T -e RUN_MIGRATIONS=0 app python - <<'PYBACKUP'
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
for name in ('news', 'quotes'):
    source = Path(f'/app/data/{name}.db')
    if source.is_file():
        with sqlite3.connect(source) as src:
            with sqlite3.connect(f'/app/data/backups/{name}-{stamp}.db') as dst:
                src.backup(dst)
PYBACKUP
```

检查备份文件后更新代码并构建启动。旧镜像 tag 应按每次发布分别保留。

```bash
git pull --ff-only
docker compose build app
docker compose up -d app quote_watcher datasette
docker compose exec app alembic current
docker compose exec app python -m news_pipeline.healthcheck
docker compose exec quote_watcher python -m news_pipeline.healthcheck --subsystem quote_watcher
```

0004 增加源健康字段；0005 增加 `v2_state`、事件、投递、LLM 调用记录，保留旧处理与推送表，同时将旧 `news_fts` 换为 `events_fts`。迁移前的原始记录标为 `v2_state='legacy'`，避免升级时把历史积压全部补推。

### 阶段 A：规则与取数修复

保持 `legacy` 和 LLM 关闭。验证回看抓取、源健康转换、即时推送去重、摘要失败不消费、腾讯个股/东财全市场与板块三个启动探测。交易时段验证主板、创业板、科创板成交量单位和日 K 均量单位后，才记录 A7 的线上验收结果。启动成功或离线测试不等同于这个实测。

### B0 与阶段 B：事件评估灰度

B0 要先从三周只读样本导出 150 个事件，人工标注规则 push 50、digest_hi 50、提及 30、宏观 20，并保留 30 条只做最终验证。仓库中的 8 个已知案例是 **unreviewed seed**，不是完成的 gold set。付费模型对比需先取得明确授权；本次变更没有模型 benchmark 或真实生产精度结论。

评测通过线：推送精度 ≥ 0.70，必推召回 ≥ 0.90，认错公司率 ≤ 2%，JSON 合法率 ≥ 99%，p95 延迟 ≤ 8 秒。记录模型、prompt 版本、费用和样本审核状态，未通过就继续规则兜底。

启用 LLM 前，在 `config/common/app.yml` 为 `llm.assess.model` 和 `llm.digest.model` 分别配置 `llm.pricing.<model>.input/output`，单位为 **人民币 / 百万 token**，两项必须是从实际供应商控制台核对的正数。默认 `pricing: {}` 与 `enabled: false` 可启动；缺价、零价或负价时启用 LLM 会被配置校验拒绝。示例模型名 `qwen-plus` 不是选型验收结论，旧 `llm.tier*` 不控制新评估器。

完成 B0 后设 `pipeline.mode: shadow`，重启 `app`，观察 **2–3 个交易日**。旧路径继续发新闻；新事件与摘要只写 `status='shadow'`，不发送。系统日报和源冒烟属于运维信号，影子模式仍发送。依据日报的新旧独有事件检查误推与漏推，再切 `v2` 并重启。

### 后续门槛

`v2` 连续稳定运行至少 **一周**、各源冒烟与日报可用、重试/回滚有证据后，才执行 C1/C2 的旧代码、配置和依赖删除，规划为 v0.7.1。阶段 C3/C4/C5 的保留任务、冒烟和文档可以先准备。阶段 D 扩源等待 **至少两周稳定运行**，逐个评估与启用，不能一次开启全部候选源。完整删除清单见 [稳定门槛与清理清单](../operations/staged-cleanup.md)。

## 回滚

阶段 B 首先把 `pipeline.mode` 改回 `legacy`、`llm.enabled` 改为 `false`，然后 `docker compose restart app`。无须删事件表或执行 Alembic downgrade。保留新路径记录用于调查；已发出去的消息不能通过回滚收回。

C1/C2 删除旧路径后，配置回滚不再足够：恢复保留的 v0.7.0 镜像和其配置，再启动服务。删除阶段不应删除旧表；正常回滚不需要恢复数据库。若迁移失败或确需恢复备份，先停止两个写入服务，并在隔离副本核对恢复后的数据及 WAL，不能把运行中的库直接覆盖。

## Datasette（仍用 Docker）

Compose 只把 Datasette 暴露在宿主机 `127.0.0.1:8001`。本机访问该地址；远程使用 SSH 隧道：

```bash
ssh -L 8001:localhost:8001 operator@server
```

## 相关

- [稳定门槛与清理清单](../operations/staged-cleanup.md)
- [调度器](../components/scheduler.md) · [可观测性](../components/observability.md)
- [评估与模型校准](../components/llm-pipeline.md) · [存储与保留](../components/storage.md)
