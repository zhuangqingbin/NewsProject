# Secrets

这一页说明 `secrets.yml` 所有字段、安全须知，以及每种 token/key 的获取方式。

---

## 文件位置和权限

```bash
config/secrets.yml          # gitignored，不提交版本库
config/secrets.yml.example  # 模板，可以提交

# 创建
cp config/secrets.yml.example config/secrets.yml
chmod 600 config/secrets.yml  # 仅 owner 可读
```

!!! warning "secrets.yml 包含所有敏感凭证，永远不要提交到 git"
    `.gitignore` 中已排除 `config/secrets.yml`。每次 `git status` 确认它不出现在 staged 文件中。

---

## 完整字段说明

```yaml
llm:
  dashscope_api_key: sk-xxx...     # 阿里云 DashScope（DeepSeek-V3）
  anthropic_api_key: REPLACE_ME    # Anthropic Claude（可选，空/REPLACE_ME → 自动 fallback）

push:
  # Telegram — 美股频道
  tg_bot_token_us: 1234567890:ABC...  # BotFather 返回的 token
  tg_chat_id_us: "123456789"          # 私聊 chat_id（正数）或群 chat_id（负数）
  tg_secret_token_us: 32位随机字符串   # Telegram Webhook secret_token（暂未启用）

  # Telegram — A 股频道
  tg_bot_token_cn: ...
  tg_chat_id_cn: ...
  tg_secret_token_cn: ...

  # 飞书 — 美股频道（自定义机器人 webhook）
  feishu_hook_us: https://open.feishu.cn/open-apis/bot/v2/hook/xxx
  feishu_sign_us: sign_secret_key

  # 飞书 — A 股频道
  feishu_hook_cn: https://open.feishu.cn/open-apis/bot/v2/hook/yyy
  feishu_sign_cn: sign_secret_key

  # 飞书 Webhook 事件验证 token（暂未启用）
  feishu_verification_token: REPLACE_ME

sources:
  finnhub_token: REPLACE_ME    # Finnhub API token
  tushare_token: REPLACE_ME    # Tushare Pro token（tushare_news 禁用时不需要）
  xueqiu_cookie: REPLACE_ME    # 雪球 cookie（xueqiu 禁用时不需要）
  ths_cookie: REPLACE_ME       # 同花顺 cookie（ths 禁用时不需要）

alert:
  bark_url: https://api.day.app/<YOUR_BARK_KEY>  # Bark 推送 URL（可选）
```

---

## 各 Token/Key 获取方式

### DashScope（DeepSeek-V3）

1. 登录[阿里云 DashScope 控制台](https://dashscope.console.aliyun.com/)
2. 左侧 "API-KEY 管理" → 创建新 Key
3. 复制 `sk-xxx...` 形式的 key
4. 建议充值 ¥50（约可用 2-3 个月）

### Anthropic（可选）

!!! note "国内访问 Anthropic"
    Anthropic 官方 API 在国内被墙，需要代理或使用国内代理商（如 302.ai）。

1. [console.anthropic.com](https://console.anthropic.com/) 注册（需海外手机 + 海外银行卡）
2. 或使用国内代理商（302.ai / ohmygpt.com），提供人民币付款 + OpenAI 兼容接口
3. 拿到 `sk-ant-...` 形式的 key

如果使用代理商，还需要在 `main.py` 中修改 `base_url`：
```python
# AnthropicClient(api_key=..., base_url="https://api.302.ai/v1")
```

### Telegram Bot

1. Telegram 搜索 `@BotFather` → `/newbot`
2. 给 bot 起名（username 必须以 `_bot` 结尾）
3. BotFather 返回的 token 即 `tg_bot_token`
4. 拿 chat_id：
   ```bash
   # 私聊 bot 发任意消息，然后：
   curl "https://api.telegram.org/bot<TOKEN>/getUpdates"
   # 找 "chat":{"id": 123456789}
   ```

### 飞书自定义机器人

1. 飞书 → 创建群 → 群设置 → 群机器人 → 添加自定义机器人
2. 安全设置 → **签名校验** → 复制 sign secret
3. 复制 Webhook URL

### Bark

1. iPhone 安装 [Bark app](https://apps.apple.com/app/bark-customed-notifications/id1403753865)
2. 打开 app → 复制 push URL（形如 `https://api.day.app/<KEY>/`）

没有 iPhone 时的替代方案：
- 可以填写任意 URL，Bark 告警会静默失败（不影响主流程）
- 或自托管 [bark-server](https://github.com/Finb/bark-server) + Android 客户端

---

## 安全须知

1. `secrets.yml` 权限设为 `600`：`chmod 600 config/secrets.yml`
2. 不要把 secrets.yml 上传到任何云服务（OSS、GitHub、飞书文档）
3. 建议用 1Password 或 Bitwarden 备份一份
4. 服务器 RAM dump 不太可能泄漏（文件只在启动时读取）
5. 如果怀疑泄漏，立即 rotate 所有 key（DashScope / Anthropic / Telegram BotFather 都有 revoke 功能）

---

## 相关

- [Operations → Configuration](configuration.md) — 其他 yml 文件
- [Operations → Troubleshooting](troubleshooting.md) — token 失效如何调试
