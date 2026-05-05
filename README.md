# News Pipeline

财经新闻自动化流水线：抓取 → 去重 → 规则匹配 → 可选 LLM 摘要 → 推送到飞书 webhook。

数据源：Caixin / SEC EDGAR / Finnhub / Juchao / Akshare / 雪球 / 同花顺 …

---

## 一键部署（Docker）

**前置要求**：Docker 24+ 带 Compose v2，约 2 GB 内存，Linux/macOS 主机。

```bash
git clone https://github.com/<你>/NewsProject.git
cd NewsProject

# 1. 填密钥（DashScope API key、飞书 webhook 等）
cp config/secrets.yml.example config/secrets.yml
$EDITOR config/secrets.yml

# 2.（可选）调 watchlist / 数据源 / 推送渠道
$EDITOR config/watchlist.yml
$EDITOR config/channels.yml

# 3. 启动（首次 5-10 min；之后秒级）
docker compose up -d

# 4. 看跑起来没
docker compose ps
docker compose logs -f app
```

完事。app 是常驻进程，Datasette 在 <http://127.0.0.1:8001> 浏览 SQLite。

### CN 网络慢？换镜像源

```bash
docker compose build --build-arg UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
docker compose up -d
```

---

## `docker compose up -d` 干了啥

一行命令做三件事：

1. **build image**（本地没有就构建）——拉 `python:3.12-slim`、装 gcc、编译 `pyahocorasick`、`uv sync` 所有依赖
2. **创建容器**——按 `docker-compose.yml` 起 `news_pipeline` + `news_datasette`
3. **`-d` 后台跑**——命令立刻返回，终端能继续用

### 速度

| 场景 | 用时 | 原因 |
|---|---|---|
| **首次 build** | 5–10 min | 拉基础镜像 + 编译 C 扩展 + 装 LLM 全家桶 |
| 改 `src/*.py` 后重启 | ~30 s | 只重跑 `COPY src` 之后的层 |
| 改 `uv.lock`（加/删依赖） | 2–5 min | 从依赖层往后全部重建 |
| 改 `config/*.yml` | **秒级**（不需要 rebuild） | config 是 bind mount，重启容器就行 |
| 容器重启（image 不变） | 1–2 s | 复用现有 image |

### Image 层缓存

```
1. python:3.12-slim                     ← 几乎不变
2. apt install build-essential          ← 几乎不变
3. pip install uv
4. COPY pyproject.toml + uv.lock        ← uv.lock 不变就不重做这层后面
5. uv sync (deps only)                  ← 上一层缓存命中就跳过
6. COPY src/                            ← 改 .py 从这里重做
7. uv sync (install project)            ← src 改了就重做
```

只有比改动层高的层才重新执行，下面全部缓存命中。

---

## 日常运维

### 决策树：我改了东西，要怎么生效？

```
改了什么？
├── 只改 config/*.yml（watchlist / channels / sources / secrets …）
│     → docker compose restart app                    ← 秒级，不用 build
│
├── 改了 src/*.py 或 alembic 迁移
│     → docker compose up -d --build                  ← rebuild，~30 秒
│
├── 改了 pyproject.toml / uv.lock（加/删依赖）
│     → docker compose up -d --build                  ← 2-5 分钟（重装依赖）
│
├── 改了 Dockerfile / docker-compose.yml
│     → docker compose up -d --build                  ← rebuild
│
├── git pull 拉了新代码（不知道改了啥）
│     → git pull && docker compose up -d --build      ← 全量保险
│
└── 啥都没改，就想重启一下
      → docker compose restart app                    ← 1-2 秒
```

`docker compose up -d --build` 自带"内容没变就跳过"的层缓存，多 build 一次也不亏，只是多等几秒。**有疑问就 `--build`，不会错。**

build 完成后（自动）：compose 比对 image 变了 → 停老容器 → 起新容器，秒级切换

### 命令速查

| 你做的事 | 命令 |
|---|---|
| 首次部署 | `docker compose up -d`（慢） |
| 只改 config（watchlist.yml 等） | `docker compose restart app`（秒级） |
| 改了 src 代码 / Dockerfile / 依赖 | `docker compose up -d --build` |
| 拉新代码 + 重启 | `git pull && docker compose up -d --build` |
| 看实时日志 | `docker compose logs -f app` |
| 看历史日志 | `docker compose logs --tail 100 app` |
| 停掉（数据保留） | `docker compose down` |
| 看状态 | `docker compose ps` |
| 进容器手动跑命令 | `docker compose exec app python -m news_pipeline.commands.<...>` |
| 浏览 SQLite（远程） | `ssh -L 8001:localhost:8001 server` 然后开 <http://localhost:8001> |

### `restart` vs `up -d --build` 区别

| | `restart app` | `up -d --build` |
|---|---|---|
| 重新加载 config（bind mount） | ✅ | ✅ |
| 加载新代码（src/*.py） | ❌（image 里还是老代码） | ✅ |
| 加载新依赖 | ❌ | ✅ |
| 用时 | 1-2 秒 | 30 秒（代码改）~ 5 分钟（依赖改） |

> ⚠️ **常见坑**：改了 `src/` 的 .py 后只跑 `restart`，会发现"为啥没生效"——因为 image 里还是旧代码。这种情况一定要 `--build`。

---

## 持久化目录

三个 bind mount，全在仓库目录下：

| 路径 | 内容 | 说明 |
|---|---|---|
| `./config/` | yaml 配置（你编辑） | 容器内 **只读** |
| `./data/` | `news.db` SQLite + 状态 | 重启不丢；要备份的就这个 |
| `./logs/` | structlog JSON 日志 | 自己定期清理 |

`docker compose down` 不动这三个目录，安全停服。`-v` 也不影响（我们没用 named volume）。

---

## 配置说明

### `config/secrets.yml`（必填）

```yaml
llm:
  dashscope_api_key: sk-xxx       # DeepSeek-V3 走 DashScope
  anthropic_api_key: ""           # 留空就降级到 Tier-1（DashScope）
push:
  feishu_us_webhook: "https://open.feishu.cn/..."
  feishu_cn_webhook: "https://open.feishu.cn/..."
sources:
  finnhub_token: ""
  xueqiu_cookie: ""
  ths_cookie: ""
  tushare_token: ""
alert:
  bark_url: "https://api.day.app/<key>"
```

### `config/watchlist.yml`（v0.3.0 双段架构）

`rules` + `llm` 两段，至少一段 `enable: true`。`rules.enable=true` + `llm.enable=false` 是**默认零 LLM 成本**模式。

```yaml
rules:
  enable: true
  gray_zone_action: digest        # skip / digest / push
  matcher: aho_corasick

  us:
    - ticker: NVDA
      name: NVIDIA
      aliases: [英伟达, 老黄家, Jensen Huang]
      sectors: [semiconductor, ai]
      macro_links: [FOMC, CPI]

  cn:
    - ticker: "600519"
      name: 贵州茅台
      aliases: [茅台]
      sectors: [白酒]
      macro_links: [央行, MLF, LPR]

  keyword_list:                    # 通用关键词，只命中不关联个股
    us: [Powell, recession]
    cn: [证监会, 国常会]

  macro_keywords:                  # 宏观词，命中后关联 macro_links 引用它的 ticker
    us: [FOMC, CPI, NFP]
    cn: [央行, MLF, LPR]

  sector_keywords:                 # 板块词，同理关联 sectors 引用它的 ticker
    us: [semiconductor, ai, ev]
    cn: [新能源, 半导体, 白酒]

llm:
  enable: false                    # 想用 LLM 摘要再开
  us: [NVDA]
  cn: ["600519"]
```

**重要**：`ticker` 下的 `sectors` / `macro_links` 必须在全局的 `sector_keywords` / `macro_keywords` 里能找到，否则启动报错。

详见 [`docs/components/rules.md`](docs/components/rules.md)。

### 其他 yaml

- `config/app.yml` — 调度间隔、LLM 模型、灰度阈值
- `config/channels.yml` — 推送渠道（哪个 webhook 推 us / cn）
- `config/sources.yml` — 启用哪些数据源
- `config/entity_aliases.yml` — 实体别名（NVIDIA Corp → NVDA）

---

## 二次开发（不用 Docker）

直接在本机跑 Python，**仅给改代码用**，不是部署方式：

```bash
uv sync --group dev
cp config/secrets.yml.example config/secrets.yml && $EDITOR config/secrets.yml
uv run alembic upgrade head
uv run python -m news_pipeline.main
```

测试 + lint：
```bash
uv run pytest
uv run ruff check src/ tests/
uv run mypy src/
```

文档实时预览：
```bash
uv run mkdocs serve   # 开 http://localhost:8000
```

---

## 文档

完整文档在 `docs/`，跑 `mkdocs serve` 浏览，重点页：

- [概述](docs/getting-started/overview.md) — 系统做什么
- [架构](docs/getting-started/architecture.md) — 数据流 + 模块图
- [Rules Engine](docs/components/rules.md) — v0.3.0 关键词匹配
- [LLM Pipeline](docs/components/llm-pipeline.md) — 4 层路由 + 成本追踪
- [日常运维](docs/operations/daily-ops.md) — 常用命令
- [故障排查](docs/operations/troubleshooting.md) — 已知问题
- [配置](docs/operations/configuration.md) — 每个 yaml 字段

