# LLM Cost

这一页说明 DashScope 和 Anthropic 的定价、每层 LLM 单次成本估算，以及月度预算分析。

---

## 当前定价（2026-04-25）

### DashScope（阿里云灵积）— DeepSeek-V3

| 计费维度 | 单价 |
|---|---|
| 输入 tokens | ¥0.5 / 1M tokens |
| 输出 tokens | ¥1.5 / 1M tokens |

### Anthropic Claude

| 模型 | 输入（CNY/1M） | 输出（CNY/1M） | 备注 |
|---|---|---|---|
| claude-haiku-4-5-20251001 | ¥7.0 | ¥35.0 | Tier-2 配置模型 |
| claude-sonnet-4-6 | ¥21.0 | ¥105.0 | Tier-3 配置模型 |

注：Anthropic 官方定价为 USD，以上按汇率 7.0 换算。Prompt cache 命中可节省 90%（仅 Anthropic 支持）。

---

## 各 Tier 单次成本估算

### 当前状态（全程 DeepSeek-V3）

| Tier | 输入 tokens（估算） | 输出 tokens（估算） | 单次成本 |
|---|---|---|---|
| Tier-0（标题分类） | ~300 | ~100 | ¥0.00031 |
| Tier-1（普通摘要） | ~800 | ~300 | ¥0.00085 |
| Tier-2（深度抽取，fallback DeepSeek） | ~1500 | ~600 | ¥0.00165 |

### 配置 Anthropic 后

| Tier | 输入 tokens | 输出 tokens | 单次成本（无缓存） | 单次成本（90% 缓存命中） |
|---|---|---|---|---|
| Tier-0 | ~300 | ~100 | ¥0.00031（DeepSeek） | — |
| Tier-1 | ~800 | ~300 | ¥0.00085（DeepSeek） | — |
| Tier-2 | ~1500 | ~600 | ¥0.0315（Haiku） | ¥0.0066（缓存命中） |
| Tier-3 | ~2000 | ~800 | ¥0.126（Sonnet） | ¥0.027（缓存命中） |

---

## 月度成本估算

### 假设条件

- 每天抓取新文章：约 200 条（5 个 source × 平均 40 条/天）
- Tier-0：所有文章过一遍
- Tier-1：约 60% 的文章（非一手源 + 相关 + 普通）
- Tier-2：约 20% 的文章（一手源 + watchlist hit）
- Tier-3：当前未在主管线使用

### 全程 DeepSeek（当前状态）

| Tier | 每日条数 | 单次成本 | 每日成本 |
|---|---|---|---|
| Tier-0 | 200 | ¥0.00031 | ¥0.062 |
| Tier-1 | 120 | ¥0.00085 | ¥0.102 |
| Tier-2（DeepSeek） | 40 | ¥0.00165 | ¥0.066 |
| **合计** | — | — | **¥0.23/天** |
| **月度** | — | — | **≈ ¥7** |

### 配置 Anthropic Haiku（Tier-2）

| Tier | 每日条数 | 单次成本 | 每日成本 |
|---|---|---|---|
| Tier-0 + Tier-1 | 320 | — | ¥0.164 |
| Tier-2（Haiku，无缓存） | 40 | ¥0.0315 | ¥1.26 |
| **合计（无缓存）** | — | — | **¥1.42/天** |
| **合计（90% 缓存命中）** | — | — | **¥0.41/天** |
| **月度（无缓存）** | — | — | **≈ ¥43** |
| **月度（有缓存）** | — | — | **≈ ¥12** |

!!! tip "Prompt Cache 对成本影响很大"
    Anthropic prompt cache 对 system prompt 命中率约 80-90%（较长的 system prompt 基本稳定命中）。
    在上面的估算中，有缓存 vs 无缓存的月度成本差了约 3.5 倍（¥43 vs ¥12）。

---

## 成本上限设置建议

| 场景 | 建议 ceiling |
|---|---|
| 全程 DeepSeek（当前） | ¥5/天（充裕） |
| Anthropic Haiku 无缓存 | ¥15/天 |
| Anthropic Haiku 有缓存 | ¥8/天 |
| 压力测试 / 高新闻量日 | ¥20/天 |

修改：
```yaml
# config/app.yml
runtime:
  daily_cost_ceiling_cny: 8.0
```

---

## PRICING 字典（代码中）

```python
# main.py
PRICING = {
    "deepseek-v3": ModelPricing(input_per_m_cny=0.5, output_per_m_cny=1.5),
    "claude-haiku-4-5-20251001": ModelPricing(input_per_m_cny=7.0, output_per_m_cny=35.0),
    "claude-sonnet-4-6": ModelPricing(input_per_m_cny=21.0, output_per_m_cny=105.0),
}
```

未在 `PRICING` 字典中的模型：`CostTracker.record()` 不会报错，只是不计费（`p is None` → return）。如果将来换模型，记得更新 `PRICING`。

---

## 查看实时成本

```bash
# Bot 命令
/cost

# SQL
sqlite3 /opt/news_pipeline/data/news.db "
SELECT metric_date, printf('%.4f', metric_value) as cny
FROM daily_metrics WHERE metric_name = 'llm_cost_cny'
ORDER BY metric_date DESC LIMIT 14;"
```

---

## 相关

- [Components → LLM Pipeline](../components/llm-pipeline.md) — LLM 路由和 fallback
- [Operations → Daily Ops](../operations/daily-ops.md) — 查成本命令
- [Operations → Monitoring](../operations/monitoring.md) — 成本超限处理
