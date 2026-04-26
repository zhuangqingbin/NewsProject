# Architecture Decisions

这一页记录关键架构决策（ADR）：为什么选 SQLite、为什么不用 Docker for app、为什么砍飞书 bitable、为什么 fallback Anthropic→DeepSeek。

---

## ADR-1: 使用 SQLite 而不是 PostgreSQL

**状态**：已采用

**背景**：需要持久化 13 张表的数据，包括原始新闻、处理结果、实体图谱、推送日志等。

**决策**：使用 SQLite（通过 SQLModel + aiosqlite）。

**理由**：

| 维度 | SQLite | PostgreSQL |
|---|---|---|
| 运维复杂度 | 极低（单文件） | 高（进程管理、用户权限） |
| 1 GB RAM 服务器 | 完全够用 | 需要额外内存 |
| 写入并发 | 单写入者（asyncio 单进程够用） | 多写入者 |
| 备份 | `cp`/`gzip` + ossutil | `pg_dump` |
| 可观测性 | Datasette 一行命令 | 需要 pgAdmin 或 psql |
| 迁移 | Alembic（与 PG 相同） | Alembic |

**代价**：
- 不支持真正的并发写入（WAL 模式下并发读 OK，但写入串行化）
- 不支持复杂的 JSON 查询（有 JSON 函数，但功能有限）
- FTS5 全文索引功能比 PG tsvector 弱

**结论**：对单用户、单进程、<1 GB 数据量的场景，SQLite 是最佳选择。

---

## ADR-2: 不用 Docker 部署 app（改用 uv + systemd）

**状态**：已采用（v0.1.1+ 生产环境）

**背景**：原计划（设计 spec）使用 Docker Compose 全栈部署（app + datasette）。

**决策**：app 进程改用 uv venv + systemd 直跑；Datasette 保留 Docker（无 native build）。

**理由**：

- **1 GB RAM 服务器 docker build OOM**：`pip install` 编译 `greenlet`、`mplfinance` 等 native 扩展时，多次被 OOM Killer 终止
- **uv 的优势**：在本地开发机上 `uv lock`，生成 `uv.lock`；服务器上 `uv sync --no-dev` 直接下载预编译 wheel，无需编译，速度极快
- **systemd 够用**：提供自动重启、开机自启、日志收集（journal），功能完整

**代价**：
- 环境不完全隔离（app 和系统共用 Python 解释器路径）
- 部署流程稍复杂（需要手写 systemd unit）

**后续**：如果升级到 2c4g+ 服务器，可以考虑恢复 Docker（在本地 build → push → 服务器 pull，跳过服务器 build）。

---

## ADR-3: 砍飞书自建应用 + bitable 归档

**状态**：已采用（v0.1.6 完全移除）

**背景**：原计划用飞书自建应用 + bitable（多维表格）做新闻归档和可视化。

**决策**：移除所有飞书自建应用代码（`archive/` 模块、`feishu_auth.py`、bitable 写入）。飞书推送只保留自定义机器人 webhook。

**理由**：飞书的权限模型对单人开发者极度不友好：

```
想往 bitable 写数据，需要：
1. 自建应用（app_id + app_secret）
2. 应用获得 bitable.content:write scope
3. 应用被添加到目标 Space 的协作者
4. 目标 bitable 表在个人云空间（非企业空间权限不同）
5. 以上四个条件缺一不可，且 91403 错误提示信息极不清晰
```

调试超过 2 小时，尝试了所有 OAuth scope 组合，仍然 91403。ROI 极低。

**代价**：失去飞书多维表格的可视化和筛选能力。

**替代方案**：Datasette — 一行命令，功能更强（SQL 查询、CSV 导出、FTS 搜索），无需任何权限申请。

---

## ADR-4: Anthropic fallback 到 DeepSeek

**状态**：已采用（v0.1.2）

**背景**：设计时 Tier-2 使用 Anthropic Claude Haiku（深度实体抽取），Tier-3 使用 Claude Sonnet。

**决策**：当 `anthropic_api_key` 为空或 `REPLACE_ME` 时，Tier-2/Tier-3 自动 fallback 到 DashScope DeepSeek-V3（tier1_model）。

**理由**：

- 国内访问 `api.anthropic.com` 被墙，需要代理或代理商中转
- Anthropic 注册需要海外手机 + 海外银行卡，门槛高
- DeepSeek-V3 在成本上更有优势（¥0.5/M vs Haiku ¥7/M）
- 实体抽取质量稍差，但管线整体可运行

**实现**：

```python
# main.py 启动时判断
has_anthropic = is_anthropic_configured(anthropic_key)
if not has_anthropic:
    log.warning("anthropic_not_configured_fallback_to_tier1", ...)

# 在 pick_client_and_model 中路由
if configured_model.startswith("claude-"):
    if anthropic_client is not None:
        return anthropic_client, configured_model
    return dashscope_client, tier1_fallback_model  # fallback
```

**代价**：实体图谱质量（`entities` + `relations` 表）在 fallback 模式下精度较低。

---

## ADR-5: 推送渠道选择（TG + 飞书，去掉企微）

**状态**：已采用（v0.1.4 去掉企微代码）

**背景**：原计划支持 Telegram + 飞书 + 企业微信三个渠道。

**决策**：只保留 Telegram + 飞书 webhook；企业微信代码保留在代码库但不激活（channels.yml 中 type=wecom 支持，但无真实凭证）。

**理由**：

- 企微 webhook 格式和 Markdown 渲染与 TG/飞书差异大，维护成本翻倍
- 个人投资者使用场景：TG 在国际市场更通用；飞书在国内更好用
- 企微更多用于企业办公场景，不是目标用户

---

## ADR-6: APScheduler 而不是 Celery / RQ

**状态**：已采用

**背景**：需要定时任务（interval scraping + cron digest）。

**决策**：使用 `APScheduler AsyncIOScheduler`，与主进程 asyncio event loop 共用。

**理由**：

- **无需独立 broker**：Celery/RQ 需要 Redis 或 RabbitMQ，增加部署复杂度
- **asyncio 原生**：所有 scraper 和 pusher 都是 async，`AsyncIOScheduler` 无缝集成
- **单进程够用**：新闻处理量不大，不需要分布式任务队列

**代价**：无法横向扩展（单进程）；APScheduler job 失败不自动 DLQ（需手动处理）。

---

## 相关

- [Getting Started → Architecture](../getting-started/architecture.md) — 整体架构图
- [Getting Started → Deployment](../getting-started/deployment-current.md) — 部署决策详情
- [Components → Storage](../components/storage.md) — SQLite 使用方式
