# Changelog

版本历史。完整内容来自项目根目录的 `CHANGELOG.md`。

---

## v0.2.0 (2026-04-26)

### Added
- Comprehensive mkdocs documentation site under `docs/`
- mkdocs + mkdocs-material in dev deps
- 18 documentation pages organized into getting-started / components / operations / reference
- Mermaid diagrams for architecture, data flow, ER schema
- Glossary

### Notes
- Source code unchanged; this is documentation only
- Existing `docs/superpowers/` and `docs/runbook/` are linked / referenced from new pages

---

## v0.1.7

Production stabilization. Current deployed version on 8.135.67.243.

---

## v0.1.6 (2026-04-26)

### Removed
- Feishu self-built application integration (entire `archive/` module + `pushers/common/feishu_auth.py`)
- Feishu bitable archive (multidim table writeback)
- Feishu image upload via `im/v1/images`
- `lark-oapi` dependency

### Changed
- Feishu push now uses **only** custom robot webhook + sign secret (no self-built app)
- TG sendPhoto for chart embedding still works
- Feishu chart embedding silently dropped
- `secrets.yml` schema simplified: no `storage:` section

### Why
Feishu's permission model for self-built apps + bitable is hostile to single-developer use.
After 2+ hours debugging error 91403 across all OAuth scope combinations, decided to wholly
eliminate the surface area. SQLite remains source of truth; browse via Datasette.

---

## v0.1.4 (2026-04-25)

### Removed
- WeCom (企业微信) channels
- OSS (阿里云对象存储) for chart hosting — charts now embedded inline
- `chart_cache` table (Alembic migration 0003)
- `oss2` dependency

### Added
- Telegram `sendPhoto` API for chart embedding (multipart/form-data)
- `CommonMessage.chart_image: bytes | None` field

---

## v0.1.3 (2026-04-25)

### Fixed
- Replace deprecated `datetime.utcnow()` with `utc_now()` everywhere
- Wrap `runner.shutdown()` in `asyncio.wait_for(timeout=30)`
- `BurstSuppressor.should_send()` no longer appends on suppressed calls (permanent suppression bug fix)
- Anti-crawl detection for xueqiu (non-JSON content-type, error_code != 0) and ths (empty body, login page)
- `Tier1Summarizer` now forwards `cache_segments` to `LLMRequest`
- `CostTracker` is now thread-safe (threading.Lock)

### Tests
- 181 passed, 2 skipped

---

## v0.1.2 (2026-04-25)

### Added
- Tier-2/Tier-3 auto-fallback to DashScope when `anthropic_api_key` is not configured
- `pick_client_and_model` helper for routing decisions
- WARN log `anthropic_not_configured_fallback_to_tier1` on startup

---

## v0.1.1 (2026-04-25)

4 critical fixes on top of MVP:
- FeishuBitableClient tenant token
- Cost tracker concurrency
- Telegram MarkdownV2 escaping
- Shutdown timeout

---

## v0.1.0-mvp (2026-04-25)

Initial MVP release. 75 tasks, 12 phases.

- 9 scrapers (5 enabled, 4 disabled due to API changes)
- 4-tier LLM pipeline (Tier-0/1/2/3)
- 3 push platforms (Telegram, Feishu, WeCom placeholder)
- 13-table SQLite schema
- Charts (mplfinance inline)
- 11 bot commands
- DR backup

See `docs/superpowers/specs/2026-04-25-news-pipeline-design.md` for original design spec.
