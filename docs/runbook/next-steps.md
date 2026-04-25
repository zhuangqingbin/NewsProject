# News Pipeline 上线指南

> 从 `v0.1.1` 代码到「真新闻进、真消息推、真挂在阿里云稳定跑」的完整步骤。
> 预计总耗时：**首次跑通 4-8 小时**（大部分是申请账号 + 充值 + 调试）。

---

## 0. 当前状态盘点

✅ **代码侧**：MVP 全部 75 task 实现完毕，已合并 `main`，tag `v0.1.1` 含 4 个 critical 修复
- 135 单测 pass，ruff/mypy 全绿
- 9 个新闻源 + 4 层 LLM + 3 平台推送 + 13 表 SQLite + 飞书归档 + 图表 + 11 个 bot 命令 + DR 备份

❌ **没做的事**（本指南要解决）：
1. 申请所有外部服务的 API keys（最耗时）
2. 配置 `secrets.yml` 真值
3. 本地跑通一次（验证管线）
4. 上阿里云轻量服务器
5. 配置每日备份 + 监控

---

## 第一部分 — 申请 API Keys（最耗时，预计 2-4 小时）

> 建议**逐项申请、逐项填到 `secrets.yml`**，不要全部攒到最后再填。
> 边申请边把得到的 key 用 1Password 之类的密码管理器存一份备份。

### 1.1 阿里云 DashScope 灵积（DeepSeek-V3 + Qwen）

**用途**：Tier-0 + Tier-1 LLM（标题分类 + 普通摘要）

1. 登录阿里云控制台 → 搜索"灵积模型服务" → 开通服务
2. 进入 [DashScope 控制台](https://dashscope.console.aliyun.com/)
3. 左侧菜单 → "API-KEY 管理" → 创建新的 API-Key
4. 复制 `sk-xxx...` 形式的 key
5. 充值：先充 ¥20-50 测试足够（DeepSeek-V3 输入 ¥0.5/M tokens，月预算 ¥10-30）
6. 填进 `secrets.yml`：
   ```yaml
   llm:
     dashscope_api_key: sk-xxx...
   ```

**坑**：
- 阿里云会要求实名认证（身份证）才能开通
- 如果你已经有阿里云账号，直接复用
- DashScope 默认 QPS 5/秒，新闻管线够用

### 1.2 Anthropic Claude（Tier-2 深度抽取）

**可选**：如果你不打算用 Anthropic（嫌麻烦/没海外卡），**可以完全跳过这一步**。

v0.1.2 起，系统检测到 `anthropic_api_key` 为空或 `REPLACE_ME` 时会自动把 Tier-2 / Tier-3 路由到 DashScope（用 `tier1_model`，默认 DeepSeek-V3）跑。

代价：实体/关系抽取质量稍差，但能跑、月成本压到 ¥10-30。

启动时会有一行 WARN 日志 `anthropic_not_configured_fallback_to_tier1`，提示你"我自动降级了"。

**用途**：Tier-2 实体/关系深度抽取（Haiku 4.5），偶尔 Tier-3 深度分析（Sonnet）

1. 访问 [console.anthropic.com](https://console.anthropic.com/)
2. 注册账号（**需要海外手机号**接验证码 + **海外银行卡 / 虚拟卡**）
3. 国内用户的常见路径：
   - **方案 A**（推荐）：通过国内代理商如 [302.ai](https://302.ai/) 或 [ohmygpt.com](https://www.ohmygpt.com/)，他们提供 OpenAI 兼容接口转发到 Anthropic，支持人民币付款。代码无需改（只需替换 `anthropic` 客户端的 `base_url`）
   - **方案 B**：自己注册 Anthropic 官方账号，需要海外身份+卡。能力最完整但门槛高
4. 拿到 API key（`sk-ant-...`）
5. 充值 ≥ $10 USD（约 ¥75，月预算估 ¥30-100）
6. 填进 `secrets.yml`：
   ```yaml
   llm:
     anthropic_api_key: sk-ant-xxx...
   ```

**坑**：
- 国内直连 api.anthropic.com 会被墙，**必须有代理或用代理商转发**
- 如果走代理商，需要在代码里改 `base_url`：
  - 编辑 `src/news_pipeline/main.py` 找到 `AnthropicClient(api_key=...)` 那行
  - 改成 `AnthropicClient(api_key=..., base_url="https://api.302.ai/v1")`（按代理商文档）

### 1.3 Telegram Bot（×2：美股 + A 股）

**用途**：实时推送 + 接收命令

**步骤**（每个 bot 重复一次）：
1. Telegram 搜索 `@BotFather` → 私聊
2. 发 `/newbot` → 给 bot 起名（如"我的美股新闻 bot"）+ username（必须 `_bot` 结尾，如 `qingbin_us_news_bot`）
3. BotFather 返回的 token 形如 `1234567890:ABC...` → 复制
4. **关键**：再发 `/setwebhook`（用于命令交互）的 secret token：
   - 命令：`/newtoken @your_bot_username` 或在配置 webhook 时附加
   - 或自定义任意字符串（建议 32+ 位随机），后续 `setWebhook` 时传入
5. 拿 `chat_id`：
   - 私聊你的 bot 发任意消息
   - 浏览器打开 `https://api.telegram.org/bot<TOKEN>/getUpdates`
   - 找 `"chat":{"id": 123456789, ...}` → 这个数字就是 chat_id
6. 重复 1-5 创建第二个 bot（A 股专用）
7. 填进 `secrets.yml`：
   ```yaml
   push:
     tg_bot_token_us: 1234567890:ABC...
     tg_chat_id_us: "123456789"
     tg_secret_token_us: 32位随机字符串
     tg_bot_token_cn: 9876543210:XYZ...
     tg_chat_id_cn: "987654321"
     tg_secret_token_cn: 另一个32位随机字符串
   ```

**坑**：
- TG 在国内不能直连，需要梯子或代理（也可以让服务器走代理出网）
- 也可以用群组而不是私聊：把 bot 拉进群，然后 chat_id 是负数（如 `-100123...`）

### 1.4 飞书自定义机器人 Webhook（×2：美股 + A 股）

**用途**：实时推送富卡片消息（国内首选）

1. 飞书 → 创建 2 个群（"美股新闻"、"A股新闻"，可以是只有自己的群）
2. 群设置 → 群机器人 → 添加机器人 → 自定义机器人
3. 起个名（如"美股推送"）
4. 安全设置 → 选 **签名校验** → 复制密钥
5. 复制 webhook URL（形如 `https://open.feishu.cn/open-apis/bot/v2/hook/xxx`）
6. 填进 `secrets.yml`：
   ```yaml
   push:
     feishu_hook_us: https://open.feishu.cn/open-apis/bot/v2/hook/xxx
     feishu_sign_us: xxx_secret
     feishu_hook_cn: https://open.feishu.cn/open-apis/bot/v2/hook/yyy
     feishu_sign_cn: yyy_secret
   ```

### 1.5 飞书企业自建应用（用于多维表格归档）

**用途**：把所有新闻归档到表格，可手工标注 + 复盘

1. 访问 [open.feishu.cn](https://open.feishu.cn/) → 开发者后台 → 创建企业自建应用
2. 起名（如"news_archive"）→ 上传图标
3. 进入应用 → 凭证与基础信息 → 拿到：
   - `App ID`：`cli_xxx`
   - `App Secret`：`xxx`
4. **权限管理** → 添加权限：
   - `bitable:app` (查看、编辑多维表格)
   - `bitable:app:readonly` (查看)
   - `drive:drive` (查看云空间)
5. 应用发布 → 创建版本 → 提交审核（个人用立即通过）
6. 创建多维表格：
   - 进入飞书任意文件夹 → 新建多维表格 → 命名"News Archive US"（再建一个 CN）
   - 按 `docs/superpowers/specs/2026-04-25-news-pipeline-design.md` §3.2 的字段表 add columns（17 个字段）
7. 拿表格 ID：
   - URL 形如 `https://xxx.feishu.cn/base/<APP_TOKEN>?table=<TABLE_ID>&...`
   - `APP_TOKEN` 是表格的应用 ID（base 后面那段）
   - `TABLE_ID` 是 `tbl_xxx` 形式
8. 在表格顶部右键 → 协作 → 添加你的应用为协作者（**必须**，否则 API 写不进）
9. 填进 `secrets.yml`：
   ```yaml
   storage:
     feishu_app_id: cli_xxx
     feishu_app_secret: xxxsecretxxx
     feishu_app_token: <APP_TOKEN>      # 两个表格在同一个 base，所以共用一个 token
     feishu_table_us: tbl_xxx
     feishu_table_cn: tbl_yyy
   ```

**坑**：
- 多维表格字段类型必须和 schema 一致（数字/单选/多选/日期/复选/URL/文本/长文本）
- 单选/多选字段需要预先建好选项（如 sentiment 选项 🟢看涨 / 🔴看跌 / ⚪中性）
- 应用必须加为表格协作者，仅创建应用是不够的

### 1.6 阿里云 OSS（SQLite 备份存储）

**用途**：每日 SQLite 数据库备份存这里（v0.1.4 起图表已改为 inline 嵌入，不再用 OSS 托管图片）

1. 登录阿里云控制台 → 对象存储 OSS → 创建 Bucket
2. 配置：
   - **Bucket 名称**：如 `news-charts-qingbin`（全网唯一）
   - **地域**：选你最近的（如杭州）
   - **存储类型**：标准存储
   - **读写权限**：私有（备份文件不需要公开）
   - **存储冗余**：本地冗余（最便宜）
3. 拿 AccessKey：右上角头像 → AccessKey 管理 → 创建 RAM 用户 → 授权 `AliyunOSSFullAccess`（仅这个 bucket 更安全）
4. 在服务器上配置 `ossutil`（见第四部分），供备份脚本使用

**坑**：
- OSS 月成本：< ¥1（备份流量极小）
- AccessKey 只需要配置在服务器的 ossutil 里，**不需要**写进 `secrets.yml`

### 1.7 Bark（iOS 系统级告警通道）

**用途**：系统挂了 / 反爬触发 / 成本超限的兜底告警，独立于推送通道（推送挂了也能告警）

1. iOS App Store 装 [Bark](https://apps.apple.com/cn/app/bark-customed-notifications/id1403753865)
2. 打开 app → 复制服务器 URL（形如 `https://api.day.app/xxxxxxxxx`）
3. 填进 `secrets.yml`：
   ```yaml
   alert:
     bark_url: https://api.day.app/xxxxxxxxx
   ```

### 1.8 Tushare（A 股财经数据）

**用途**：A 股新闻 + 行情兜底

1. 注册 [tushare.pro](https://tushare.pro/register)
2. 个人主页 → 复制 token
3. 普通用户每分钟 200 次调用够用；积分越高频率越高
4. 填进 `secrets.yml`：
   ```yaml
   sources:
     tushare_token: xxxxx...
   ```

### 1.9 雪球 + 同花顺 Cookie（最麻烦，可选）

**用途**：UGC 情绪 + 多源新闻

**这两个源是可选的**。如果嫌麻烦，可以先在 `config/sources.yml` 里 disable，主链路不影响：
```yaml
sources:
  xueqiu: {enabled: false}
  ths:    {enabled: false}
```

**抓 cookie 推荐方法（Network 标签）**：

1. 浏览器登录 [xueqiu.com](https://xueqiu.com)（确保右上角有头像）
2. F12 → 切到 **Network** 标签
3. 刷新页面（F5）
4. Network 列表找一个 `xueqiu.com` 的请求，点开
5. 右侧 Headers → Request Headers → 找 `Cookie:` 这一行
6. **鼠标右键 cookie 值 → Copy value**
7. 粘到 secrets.yml 的 `xueqiu_cookie:` 后面（用 `"..."` 包起来）

**或者用 cURL 命令**：Network 里找请求 → 右键 → Copy → Copy as cURL → 粘到记事本，里面 `-H 'Cookie: ...'` 就是要的内容。

**如果 Network 里看不到 Cookie 字段**：说明你**没真正登录**（雪球微信扫码登录有时不生成 web cookie），改用手机号或邮箱登录。

**雪球关键 cookie**（最少这 4 个就能跑）：
```
xq_a_token=xxx; xqat=xxx; xq_r_token=xxx; u=xxx
```

**同花顺关键 cookie**（最少这几个）：
```
u_ukey=xxx; v=xxx; user=xxx; userid=xxx; utk=xxx
```

填到 secrets.yml：
```yaml
sources:
  xueqiu_cookie: "xq_a_token=xxx; xqat=xxx; xq_r_token=xxx; u=xxx; ..."
  ths_cookie: "u_ukey=xxx; v=xxx; ..."
```

**坑**：
- Cookie 通常 7-30 天过期，过期后该源会反爬告警，需要重新拿
- **不要 commit cookie 到 git**（`config/secrets.yml` 已 gitignored）
- 雪球和同花顺有反爬，请求频率不要超 spec 设定（雪球 5min 一次）
- v0.1.3 起增强了反爬识别（HTML 假成功 / 空响应 / error_code 都识别），cookie 失效会立刻 Bark 告警

### 1.10 Finnhub（美股新闻 API，可选但强烈推荐）

**用途**：美股新闻一手源

1. 注册 [finnhub.io](https://finnhub.io/register)（免费）
2. Dashboard 复制 API key
3. 免费层 60 calls/min 够用
4. 填进 `secrets.yml`：
   ```yaml
   sources:
     finnhub_token: xxx...
   ```

---

## 第二部分 — 配置 secrets.yml（10 分钟）

```bash
cd /Users/qingbin.zhuang/Personal/NewsProject

# 复制模板（config/secrets.yml 已在 .gitignore，不会被提交）
cp config/secrets.yml.example config/secrets.yml

# 设置只有自己可读的权限
chmod 600 config/secrets.yml

# 编辑（填上面所有的真值）
vim config/secrets.yml
```

**最终结构示例**：
```yaml
llm:
  dashscope_api_key: sk-真实值
  anthropic_api_key: sk-ant-真实值
push:
  tg_bot_token_us: 真实值
  tg_chat_id_us: "真实值"
  tg_secret_token_us: 32位随机字符串
  tg_bot_token_cn: 真实值
  tg_chat_id_cn: "真实值"
  tg_secret_token_cn: 32位随机字符串
  feishu_hook_us: https://...
  feishu_sign_us: 真实值
  feishu_hook_cn: https://...
  feishu_sign_cn: 真实值
storage:
  feishu_app_id: cli_真实值
  feishu_app_secret: 真实值
  feishu_app_token: 真实值
  feishu_table_us: tbl_真实值
  feishu_table_cn: tbl_真实值
sources:
  finnhub_token: 真实值
  tushare_token: 真实值
  xueqiu_cookie: "..."
  ths_cookie: "..."
alert:
  bark_url: https://api.day.app/真实值
```

---

## 第三部分 — 本地跑通一次（30 分钟）

> 目的：验证管线能跑通，所有 secrets 可用，**不真发推送**（先用 dry-run 看日志）。

### 3.1 装依赖

```bash
cd /Users/qingbin.zhuang/Personal/NewsProject

# 装 uv（如已装跳过）
curl -LsSf https://astral.sh/uv/install.sh | sh

# 安装 Python 依赖
uv sync

# 装 docker（如已装跳过）
brew install --cask docker
```

### 3.2 初始化数据库

```bash
mkdir -p data logs
uv run alembic upgrade head

# 验证 13 表都建好
sqlite3 data/news.db ".tables"
```

期望看到：`alembic_version audit_log daily_metrics dead_letter digest_buffer entities news_entities news_fts news_processed push_log raw_news relations source_state`（13 表，不含已删除的 `chart_cache`）

### 3.3 跑一次抓取 + 处理（不推送）

```bash
# 临时禁用推送：把 channels.yml 里所有 enabled: true 改成 false
cp config/channels.yml config/channels.yml.bak
sed -i '' 's/enabled: true/enabled: false/g' config/channels.yml

# 跑一次端到端
NEWS_PIPELINE_ONCE=1 uv run python -m news_pipeline.main 2>&1 | tee logs/first-run.log
```

**期望看到**（结构化 JSON 日志）：
- `scheduler_started` 或 `scrape_done` 多次（每个源一次）
- `llm_skip` 或 `llm_done` 表示 LLM 处理过
- 没有 `ERROR` 级别的反复异常

**检查 SQLite 有没有数据**：
```bash
sqlite3 data/news.db "SELECT source, count(*) FROM raw_news GROUP BY source;"
sqlite3 data/news.db "SELECT count(*) FROM news_processed WHERE is_critical = 1;"
```

### 3.4 排查常见问题

| 现象 | 原因 | 修法 |
|---|---|---|
| `ImportError` | 依赖装不全 | `uv sync` 重新装 |
| `OperationalError: no such table` | 没跑迁移 | `uv run alembic upgrade head` |
| `httpx.ConnectError` 大量出现 | 国内访问被墙 | 配代理：`HTTPS_PROXY=http://localhost:7890 uv run ...`；或换成可用 endpoint |
| `xueqiu blocked` / `ths blocked` | cookie 失效 | 重新拿 cookie |
| `CostCeilingExceeded` | LLM 成本超限 | 调高 `app.yml` 的 `daily_cost_ceiling_cny` 或减少 watchlist |
| 没有 raw_news | 抓取全部失败 | 看日志 `scrape_failed` 行的 `error` 字段 |

### 3.5 测试推送（小心，会真发！）

```bash
# 恢复 channels.yml
mv config/channels.yml.bak config/channels.yml

# 只 enable 一个 channel 测试（如先只 enable feishu_us）
vim config/channels.yml   # 把 enable 改回 true，但其他还是 false

# 把 watchlist 缩小（避免一次推 20 条）
vim config/watchlist.yml   # 只留 1-2 只股

# 跑
NEWS_PIPELINE_ONCE=1 uv run python -m news_pipeline.main

# 看 push_log
sqlite3 data/news.db "SELECT * FROM push_log ORDER BY id DESC LIMIT 10;"
```

如果飞书群收到消息 → 推送链路通了。逐个 enable 其他渠道。

---

## 第四部分 — 上阿里云轻量服务器（1-2 小时）

### 4.1 买服务器

1. 阿里云 → 轻量应用服务器 → 选配置：
   - **2 核 2 GB**（最小推荐）/ **2 核 4 GB**（更稳，月 ¥80-100）
   - **镜像**：Ubuntu 22.04
   - **地域**：选你能就近 SSH 的地方，**杭州/上海**国内访问 OSS 最快
   - **流量套餐**：300 GB/月 够用
2. 设置实例密码 / 上传 SSH 公钥
3. 防火墙开放：22 (SSH)、80 (可选, healthcheck)、443 (可选, webhook)

### 4.2 SSH 进服务器初始化

```bash
ssh root@<服务器IP>

# 装基础包
apt update && apt install -y docker.io docker-compose-v2 sqlite3 git vim
systemctl enable --now docker

# 装 ossutil（用于备份）
wget https://gosspublic.alicdn.com/ossutil/1.7.18/ossutil64
chmod +x ossutil64 && mv ossutil64 /usr/local/bin/ossutil

# 配置 ossutil
ossutil config -e oss-cn-hangzhou.aliyuncs.com \
  -i <access_key_id> -k <access_key_secret> -L CH

# 创建项目目录
mkdir -p /opt/news_pipeline
cd /opt/news_pipeline
```

### 4.3 同步代码

**本地**：
```bash
cd /Users/qingbin.zhuang/Personal/NewsProject
rsync -avz --exclude='.venv' --exclude='__pycache__' --exclude='data' \
  --exclude='secrets' --exclude='logs' --exclude='.git' \
  --exclude='.omc' \
  ./ root@<服务器IP>:/opt/news_pipeline/
```

或者推到 GitHub 私库再 `git clone`（但要给服务器配 deploy key）。

### 4.4 配置 secrets

```bash
# 服务器上
cd /opt/news_pipeline
mkdir -p data logs
cp config/secrets.yml.example config/secrets.yml
chmod 600 config/secrets.yml
vim config/secrets.yml       # 同本地一样填值
```

### 4.5 起服务

```bash
cd /opt/news_pipeline
docker compose -f docker/compose.yml build
docker compose -f docker/compose.yml up -d

# 看日志
docker compose -f docker/compose.yml logs -f
```

期望看到 `scheduler_started` 后跟着各种 `scrape_done` / `llm_done` / `push_done`。

### 4.6 配置每日备份 cron

```bash
# 服务器上
crontab -e
```

加入：
```cron
# 每天 03:00 UTC（北京 11:00）备份 SQLite 到 OSS，保留 30 天
0 3 * * * cd /opt/news_pipeline && \
  OSS_BUCKET=news-charts-qingbin \
  OSS_ENDPOINT=oss-cn-hangzhou.aliyuncs.com \
  NEWS_PIPELINE_DB=data/news.db \
  ./scripts/backup_sqlite.sh \
  >> logs/backup.log 2>&1
```

第二天看 `logs/backup.log` 验证。

### 4.7 给 Telegram 设 webhook（启用命令交互）

```bash
# 暴露 webhook 端口（可用 nginx 反向代理 + Let's Encrypt 加 HTTPS）
# 简化方案：用 cloudflare tunnel 或 ngrok 临时暴露

# 给每个 bot 调一次 setWebhook
curl "https://api.telegram.org/bot<TG_BOT_TOKEN_US>/setWebhook?url=https://你的域名/tg/webhook&secret_token=<TG_SECRET_TOKEN_US>"
```

之后在 TG 私聊 bot 发 `/list` 应该能收到回复。

---

## 第五部分 — 日常运维（持续）

### 5.1 常用 bot 命令

```
/list                查看当前 watchlist
/watch NVDA          加入自选
/unwatch NVDA        移除自选
/news NVDA           查 NVDA 近 10 条新闻
/chart NVDA 30d      生成 K 线图
/sentiment NVDA 7d   情绪曲线
/cost                查看本月 LLM 消耗
/pause xueqiu 60     暂停某源 60 分钟
/digest now          立即出 digest
/health              系统健康检查
/deep <news_id>      Tier-3 深度分析
```

### 5.2 监控

- **Bark 推送**：自动告警，挂了第一时间收到
- **看 SQLite 状态**：
  ```bash
  ssh root@<服务器> "cd /opt/news_pipeline && sqlite3 data/news.db '
    SELECT date(extracted_at), count(*) FROM news_processed
    WHERE extracted_at > datetime(\"now\", \"-7 days\")
    GROUP BY date(extracted_at);'"
  ```
- **看推送成功率**：
  ```bash
  sqlite3 data/news.db 'SELECT channel, status, count(*) FROM push_log
    WHERE sent_at > datetime("now", "-1 day")
    GROUP BY channel, status;'
  ```
- **看死信**：
  ```bash
  sqlite3 data/news.db 'SELECT kind, error, count(*) FROM dead_letter
    WHERE resolved_at IS NULL GROUP BY kind, error;'
  ```

### 5.3 升级流程

本地改完代码 + 推到 GitHub：
```bash
ssh root@<服务器>
cd /opt/news_pipeline
git pull
docker compose -f docker/compose.yml build
docker compose -f docker/compose.yml up -d
docker compose -f docker/compose.yml logs -f --tail=50
```

### 5.4 Cookie 过期处理

雪球/同花顺 cookie 过期会触发：
- Bark 告警 "anti_crawl: xueqiu blocked"
- 该源被自动暂停 30 min（之后重试还会失败）

修复：
```bash
# 在本地浏览器登录该站 → F12 拿新 cookie
ssh root@<服务器>
vim /opt/news_pipeline/config/secrets.yml    # 更新 xueqiu_cookie / ths_cookie
docker compose -f docker/compose.yml restart  # 配置热加载也行，但重启更稳
```

---

## 第六部分 — 后续优化路线（可选，按优先级）

### 高优先级（review 文档里的 🟡 Important）

参考 `docs/superpowers/reviews/2026-04-25-impl-mvp-review.md`：

1. **I1**: `FeishuBitableClient._tenant_token` 加过期跟踪 + asyncio.Lock（避免并发冲突）
2. **I3**: Tier-1 也用 prompt cache（省 LLM 钱）
3. **I4**: `CostTracker` 加锁（避免并发漏算）
4. **I7**: `main.py` shutdown 加 timeout 防死锁
5. **I9**: Telegram MarkdownV2 转义拆分（链接 URL 也要转义）
6. **I10**: 雪球/同花顺反爬识别加上「200 + 0 items + HTML」检测

### 中优先级（运营经验积累）

7. 财联社 endpoint 实地抓包验证（spec 已标 placeholder）
8. 同花顺 endpoint 同上
9. 把 `daily_cost_ceiling_cny` 调到合适值（建议跑一周看实际消耗再定）
10. `title_simhash_distance` 从 4 调到 8-12（dedup 太严，相似中文标题漏不到）
11. Watchlist 加 SEC CIK 映射（`main.py` 里 hard-coded，应该挪到 yaml）

### 低优先级（长期价值）

12. 加更多新闻源（彭博 RSS、Reuters 中文）
13. 真上 Neo4j 图数据库（spec §3.5 第 2 条，关系数据已建模好，迁移脚本一写就能用）
14. 真做 prompt A/B（当前只版本化，没对比）
15. 让 watchlist 命令也写到 `entities` 表（别名归一）
16. 引入 LLM batch API（DeepSeek + Anthropic 都支持，digest 处理时省 50%）

### 真出问题再做（不主动改）

17. 拆分 scraper 成独立容器（防止抓取卡死带崩主流程）
18. 上 Redis 队列（消息处理量级真起来再上）
19. 加 Web 仪表板（飞书表格够用，前端是奢侈品）
20. 多用户隔离（个人项目不需要）

---

## 附录 A：常见问题 FAQ

**Q: 一个月真实成本大概多少？**
- 阿里云轻量 2c2g：¥60-100
- DashScope DeepSeek：¥10-30（按实际新闻量）
- Anthropic Haiku：¥30-100（含 prompt cache 后）
- Anthropic Sonnet：¥0-20（仅手动 /deep 触发）
- OSS 存储（备份）：< ¥1
- **合计：¥100-250/月**

**Q: Anthropic 没法用怎么办？**
- 全部走 DashScope（DeepSeek-V3 当 Tier-2）：质量降一档但能跑，月成本压到 ¥80
- 改 `app.yml` 的 `tier2_model: deepseek-v3`，并改 prompt 让 DS 也输出 entities

**Q: 飞书表格满了怎么办？**
- 飞书表格上限 50000 行（个人版）
- 90 天前的归档可手动删除（已写在 spec 的 retention 里）
- 或者切到飞书"高级版"

**Q: 我想加一个新闻源怎么办？**
1. 在 `src/news_pipeline/scrapers/<market>/<name>.py` 实现 `ScraperProtocol`
2. 在 `sources.yml` 里加配置项
3. 在 `scrapers/factory.py` 里 register
4. 加单测
5. 不需要动其他代码

**Q: 怎么知道 LLM 处理质量？**
1. 看飞书表格里的 `summary` 字段，人眼判断
2. `tests/eval/gold_news.jsonl` 加更多 gold 样本，跑 `RUN_EVAL=1 uv run pytest tests/eval`
3. 看 `confidence < 0.6` 的新闻（标记为 manual_review）

**Q: 服务器挂了怎么办？**
1. SSH 不通 → 阿里云控制台重启实例
2. Docker 容器挂 → `docker compose up -d` 自带 restart=unless-stopped 自动重启
3. 数据库损坏 → 切前一天 OSS 备份：
   ```bash
   ./scripts/restore_sqlite.sh oss://news-charts-qingbin/backups/news_YYYYMMDDTHHMMSSZ.db.gz
   ```
4. 全部重来 → 新开轻量 + git clone + secrets + 备份恢复 + `docker compose up`，30 分钟内恢复

**Q: 我想关掉系统休假一周怎么办？**
- `docker compose -f docker/compose.yml down`
- 回来再 `docker compose -f docker/compose.yml up -d`
- 期间没有新数据，但旧数据都在

---

## 附录 B：代码改动如何走

1. 本地 `git checkout -b feat/xxx`
2. 改代码 + 加测试
3. `uv run pytest && uv run ruff check && uv run mypy src/`
4. `git commit -m "feat: ..."`
5. 推到 GitHub（`git push -u origin feat/xxx`）
6. 自己 review 或合并 PR
7. 服务器 `git pull` + `docker compose build` + `docker compose up -d`

---

## 检查清单

打勾确认：

- [ ] 1.1 阿里云 DashScope 充值 ≥ ¥30，拿到 API key
- [ ] 1.2 Anthropic（直连或代理商）API key 可用
- [ ] 1.3 创建 2 个 Telegram bot，拿到 token + chat_id
- [ ] 1.4 创建 2 个飞书自定义机器人 webhook + sign
- [ ] 1.5 创建飞书企业自建应用 + 2 张多维表格 + 把 app 加为表格协作者
- [ ] 1.6 阿里云 OSS bucket（公共读 + 30 天生命周期）+ AccessKey
- [ ] 1.7 iOS 装 Bark + 拿 server URL
- [ ] 1.8 tushare 注册 + token
- [ ] 1.9 雪球 + 同花顺 cookie（可选）
- [ ] 1.10 Finnhub 注册（可选）
- [ ] 2 secrets.yml 全部填好，权限 600
- [ ] 3.2 本地 alembic upgrade head 成功
- [ ] 3.3 NEWS_PIPELINE_ONCE=1 跑一次能拿到 raw_news
- [ ] 3.5 至少 1 个推送渠道收到测试消息
- [ ] 4.1 阿里云轻量服务器开通
- [ ] 4.2 ssh 进去，docker + ossutil 装好
- [ ] 4.3 代码 rsync 到 /opt/news_pipeline
- [ ] 4.5 docker compose up -d 起来，日志正常
- [ ] 4.6 host cron 配好，第二天有备份
- [ ] 5.1 在 TG / 飞书 用 /list 命令收到回复
- [ ] 真新闻进 + 真消息推（端到端通了）

---

**到这里你的 v0.1.1 就完整跑在生产了。** 🎉

后续优化按附录"后续优化路线"逐项推进。任何问题先翻 spec / plan / review 三个文档，再问我。
