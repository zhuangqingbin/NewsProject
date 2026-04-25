# Final Review: `impl/mvp` Branch (v0.1.0-mvp)

- **Reviewer:** Opus code-reviewer agent
- **Date:** 2026-04-25
- **Verdict:** APPROVE_WITH_CONCERNS — merge OK; **do not enable production cron until 🔴 list addressed**
- **Range reviewed:** `f732f3d..impl/mvp` (52 commits)

---

## Strengths

- Clean layering across scrapers/dedup/LLM/classifier/router/pushers/archive
- Protocol-based seams (`ScraperProtocol`, `PusherProtocol`, `LLMClient`) — easy testing + swappable providers
- Dedup hot-path correct: `RawNewsDAO.insert` catches `IntegrityError` → safe under concurrent scrapes
- Sensible indexes on `RawNews`, `NewsProcessed`, `DigestBuffer`, `Relation`
- Tier-2 entity/relation extraction handles unknown predicates safely (falls back to `MENTIONS`)
- Burst suppressor: clean sliding-window deque per ticker
- Cost ceiling check happens BEFORE the LLM call (cannot blow past in one big call)
- Anthropic uses tool-use for structured JSON (very reliable)
- Config + secrets split is real, secrets referenced indirectly in channel config
- Idempotent scheduler: `coalesce=True` + `max_instances=1`

---

## 🔴 Critical (must fix before enabling production cron)

### C1. Cost is checked but never recorded
- **Where:** `src/news_pipeline/llm/pipeline.py:36` calls `self._cost.check()` but no code anywhere calls `cost_tracker.record(...)`.
- **Impact:** ceiling never trips in production until wired. You can blow `daily_cost_ceiling_cny` by orders of magnitude with no alert.
- **Fix:** in `Tier0Classifier.classify`, `Tier1Summarizer.summarize`, `Tier2DeepExtractor.extract`, after `await self._client.call(req)`, call `cost_tracker.record(model=resp.model, usage=resp.usage)`. Cleanest: pass tracker into each extractor, OR wrap `self._client.call` in a `MeteredClient` decorator.

### C2. Telegram webhook has no authentication
- **Where:** `src/news_pipeline/commands/server.py:14-16` accepts `POST /tg/webhook` from any caller.
- **Impact:** Attacker who finds the URL can trigger `/watch`, `/cost`, `/pause`, spam push channels.
- **Fix:** Telegram → require `X-Telegram-Bot-Api-Secret-Token` header (set via `setWebhook` `secret_token`), 401 on mismatch. 飞书 → use documented `Encrypt-Key` + signature.

### C3. `_digest_job_runner` reaches into private `_by_market`
- **Where:** `src/news_pipeline/main.py:254`: `dispatch_router._by_market.get(market, [])`.
- **Impact:** Works today only because the name happens to be exposed. Will silently break on refactor; can also diverge from runtime config under hot-reload.
- **Fix:** Add `DispatchRouter.channels_for(market)` accessor; or capture channels list at runner-build time via the snapshot already in scope.

### C4. Evening digests never fire
- **Where:** `src/news_pipeline/scheduler/jobs.py:171`: `scheduled_digest=f"morning_{art.market.value}"` hardcoded.
- **Impact:** `evening_us` / `evening_cn` cron jobs always return `[]` from `list_pending`; users only get morning digests.
- **Fix:** pick digest key based on current local time (e.g. before 12:00 local → `morning`, otherwise → `evening`); or make `DispatchPlan` carry the digest key.

### C5. Feishu signing algorithm likely incorrect
- **Where:** `src/news_pipeline/pushers/feishu.py:62-65`: `hmac.new(string_to_sign.encode(), digestmod=...)` — uses secret as part of message, no key bytes.
- **Impact:** signature validation likely fails on Feishu's end; pushes rejected silently.
- **Fix:** per Feishu spec — `hmac.new(key=string_to_sign.encode(), msg=b"", digestmod=hashlib.sha256).digest()`. Verify against a real webhook before relying on it.

### C6. `for _ch in p.channels: ... break` smells
- **Where:** `src/news_pipeline/scheduler/jobs.py:167-173`: enqueues 1 digest row regardless of channel count, then breaks.
- **Impact:** combined with C4, evening digests silently dropped; per-channel digest opt-out impossible.
- **Fix:** remove the `for/break` if intent is "one digest entry per news"; or store `(news_id, channel)` per channel.

---

## 🟡 Important (next iteration)

| # | File | Issue | Fix |
|---|---|---|---|
| I1 | `archive/feishu_table.py:31-45` | `_tenant_token` no expiry tracking, no async lock | Store `(token, expires_at)`, refresh at `expires_at-60s`, guard with `asyncio.Lock` |
| I2 | `archive/feishu_table.py:47` | `@async_retry` only covers `httpx.HTTPError`; `RuntimeError` from token failure bubbles silently to `process_pending`'s try/except | Include `RuntimeError` in `retry_on`; or split token refresh from retry boundary |
| I3 | `extractors.py:86-93` | Tier-1 doesn't forward `cache_segments` | Forward `rendered.cache_segments` + `few_shot_examples` (or document why DashScope excluded) |
| I4 | `cost_tracker.py:22-30` | No lock on `_daily_total` writes; race under `asyncio.gather` | `asyncio.Lock` (or `threading.Lock` since class is sync) |
| I5 | `extractors.py:111,196`, `models.py:70,95` | `datetime.utcnow()` deprecated in 3.12 + naive | Replace with `utc_now()` (consistent with rest of codebase) |
| I6 | `scheduler/jobs.py:56` | `except (ScraperError, Exception)` — `ScraperError` arm unreachable; HTTP 500 looks identical to KeyError | Distinguish transient vs programmer/parser errors; alert on 3 consecutive |
| I7 | `main.py:268-281` | No hard-cancel deadline on shutdown; in-flight LLM/Feishu can deadlock | `asyncio.wait_for(runner.shutdown(), timeout=30)` |
| I8 | `pushers/common/burst.py:23` | `should_send` mutates state even on suppress — extends own suppression indefinitely | Skip `buf.append(now)` when `send=False`, or document with test |
| I9 | `pushers/telegram.py:71-72` | Over-escapes inside backticks; URLs in links not escaped — breaks on `)` | Split `md2_escape_text` / `md2_escape_code` / `md2_escape_link_url` |
| I10 | `scrapers/cn/xueqiu.py:32`, `ths.py:31` | Only 401/403 raise `AntiCrawlError`; CAPTCHA pages return 200 + 0 items silently | Detect HTML where JSON expected, `error_code != 0`, suspicious empty payloads |
| I11 | `scrapers/cn/caixin_telegram.py:20-22` | Endpoint is placeholder (in-code NOTE) | Verify real endpoint via packet capture before enabling |

---

## 🟢 Minor / 💡 Suggestions

- 💡 `main.py:53-57`: hard-coded `PRICING` dict — move to YAML
- 💡 `main.py:182`: hard-coded `sec_ciks` — move to `sources.yml` or watchlist
- 🟢 `main.py:80-83`: unused `_dlq`, `_audit`, `_chart_cache` locals — remove or wire
- 🟢 `LLMPipeline.__init__` 7 positional deps — make kwargs-only
- 🟢 `RawNewsDAO.list_recent_simhashes` returns ALL last-24h sims; dedup does O(N) per article → 400M comparisons/day at 20k news. Hash-bucketing or trigram needed at scale
- 🟢 Tier-2 entity dedup keys on `name` only → "NVIDIA" vs "Nvidia" = two entities
- 🟢 `wecom.py:43`/`feishu.py:59` use substring `'"errcode":0'` — parse JSON instead
- 🟢 `_render` in pushers concatenates user content into Markdown — TG escapes; Wecom/Feishu don't (link injection risk)
- 🟢 `BarkAlerter` interpolates title/body straight into URL path — no URL-encoding (breaks on `/`, `?`, spaces)
- 🟢 `Dedup` doesn't increment `dedup_dup` reason metric — useful for observability

---

## ⚠️ Risks not in code (assumptions that will bite)

- **Cookie-based scrapers (xueqiu, ths) are fragile** — cookies expire days/weeks; no rotation; no health check; no alert on silent-failure mode (200 + 0 items)
- **Source endpoints will shift** — caixin already flagged; xueqiu/ths/juchao/akshare all hit non-public endpoints. Need synthetic monitor: "did we ingest ≥ 1 article from each source in last 4h?"
- **Feishu/Anthropic/DashScope/OSS are external dependencies with quotas** — no circuit-breaker; one outage cascades into LLM batch worker stalling
- **`process_pending` is sequential per article** — at 3-15s LLM latency × batch_size=25 = 1-6 min per batch; sole LLM consumer; if it stalls, nothing else processes. Consider bounded `asyncio.gather`
- **No outbound push rate limit** — TG has 30 msg/sec global, 1/sec per chat. Burst of 10 critical news from one ticker after suppressor reset → may hit limits; retry decorator masks as transient
- **CN/US digest cron hardcoded `Asia/Shanghai`** (`scheduler/runner.py:48`) — `morning_us` at SH 7:00 = US 7pm previous day. Likely wrong; should be per-market timezone
- **No DLQ wiring** — `DeadLetterDAO` exists but `process_pending` only `mark_status="dead"`; loses LLM error context after re-runs
- **`watchlist` read once at startup** — `LLMPipeline._wl_us/_wl_cn` captured by reference; `/watch` `/unwatch` commands won't take effect without restart unless they go through same config snapshot path

---

## Test coverage gaps

**Well tested**: contracts, hashing, dedup logic, scraper parsers (mocked HTTP), classifier rules, individual pushers, prompt loader, cost tracker math, all DAOs.

**NOT tested**:
- End-to-end `process_pending` with stub LLM through `dispatcher` + `archive` + `digest`
- **Cost recording** — would have caught C1
- **Digest scheduling end-to-end** — would have caught C4
- **Webhook auth** — `test_server.py` exists but no 401 test → no contract enforcement
- **Scraper anti-crawl recovery** — `set_paused` set but no test verifies subsequent skip + `paused_until` expiry
- **Concurrent dedup** — `IntegrityError` branch correct-by-inspection but unverified
- **Burst suppressor extending-window** behavior (I8)
- **Feishu signature** — needs golden test against known-good payload (C5)
- **Tier-2 entity name collision** (case sensitivity, aliases) — likely produces dup `Entity` rows over time

---

## Action plan summary

**Before merge to main:** none required (this is OK as `v0.1.0-mvp` artifact).

**Before enabling production cron (minimum):** C1, C2, C4, C5.

**Before relying on numbers (next iteration):** all 🔴 + I1, I2, I3, I4, I5, I7.

**For long-term scale:** address all ⚠️ risks (cookie health, source-shift monitor, circuit breaker, bounded concurrency, push rate limits, timezone, DLQ wiring, hot-reload watchlist).
