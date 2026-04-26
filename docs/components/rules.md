# Rules Engine

!!! success "状态：v0.3.0 已上线"
    本页是当前生产生效的 watchlist 双段架构（rules + llm）。
    完整 spec：[设计文档](../superpowers/specs/2026-04-26-watchlist-rules-design.md)

---

## 这一页讲什么

v0.3.0 把单层 watchlist 改成 **rules + llm 双段**，rules 默认开、llm 默认关。
- **rules**：Aho-Corasick 算法做关键词匹配，毫秒级、零成本
- **llm**：当前的 LLM Tier-0/1/2 链路，可选

## 为什么改

| 痛点 | v0.1.7 行为 | v0.3.0 修复 |
|---|---|---|
| 慢 | 每条新闻 LLM Tier-0 1-2 秒 | rules 单条 < 1 ms |
| 贵 | 累积消耗 DashScope token | rules 零成本 |
| 不可控 | LLM 偶尔漏判过判 | 关键词列表全可枚举可单测 |
| 配置死路 | 想加复杂关联只能塞 prompt | sectors / macros / aliases 显式建模 |

## 4 种 enable 组合

| `rules.enable` | `llm.enable` | 行为 |
|---|---|---|
| true / false（默认） | rules.match → 命中走零 LLM 路径，不命中丢弃 |
| true / true | rules.match → 命中走 LLM Tier-1 拿摘要，不命中丢弃 |
| false / true | 跳过 rules，走原 LLM 全流程 |
| false / false | 启动报错 |

## 配置示例（v0.3.0 新格式）

```yaml
# config/watchlist.yml

rules:
  enable: true
  gray_zone_action: digest      # skip / digest / push
  
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
      macro_links: [央行, MLF]
  
  keyword_list:
    us: [Powell, recession, AI bubble]
    cn: [证监会, 国常会]
  
  macro_keywords:
    us: [FOMC, CPI, NFP, 美联储]
    cn: [央行, MLF, LPR, 降准]
  
  sector_keywords:
    us: [semiconductor, AI chip, GPU]
    cn: [白酒, 新能源, 半导体]

llm:
  enable: false
  us: [NVDA, TSLA]
  cn: ["600519"]
  macro: [FOMC]
  sectors: [semiconductor]
```

## 算法（Aho-Corasick + 边界处理）

- 库：[pyahocorasick](https://pyahocorasick.readthedocs.io/)（C 扩展）
- 启动一次性 build trie（< 10 ms）
- 单文章匹配 O(N+M)：1 KB 文本 + 350 patterns < 1 ms
- 英文 word boundary 校验（防 `NVDA` 误命中 `ENVDAQ`），中文不需要
- 算法可插拔：`MatcherProtocol`，未来可换 TF-IDF / embedding / regex / composite

## 数据流（rules-only 默认）

```mermaid
flowchart LR
  R[raw_news pending] --> M{RulesEngine.match}
  M -->|matched| S[synth_enriched_from_rules<br/>summary=body[:200]]
  M -->|no match| D[mark_status='skipped_rules']
  S --> C[classifier.score_news<br/>+ verdict.score_boost]
  C --> R2[router.route]
  R2 --> P[dispatcher.dispatch<br/>TG + Feishu]
```

## score_boost 公式

```
直接 ticker 命中     → +50
板块命中             → +20
宏观命中             → +15
（最高 100）

加上 classifier 现有 source / event / sentiment 权重后 ≥ 70 → is_critical=True
```

## 灰区行为（gray_zone_action）

| 值 | 行为 |
|---|---|
| `skip` | 灰区新闻完全丢弃 |
| `digest`（默认） | 进 digest_buffer，等早晚定时推 |
| `push` | 灰区当 critical 立即推 |

## 完整 spec

详细字段定义、pydantic schema、pipeline 集成代码、推送示例、迁移路径、测试策略、ADR 决策记录见：

[`docs/superpowers/specs/2026-04-26-watchlist-rules-design.md`](../superpowers/specs/2026-04-26-watchlist-rules-design.md)

## 实施时间表

- **v0.3.0**：本设计落地（AhoCorasickMatcher only）
- **v0.3.x**：TF-IDF / per-ticker enable 等增强
- **v0.4.0+**：Embedding / Composite matcher / 关系图触发
