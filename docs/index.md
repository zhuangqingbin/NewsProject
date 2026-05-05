# News Pipeline

News Pipeline 是一个全自动财经新闻处理系统：从 9 个数据源持续抓取新闻，通过四层 LLM 管线提取结构化信息，按重要性分级后实时推送到飞书，并每天早晚发送摘要。系统运行在阿里云轻量服务器（1c2g），每月 LLM 成本约 ¥10–30。

```
新闻源 → 抓取 → 去重 → LLM 提取 → 分类打分 → 推送（实时 or 摘要）
```

---

## 关键章节

| 目标 | 链接 |
|---|---|
| 了解系统能做什么 | [Getting Started → Overview](getting-started/overview.md) |
| 看整体架构图 | [Getting Started → Architecture](getting-started/architecture.md) |
| 当前生产部署方式 | [Getting Started → Deployment](getting-started/deployment-current.md) |
| LLM 四层路由详解 | [Components → LLM Pipeline](components/llm-pipeline.md) |
| 日常运维命令 | [Operations → Daily Ops](operations/daily-ops.md) |
| 常见问题排查 | [Operations → Troubleshooting](operations/troubleshooting.md) |

---

## 当前版本

**v0.1.7** — 生产运行中，部署于 `8.135.67.243`（阿里云轻量）。

- 5 个抓取源已启用，4 个暂停（endpoint 变动，需重新验证）
- LLM：DashScope DeepSeek-V3 全程（Anthropic 未配置，自动 fallback）
- 推送：飞书 webhook
- 存储：SQLite 13 表，Datasette 浏览

查看完整版本历史：[Reference → Changelog](reference/changelog.md)
