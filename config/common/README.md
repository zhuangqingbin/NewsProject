# config/common — 两个子系统共用的配置

`news_pipeline` 和 `quote_watcher` 都会读取这里的文件。

---

## secrets.yml

API 密钥集合。**绝对不要提交到 git**（已在 `.gitignore` 中排除）。

从模板复制后按需填写：

```bash
cp config/common/secrets.yml.example config/common/secrets.yml
$EDITOR config/common/secrets.yml
```

**关于飞书 webhook 拆分**(v0.4.1):新闻和盯盘告警分到 2 个不同的飞书机器人,避免互相吵.A 股新闻 → `feishu_hook_cn` 机器人,A 股盯盘告警 → `feishu_hook_cn_alert` 机器人.建群时分开建,或同一群多个机器人也行.

### 字段说明

| 字段 | 必要程度 | 用途 | 怎么获取 |
|---|---|---|---|
| `push.feishu_hook_us` | ⭐ 必填 | 美股新闻推送的飞书机器人 webhook key | 飞书群 → 设置 → 群机器人 → 添加自定义机器人 → 复制 webhook URL 中 `v2/hook/` 后面的 key |
| `push.feishu_sign_us` | 推荐 | 美股新闻频道机器人签名校验密钥 | 添加机器人时勾选"签名校验"，复制密钥 |
| `push.feishu_hook_cn` | ⭐ 必填 | A 股新闻推送的飞书机器人 webhook key | 同上，推荐另开一个群分流告警 |
| `push.feishu_sign_cn` | 推荐 | A 股新闻频道机器人签名校验密钥 | 同上 |
| `push.feishu_hook_us_alert` | 选填 | 美股盯盘告警飞书机器人 webhook key（Phase 1.x 预留，当前 US 盯盘未启用） | 同上 |
| `push.feishu_sign_us_alert` | 选填 | 美股告警频道机器人签名校验密钥 | 同上 |
| `push.feishu_hook_cn_alert` | ⭐ 必填 | A 股盯盘告警飞书机器人 webhook key | 同上，建议与新闻机器人分开 |
| `push.feishu_sign_cn_alert` | 推荐 | A 股告警频道机器人签名校验密钥 | 同上 |
| `llm.dashscope_api_key` | ⭐ 必填 | DeepSeek tier-0/tier-1 LLM（阿里云百炼） | https://dashscope.console.aliyun.com → API-KEY 管理 → 创建 API Key |
| `llm.anthropic_api_key` | 推荐 | Claude Haiku tier-2 实体抽取；无此 key 时自动降级到 dashscope | https://console.anthropic.com → API Keys → Create Key |
| `sources.finnhub_token` | 美股必填 | Finnhub 财经新闻 + 基本面数据 | https://finnhub.io 注册后首页直接显示免费 token |
| `sources.xueqiu_cookie` | 选填 | 雪球 A 股新闻（`sources.yml` 中默认禁用） | 浏览器登录 xueqiu.com → F12 Network → 任意请求 → 复制 Cookie 请求头 |
| `sources.ths_cookie` | 选填 | 同花顺新闻（`sources.yml` 中默认禁用） | 同上，登录 ths.com 后复制 |
| `alert.bark_url` | 推荐 | iOS Bark 系统级告警（独立于飞书，费用超限 / scraper 挂掉会直接推手机通知） | iOS 安装 Bark App → 首页复制个人推送 URL（形如 `https://api.day.app/xxxx/`） |

### 最小可用集（能跑起来的最少配置）

```yaml
push:
  feishu_hook_cn: REPLACE_ME        # A股新闻飞书群机器人
  feishu_hook_cn_alert: REPLACE_ME  # A股盯盘告警飞书群机器人
llm:
  dashscope_api_key: REPLACE_ME
sources:
  finnhub_token: REPLACE_ME
```

> 最小可用集：`feishu_hook_cn` + `feishu_sign_cn` + `feishu_hook_cn_alert` + `feishu_sign_cn_alert` + `llm.dashscope_api_key` + `sources.finnhub_token`。

---

## app.yml

全局调度 / LLM 路由 / 分类阈值。**默认值已调好，通常不需要改。**

### 主要字段速查

| 字段 | 默认值 | 说明 |
|---|---|---|
| `runtime.daily_cost_ceiling_cny` | `5.0` | 每日 LLM 费用上限（CNY）；超限停止调用 LLM，Bark 告警 |
| `runtime.hot_reload` | `true` | 运行中修改 yml → 自动生效，无需重启 |
| `scheduler.scrape.market_hours_interval_sec` | `180` | 交易时段各 scraper 轮询间隔（秒） |
| `scheduler.scrape.off_hours_interval_sec` | `1800` | 非交易时段轮询间隔 |
| `scheduler.llm.process_interval_sec` | `120` | 待处理新闻 LLM 批处理间隔 |
| `scheduler.digest.morning_cn` | `"08:30"` | A 股早报推送时间（CST） |
| `scheduler.digest.evening_cn` | `"21:00"` | A 股晚报推送时间 |
| `scheduler.digest.morning_us` | `"21:00"` | 美股早报（北京时间晚 9 点对应美东早盘前） |
| `scheduler.digest.evening_us` | `"04:30"` | 美股晚报（北京时间次日凌晨，美东收盘后） |
| `llm.tier0_model` | `deepseek-v3` | tier-0 快速分类模型 |
| `llm.tier1_model` | `deepseek-v3` | tier-1 摘要模型 |
| `llm.tier2_model` | `claude-haiku-4-5-20251001` | tier-2 深度实体抽取（需 anthropic_api_key，否则降级 tier1） |
| `llm.prompt_versions` | `v1` | 各 tier prompt 版本，与 `prompts/` 目录文件名对应 |
| `classifier.rules.price_move_critical_pct` | `5.0` | 价格变动超过此百分比 → 自动标记为 critical |
| `classifier.llm_fallback_when_score` | `[40, 70]` | 规则打分落在此区间时，调用 LLM 二次判断 |
| `dedup.title_simhash_distance` | `4` | 标题 SimHash 去重阈值；越小越严格 |
| `push.same_ticker_burst_threshold` | `3` | 同一 ticker N 条内抑制重复推送 |
| `retention.raw_news_hot_days` | `30` | 原始新闻保留天数 |

---

## channels.yml

推送频道路由。**默认配置已就绪，通常不需要改。**

v0.4.1 起共 4 个频道，按用途拆分：新闻频道和告警频道各自独立。

| 频道 ID | market | 用途 | 使用者 |
|---|---|---|---|
| `feishu_us` | us | 美股新闻推送 | news_pipeline |
| `feishu_cn` | cn | A 股新闻推送 | news_pipeline |
| `feishu_us_alert` | us | 美股盯盘告警（Phase 1.x 预留，当前 `enabled: false`） | quote_watcher |
| `feishu_cn_alert` | cn | A 股盯盘告警 | quote_watcher |

路由规则：
- `news_pipeline` 只使用**不含** `_alert` 后缀的频道（market 匹配 + `enabled: true`）
- `quote_watcher` 只使用**含** `_alert` 后缀的频道（market 匹配 + `enabled: true`）

```yaml
channels:
  feishu_us:          # 频道 ID（被 sources/watchlist 引用）
    type: feishu
    market: us        # us / cn
    options:
      webhook_key: feishu_hook_us    # 对应 secrets.yml push.feishu_hook_us
      sign_key: feishu_sign_us       # 对应 secrets.yml push.feishu_sign_us
  feishu_cn:
    type: feishu
    market: cn
    options:
      webhook_key: feishu_hook_cn
      sign_key: feishu_sign_cn
  feishu_us_alert:
    type: feishu
    market: us
    enabled: false    # Phase 1.x 预留；US 盯盘接入后改为 true
    options:
      webhook_key: feishu_hook_us_alert
      sign_key: feishu_sign_us_alert
  feishu_cn_alert:
    type: feishu
    market: cn
    options:
      webhook_key: feishu_hook_cn_alert
      sign_key: feishu_sign_cn_alert
```

如需新增频道（例如再加一个测试群）：复制一段，改 ID + `webhook_key`，在 `secrets.yml` 对应加上 token 即可。
