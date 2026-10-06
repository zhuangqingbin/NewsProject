# Pipeline Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the approved October 6 design's A and B releases, with the C operational tooling prepared for rollout.

**Architecture:** Keep SQLite, APScheduler, and Docker Compose. Repair ingestion and rules first; add independent article state, persistent events, assessments and outbox next. Keep legacy/shadow/v2 modes until production v2 has run stably for one week, as required by §4 and §8.

**Tech Stack:** Python 3.12+, SQLModel/SQLAlchemy, Alembic, httpx, Pydantic, pytest, Ruff, mypy.

**Scope gates:** D is explicitly conditional on two weeks of production observation and is excluded from this release. C1/C2 removal of legacy paths and dependencies follows the one-week stability gate; do not remove the rollback path now. Model benchmarking requires a human-reviewed sample and authorization for paid calls; build the tools and leave LLM disabled until pricing/model selection is complete. No production deploy or credential reset is part of this implementation.

## Task 1: Repair quote feeds (A7)

Files: `src/quote_watcher/feeds/{base,tencent,em_scan,market_scan,sector}.py`, `alerts/context.py`, quote feed tests.

- [ ] Write Tencent fixture tests for main-board/ChiNext volume ×100, STAR volume unchanged, fields 47–49 and malformed records. Add respx tests proving market scans issue three sorted requests and sectors page until total is covered.
- [ ] Run `uv run pytest tests/unit/quote_watcher/feeds tests/unit/quote_watcher/alerts/test_context.py` and observe the new tests fail.
- [ ] Implement `TencentFeed.fetch(tickers)`, the snapshot fields, direct Eastmoney scanning/sector feeds and context's source-provided volume ratio/limit-price preference.
- [ ] Verify those tests; preserve `SinaFeed` and existing constructors for compatibility.

## Task 2: Repair news sources (A2)

Files: `scrapers/common/contract.py`, `scrapers/{cn,us}/*.py`, `scrapers/factory.py`, scraper tests.

- [ ] Add recorded-response tests for CLS, Eastmoney search JSONP, WallstreetCN lives, CNInfo orgId/timestamps, SEC submissions/Items and missing columns/paths.
- [ ] Run `uv run pytest tests/unit/scrapers` to establish failing regression tests.
- [ ] Implement the endpoints/mapping exactly as §2.2; cache metadata daily; use configured SEC contact UA, 7-ticker fallback, and raise structural errors instead of silently returning empty results.
- [ ] Verify `uv run pytest tests/unit/scrapers`; no real upstream requests in tests.

## Task 3: Rules v2, config and similarity (A3/A4 foundation)

Files: `config/schema.py`, `config/loader.py`, `rules/{aliases,headline,scoring,first_party,engine,verdict}.py`, `events/similarity.py`, configuration YAML, rule/config tests.

- [ ] Write tests for §B.3 cases, alias exclusions/ASCII boundaries/config rejection, first-party tiers, four headline shapes and §B.4 similarity positive/negative cases.
- [ ] Run `uv run pytest tests/unit/rules tests/unit/config` and confirm new behavior fails.
- [ ] Implement the §C vocabularies, RulesVerdict v2, scoring and similarity preserving decimal/percentage numbers before stripping punctuation. Keep compatibility accessors for legacy consumers during shadow rollout.
- [ ] Add typed A/B settings and load optional scoring/first-party files. Reject enabled LLM models without positive prices.
- [ ] Verify the targeted tests and Ruff.

## Task 4: Ingestion, health, migrations and event storage (A1/A6/B1/B2)

Files: `storage/models.py`, migrations `0004/0005`, raw/source/event DAOs, `ingest/store.py`, `health/source_health.py`, `events/clusterer.py`, storage/ingest/event tests.

- [ ] Add tests for delayed articles despite newer watermarks, first-run seeding, URL batches/in-batch duplicates, simhash duplicate evidence, exponential backoff and health transitions.
- [ ] Add old-schema migration tests: selective source-state backfill, all historical raw rows set to legacy, independent pending index and events FTS insert/update/delete.
- [ ] Add SQLite clustering integration tests with same-event merging, 6h/12h windows, reassessment on stronger evidence, first-party representative and repeat reparenting.
- [ ] Run those tests red, then implement the additive models/migrations and transactional DAOs/clusterer.
- [ ] Verify all storage/event tests.

## Task 5: Assessment and decision policy (B0/B3/B4)

Files: `assess/{client,schema,prompts,assessor}.py`, `deliver/policy.py`, assessment/policy tests, `tools/replay.py`, `tests/eval/gold_events.jsonl`.

- [ ] Test schema sanitization, retry classes, invalid JSON retry, token/cost persistence, day cap, ten-failure circuit breaker, reset after ten minutes.
- [ ] Test the materiality/directness/confidence/freshness/quiet-hours/first-party matrix and rule disagreement protection.
- [ ] Implement reusable HTTP client and prompts from §3.4, bounded concurrency and durable budget accounting. No live LLM calls.
- [ ] Build replay/eval/export CLI, read-only input database and disk response cache. Include the eight documented cases as seed fixtures, marking human annotation outstanding rather than inventing a reviewed 150-event gold set.
- [ ] Verify assessment/policy/eval tests.

## Task 6: Persistent delivery and digest (B5/B6/B7)

Files: `deliver/{outbox,digest,cards}.py`, delivery DAO, delivery/digest tests.

- [ ] Test retry timestamps, channel rate limits, persistence across worker restarts, immediate expiry-to-digest, shadow never sends, duplicate enqueue protection.
- [ ] Test digest candidate ordering, successful-send consumption, recovery after failure, reference sanitization, rule fallback, 20KB payload trimming and original article links.
- [ ] Implement decision-to-delivery transactions, card rendering, outbox and structured digest. Retain candidates until delivery succeeds, including preselected-but-unshown ids as §3.7 requires.
- [ ] Verify delivery tests and full article→event→fake-assessment→fake-outbox integration.

## Task 7: Wire runtime and fix legacy delivery (A4/A5/A6/A8/B8)

Files: `main.py`, `scheduler/{jobs,runner}.py`, legacy DAOs, quote runtime, shared heartbeat/calendar/logging, Docker files and integration tests.

- [ ] Test all three mode registrations and isolated `status`/`v2_state`; legacy freshness, burst-to-digest, persisted send dedup and digest retries.
- [ ] Implement lookback+timeout ingestion, heartbeat/completed jobs, state-change health checks, daily ops/shadow comparison, market-local digest schedules and graceful client shutdown.
- [ ] Wire Tencent default feed/8s timeout, startup probes and five-minute quote outage/recovery monitoring.
- [ ] Gate migrations with `RUN_MIGRATIONS=1` only on app; protect secrets ignore and suppress HTTP credential-bearing INFO logs.
- [ ] Verify one-shot startup and Compose/entrypoint behavior with fake dependencies.

## Task 8: Operational tooling and final review (C3–C5)

Files: `health/{smoke,leak_check,ops_report}.py`, retention job/DAO, deployment/components docs, CHANGELOG/version.

- [ ] Test retention preserves event-linked/history rows, deletes children before parents, shadow 30d and LLM 180d cutoffs; schedule monthly vacuum separately.
- [ ] Implement weekly/CLI smoke and leak checks with fetch timeouts, contract errors and zero-output assertions, without duplicating scrape ingest.
- [ ] Update deployment/config docs and add an explicit C1/C2 post-stability checklist.
- [ ] Run `uv run pytest`, `uv run ruff check`, `uv run ruff format --check`, `uv run mypy src/` and migration checks.
- [ ] Obtain independent spec review followed by code-quality review, fix material findings and rerun affected checks.

## Implementation status

Baseline setup: use `uv sync --frozen` in isolated worktree; globally installed Python 3.11 lacks project dependencies and is not a valid test environment.

Production-only checks remain: actual source reachability, reviewed 150-event gold set/model benchmark, 2–3 trading-day shadow comparison, first quote trading-session volume validation, and one-week v2 stability gate before C1/C2.
