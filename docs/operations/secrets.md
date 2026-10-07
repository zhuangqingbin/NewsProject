# Secrets

真实密钥只放 `config/common/secrets.yml`，从同目录 `.example` 复制并设 600 权限。该文件被 `.gitignore` 忽略，模板和其他配置没有被整目录忽略。配置备份会包含真实密钥，同样要限制权限。

## 当前字段

`push.news_pipeline` 的 US/CN hook/sign 配置新闻机器人；`push.quote_watcher` 的 CN hook/sign 配置盯盘机器人。`channels.yml` 的 dotted key 路径映射这些嵌套值；旧 flat push 仅兼容迁移。

`llm.dashscope_api_key` 只在新 LLM 开启后需要；默认规则不调用模型。Finnhub 启用时填 `sources.finnhub_token`。`alert.bark_url` 用于独立源/行情/模型告警。SEC 联系 User-Agent 是 sources/options 或显式容器环境配置，不是匿名占位字符串。

## 旧 Anthropic 与 cookie 字段

Anthropic、雪球/旧同花顺 cookie 没有当前调用方，可从自己的密钥文件移除。旧 Tier 路由、抓取器与命令服务器已删除；不改动或清除用户真实密钥文件。

日志中不打印 webhook/设备 key。HTTP 客户端 INFO 日志已关闭，但操作时仍应避免把秘密放到共享终端记录或 issue 中。详见 [部署](../getting-started/deployment-current.md) 与 [Pushers](../components/pushers.md)。
