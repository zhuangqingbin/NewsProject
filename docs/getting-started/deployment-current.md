# Current Deployment

这一页描述 v0.1.7 的实际生产部署方式，以及和原计划（Docker for app）的偏差原因。

---

## 当前状态

| 项目 | 状态 |
|---|---|
| 服务器 | 阿里云轻量服务器，`8.135.67.243`，Ubuntu 22.04，1c2g |
| 运行方式 | **uv + systemd 直跑**（非 Docker for app） |
| Datasette | **仍用 Docker**（小镜像，无影响） |
| 进程管理 | systemd unit `news-pipeline.service` |
| 代码路径 | `/opt/news_pipeline/` |
| 数据库 | `/opt/news_pipeline/data/news.db` |
| 日志 | `journalctl -u news-pipeline` + `/opt/news_pipeline/logs/` |

---

## 为什么没有用 Docker for app

原计划（`docs/superpowers/specs/`）设计为全 Docker Compose 部署。实际执行时遇到阻碍：

!!! warning "1 GB RAM 服务器 Docker build 太慢"
    `docker build` 过程中 pip install 需要编译 native 扩展（如 `greenlet`、`mplfinance`），
    在 1 GB RAM 机器上 OOM-killed 多次，单次 build 耗时 20+ 分钟。

替代方案：**uv 直接安装虚拟环境，systemd 管理进程**。

- `uv sync` 在开发机本地完成依赖解析 → 服务器上只需 `uv sync --no-dev`（预编译 wheel，快）
- systemd 提供自动重启、日志收集、开机自启
- Datasette 用的是官方 slim Docker 镜像（无 native build），保留 Docker 部署

---

## systemd unit 文件

路径：`/etc/systemd/system/news-pipeline.service`

```ini
[Unit]
Description=News Pipeline
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/news_pipeline
Environment=NEWS_PIPELINE_CONFIG_DIR=/opt/news_pipeline/config
Environment=NEWS_PIPELINE_DB=/opt/news_pipeline/data/news.db
Environment=LOG_LEVEL=INFO
ExecStart=/opt/news_pipeline/.venv/bin/python -m news_pipeline.main
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=news-pipeline

[Install]
WantedBy=multi-user.target
```

启用和管理：

```bash
# 首次启用
sudo systemctl daemon-reload
sudo systemctl enable news-pipeline
sudo systemctl start news-pipeline

# 日常
sudo systemctl status news-pipeline
sudo systemctl restart news-pipeline
sudo journalctl -u news-pipeline -f --no-pager
```

---

## Datasette（仍用 Docker）

Datasette 官方镜像很小（~100 MB），没有 native 编译，一行命令搞定：

```bash
# docker/compose.yml 中的 datasette service
docker compose -f docker/compose.yml up -d datasette
```

默认绑定 `127.0.0.1:8001`（仅本机访问）。

远程访问用 SSH 隧道：

```bash
ssh -L 8001:localhost:8001 ubuntu@8.135.67.243
# 然后本机浏览器打开 http://localhost:8001
```

---

## 首次部署步骤

```bash
# 1. 服务器上拉代码
ssh ubuntu@8.135.67.243
git clone <repo> /opt/news_pipeline
cd /opt/news_pipeline

# 2. 安装 uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# 3. 安装依赖
uv sync --no-dev

# 4. 配置 secrets
cp config/secrets.yml.example config/secrets.yml
chmod 600 config/secrets.yml
vim config/secrets.yml   # 填入真实 token

# 5. 初始化数据库
mkdir -p data logs
uv run alembic upgrade head

# 6. 安装 systemd unit（见上方内容）
sudo vim /etc/systemd/system/news-pipeline.service
sudo systemctl daemon-reload
sudo systemctl enable --now news-pipeline

# 7. 验证
sudo systemctl status news-pipeline
sudo journalctl -u news-pipeline -f
# 预期看到: scheduler_started, scraper_probe_ok (×5), bark sent "started"
```

---

## 升级流程

```bash
git pull
uv sync --no-dev
uv run alembic upgrade head
sudo systemctl restart news-pipeline
```

详见 [Operations → Upgrading](../operations/upgrading.md)。

---

## 后续改回 Docker 的条件

如果将来升级到 2c4g 以上服务器：

1. 在开发机本地 `docker build` → `docker push` 到镜像仓库（避免在服务器 build）
2. 服务器上只做 `docker pull` + `docker compose up -d`
3. 配合阿里云容器镜像服务（免费个人版）加速 push/pull

目前保留 `docker/Dockerfile` 和 `docker/compose.yml`，代码没有删除。

---

## 相关

- [Operations → Daily Ops](../operations/daily-ops.md)
- [Operations → Upgrading](../operations/upgrading.md)
- [Operations → Monitoring](../operations/monitoring.md)
