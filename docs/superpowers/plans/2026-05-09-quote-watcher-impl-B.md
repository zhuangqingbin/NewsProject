# Quote Watcher Implementation Plan — Part B (S4-S7)

> **For agentic workers:** Compact plan format. Each task lists files + acceptance criteria + commit message. Implementation patterns established by Plan A still apply (TDD, specific-file `git add`, `pytest -p no:warnings 2>&1 | tail -3` for counts, ruff/mypy gates).

**Goal:** Complete the deferred sprints from Plan A:
- **S4** 全市场扫描 — top gainers / losers / volume ratio digest
- **S5** 技术指标 — MA / MACD / RSI + indicator-kind rules
- **S6** 事件 / 板块 — limit-up/down events + sector rules
- **S7** 观测 / 文档 — alerts.yml hot reload, alembic for quotes.db, preview-rules CLI, README

**Reference**:
- Spec: `docs/superpowers/specs/2026-05-08-quote-watcher-design.md`
- Plan A (S0-S3, merged): `docs/superpowers/plans/2026-05-08-quote-watcher-impl-A.md`
- Branch: `feat/v0.4.0-quote-watcher-b` from `main` (1528686)
- Baseline tests: 350 passed, 2 skipped

**Tech notes**: 
- akshare for both全市场 spot (`stock_zh_a_spot_em`) and daily K (`stock_zh_a_hist`)
- Sector data via akshare `stock_board_industry_name_em` + `stock_board_industry_cons_em`
- Hot reload via existing `watchdog` (used by news_pipeline ConfigLoader — pattern to copy)
- Alembic baseline migration on `quotes.db` (similar to news.db setup)

---

## File Structure (additions)

```
src/quote_watcher/
├── feeds/
│   ├── market_scan.py        # NEW: akshare 全市场 spot wrapper
│   └── sector.py             # NEW: akshare 板块 wrapper (S6)
├── alerts/
│   └── indicator.py          # NEW: MA / RSI / MACD / cross_above (S5)
├── store/
│   └── kline.py              # NEW: daily K loader + cache (S5)
├── scheduler/
│   └── jobs.py               # extend with: scan_market, evaluate_sector
├── tools/                    # NEW dir
│   ├── __init__.py
│   └── preview_rules.py      # NEW: CLI dry-run rule preview (S7)
└── storage/
    └── migrations/versions/
        └── 0001_initial.py   # NEW: alembic baseline (S7)

config/
├── alerts.yml                # extend with sample indicator/event rules
└── quote_watchlist.yml       # already has market_scans cfg

scripts/
└── alembic_quotes.ini        # NEW (S7)

docs/quote_watcher/
└── getting_started.md        # NEW (S7)
```

---

## Conventions

Same as Plan A. `uv run pytest`, `uv run ruff check src/ tests/`, `uv run mypy src/`. Specific-file `git add`, NEVER `git add -A`. Commit format `feat(v0.4.0): ...` or `test(v0.4.0): ...` or `docs(v0.4.0): ...`.

---

## Phase S4 — 全市场扫描 (~6 tasks)

### Task B4.1 — `feeds/market_scan.py`: akshare 全市场快照
- Create `src/quote_watcher/feeds/market_scan.py` exposing `MarketScanFeed.fetch() -> list[MarketRow]`
- `MarketRow = (ticker, name, price, pct_change, volume, amount, volume_ratio_5d_or_None)`
- Wrap `akshare.stock_zh_a_spot_em()` (returns DataFrame); convert columns; filter rows lacking essential fields
- Tests: `tests/unit/quote_watcher/feeds/test_market_scan.py` — mock akshare DataFrame fixture, verify parse + 1 row sanity
- Commit: `feat(v0.4.0): MarketScanFeed for akshare 全市场 spot`

### Task B4.2 — `MarketScanRanker` (top gainers/losers/volume_ratio)
- Create `src/quote_watcher/alerts/scan_ranker.py` with `rank_market(rows, cfg: MarketScansCfg) -> ScanResult`
- `ScanResult = (top_gainers: list[MarketRow], top_losers: list[MarketRow], top_volume_ratio: list[MarketRow])`
- Apply `cfg.only_when_score_above` filter (score = abs(pct_change) for movers, volume_ratio for vol)
- Tests: `tests/unit/quote_watcher/alerts/test_scan_ranker.py`
- Commit: `feat(v0.4.0): MarketScanRanker — top N gainers/losers/volume`

### Task B4.3 — `emit/scan_message.py`: digest CommonMessage builder
- Create `src/quote_watcher/emit/scan_message.py` exposing `build_market_scan_message(result: ScanResult) -> CommonMessage`
- Format per spec §7.4 (`📊 A 股 14:30 异动榜` + top 5 涨幅 + top 3 量比); `kind="market_scan"`
- Tests
- Commit: `feat(v0.4.0): market scan digest message builder`

### Task B4.4 — Scheduler `scan_market` job
- Append to `src/quote_watcher/scheduler/jobs.py`: `scan_market(*, feed, ranker, builder, dispatcher, calendar, channels, cfg) -> int`
- Skip when calendar closed; dispatch ONE digest message if any of three top-N lists non-empty
- Tests: `tests/unit/quote_watcher/scheduler/test_scan_market.py`
- Commit: `feat(v0.4.0): scan_market scheduler job`

### Task B4.5 — Wire scan into `main.py`
- Build MarketScanFeed + ranker + dispatcher; add a separate poll loop interval (60s default — env `QUOTE_SCAN_INTERVAL_SEC`) running `scan_market`
- Use `asyncio.gather` or two parallel loops; the existing 5s ticker poll loop stays as-is
- Tests: smoke (`timeout 6 uv run python -m quote_watcher.main` shows starting + stopped)
- Commit: `feat(v0.4.0): wire market scan into main loop`

### Task B4.6 — S4 e2e integration test
- `tests/integration/quote_watcher/test_e2e_market_scan.py` — fake akshare DataFrame, verify ranker → builder → mock dispatcher chain
- Tag `s4-complete`
- Commit: `test(v0.4.0): S4 e2e — fake akshare → market scan digest dispatch`

---

## Phase S5 — 技术指标 (~9 tasks)

### Task B5.1 — `store/kline.py` daily K cache
- Create `src/quote_watcher/store/kline.py` exposing `DailyKlineCache` with:
  - `load_for(tickers: list[str], days: int = 250) -> dict[str, list[Bar]]` (Bar dataclass: date, open, high, low, close, volume)
  - Persists to `quote_bars_daily` SQLite table (already in `models.py`)
  - Returns most recent N daily bars
- Backed by `akshare.stock_zh_a_hist(symbol=..., period="daily", start_date=..., end_date=...)` 
- Tests: `tests/unit/quote_watcher/store/test_kline.py` mock akshare, verify cache hit / miss / persist
- Commit: `feat(v0.4.0): DailyKlineCache for indicator history`

### Task B5.2 — Indicator math: MA / cross_above / cross_below
- Create `src/quote_watcher/alerts/indicator.py` with:
  - `ma(closes: list[float], n: int) -> float | None` (returns latest MA)
  - `ma_yday(closes, n) -> float | None`
  - `cross_above(today_a, today_b, yday_a, yday_b) -> bool` 
  - `cross_below(...)`
- Tests
- Commit: `feat(v0.4.0): indicator — MA + cross_above/below`

### Task B5.3 — Indicator math: RSI
- Add `rsi(closes: list[float], n: int = 14) -> float | None` to `indicator.py` (Wilder's RSI)
- Tests with known sample sequences
- Commit: `feat(v0.4.0): indicator — RSI (Wilder)`

### Task B5.4 — Indicator math: MACD
- Add `macd(closes, fast=12, slow=26, signal=9) -> MACDResult` (dif, dea, hist)
- Tests
- Commit: `feat(v0.4.0): indicator — MACD (dif/dea/hist)`

### Task B5.5 — `build_indicator_context` (extends threshold context)
- Add to `src/quote_watcher/alerts/context.py`: `build_indicator_context(snap, holding=None, *, kline_cache, volume_avg5d=...) -> dict`
- Inherits threshold ctx + adds: `ma5/ma10/ma20/ma60`, `ma5_yday/...`, `rsi(n)` callable, `macd_dif/dea/hist`, `cross_above/cross_below` callables, `highest_n_days(n) / lowest_n_days(n)` callables
- Tests
- Commit: `feat(v0.4.0): indicator context — MA/RSI/MACD/cross helpers in asteval ctx`

### Task B5.6 — AlertEngine: INDICATOR kind branch
- Extend `AlertEngine.evaluate_for_snapshot` to also handle `kind=INDICATOR + ticker matches snap.ticker`
- Reuse `_run_rules`; build context via `build_indicator_context` (passes `kline_cache` from constructor)
- Add `kline_cache: DailyKlineCache | None = None` to AlertEngine constructor
- Tests: `tests/unit/quote_watcher/alerts/test_indicator_engine.py`
- Commit: `feat(v0.4.0): AlertEngine — INDICATOR kind support`

### Task B5.7 — Startup warmup in `main.py`
- After `db.initialize()`, before launching loops: call `kline_cache.load_for(ticker_list, days=250)` to pre-populate
- Skip warmup outside trading hours? No — warmup is read-only akshare call, fine anytime
- Wrap in try/except; log warning + continue if akshare fails (degraded mode)
- Commit: `feat(v0.4.0): startup warmup of daily K for indicator rules`

### Task B5.8 — Sample alerts.yml entries + integration test
- Add 1-2 indicator rules to `config/alerts.yml` (commented out by default for safety)
- `tests/integration/quote_watcher/test_e2e_indicator.py` — synthetic K-line series, cross_above triggers
- Commit: `test(v0.4.0): S5 e2e — indicator cross_above triggers alert`

### Task B5.9 — Tag s5-complete
- Verify full suite, ruff, mypy green
- `git tag s5-complete`
- (No commit; tag only)

---

## Phase S6 — 事件 / 板块 (~7 tasks)

### Task B6.1 — Promote `is_limit_up/down` to first-class EVENT kind
- Already in threshold context. EVENT-kind rules with `target_kind=ticker` should evaluate against the same threshold context (or a slimmer event context) — no NEW math needed
- Add EVENT branch in `AlertEngine.evaluate_for_snapshot` for `target_kind=ticker`: identical to threshold path but matches `kind=EVENT`
- Tests: existing limit-up/down behavior reused; just confirm rule with `kind=event, ticker=X, expr=is_limit_up` triggers
- Commit: `feat(v0.4.0): AlertEngine — EVENT kind (target_kind=ticker)`

### Task B6.2 — `feeds/sector.py`: 板块 quote wrapper
- Wrap akshare `stock_board_industry_name_em()` for sector list + per-sector `stock_board_industry_index_em()` for index OHLC
- Expose `SectorFeed.fetch_pct_changes() -> dict[str, SectorSnapshot]` where SectorSnapshot has `pct_change`, `volume_ratio`, etc
- Tests: mock akshare DataFrames
- Commit: `feat(v0.4.0): SectorFeed — akshare 板块 quote wrapper`

### Task B6.3 — `build_sector_context`
- Add to `src/quote_watcher/alerts/context.py`: `build_sector_context(sector: str, sector_snap) -> dict`
- Vars: `sector_pct_change`, `sector_volume_ratio`
- Tests
- Commit: `feat(v0.4.0): sector context builder`

### Task B6.4 — AlertEngine: EVENT + target_kind=sector
- New method `AlertEngine.evaluate_sector(sector_snaps: dict[str, SectorSnapshot]) -> list[AlertVerdict]`
- Filter rules by `kind=EVENT, target_kind=sector, sector matches`
- AlertState key uses `_sector:<name>` to namespace cooldowns
- Tests
- Commit: `feat(v0.4.0): AlertEngine — sector event evaluation`

### Task B6.5 — Scheduler `evaluate_sector_alerts` job
- Append to `scheduler/jobs.py`: `evaluate_sector_alerts(*, feed, engine, dispatcher, channels)` — fetch sector data → engine → emit single message per verdict
- Tests
- Commit: `feat(v0.4.0): scheduler — sector alerts job`

### Task B6.6 — Wire sector into `main.py`
- Same pattern as scan_market: separate loop interval (60s default — env `QUOTE_SECTOR_INTERVAL_SEC`)
- Commit: `feat(v0.4.0): wire sector alerts into main loop`

### Task B6.7 — S6 e2e + tag
- `tests/integration/quote_watcher/test_e2e_sector.py` — fake sector DataFrame, surge triggers
- `git tag s6-complete`
- Commit: `test(v0.4.0): S6 e2e — sector surge triggers alert`

---

## Phase S7 — 观测 / 文档 (~5 tasks)

### Task B7.1 — alerts.yml hot reload
- Mirror news_pipeline ConfigLoader watchdog pattern (look at `src/news_pipeline/config/loader.py` for existing impl)
- When alerts.yml changes: re-validate AlertsFile + atomically swap `engine._rules`
- Surface a logger info line on reload success/failure
- Tests: synthetic file change → engine reflects new rules
- Commit: `feat(v0.4.0): alerts.yml hot reload via watchdog`

### Task B7.2 — Alembic baseline for quotes.db
- Create `scripts/alembic_quotes.ini` + `src/quote_watcher/storage/migrations/env.py`
- One baseline migration `0001_initial.py` capturing current 4 tables (QuoteBar1min, QuoteBarDaily, AlertState, AlertHistory)
- Update main.py: replace `Base.metadata.create_all` with `alembic upgrade head` invocation OR keep create_all for dev + alembic for prod (common pattern)
- Tests: alembic upgrade head on a fresh sqlite — all 4 tables exist
- Commit: `feat(v0.4.0): alembic baseline migration for quotes.db`

### Task B7.3 — `tools/preview_rules.py` CLI
- `uv run python -m quote_watcher.tools.preview_rules --since YYYY-MM-DD --tickers SH600519,SZ300750`
- For each day in range: replay daily K + intraday min K (if available) → run engine → print which rules would have fired (no actual push)
- Tests for the CLI argparse + dry-run output structure
- Commit: `feat(v0.4.0): preview_rules CLI for historical dry-run`

### Task B7.4 — README + getting_started docs
- Update top-level README.md with quote_watcher section: how to run, config files, deploying
- Create `docs/quote_watcher/getting_started.md` covering: install, secrets, alerts.yml DSL, holdings, troubleshooting
- Commit: `docs(v0.4.0): quote_watcher README + getting_started`

### Task B7.5 — Final regression sweep + v0.4.0 tag
- Full pytest, ruff, mypy, smoke
- `git tag s7-complete`
- `git tag v0.4.0` (the actual release tag, replacing the MVP tag)
- (No commit; tags only)

---

## Self-Review

Plan B mirrors the spec's deferred sprints exactly. No placeholder. No TBD. Each task has files + acceptance + commit message.

Caveat: the per-task implementation code is NOT inlined here (unlike Plan A). The dispatch prompts to subagents will provide concrete code blocks. This keeps the plan file focused on *what* and lets the per-task prompt drive *how*.

If at any point akshare API changes the column names of `stock_zh_a_spot_em` / `stock_zh_a_hist` / `stock_board_industry_*` — investigate at task time. The wrapper functions isolate the risk.

If alembic env.py setup is more involved than expected, S7.2 may exceed scope; in that case keep `Base.metadata.create_all` and defer alembic to a future ticket.

---

## Execution

Subagent-driven, same pattern as Plan A. Implementer subagent per task; lightweight spot-check from controller; tag at sprint boundaries.
