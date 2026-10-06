# Pipeline optimization implementation verification

2026-10-06. Implements the approved design's A and B code and C3–C5 operational preparation. Default configuration remains `pipeline.mode: legacy` and `llm.enabled: false`. This report describes development verification, not a production release or model acceptance result.

## Verification evidence

| Check | Result |
|---|---|
| `uv run pytest -W error::pytest.PytestUnhandledThreadExceptionWarning` | 796 passed, 1 real-model test skipped |
| `uv run ruff check` | Passed |
| `uv run ruff format --check` | Passed, 382 files |
| `uv run mypy src/` | Passed, 197 source files |
| `docker compose config --quiet` | Passed |
| `uv run mkdocs build --strict` | Passed; navigation and documentation links validated |
| `git diff --check` | Passed |
| Alembic fresh/0003-to-head migration, source backfill and event FTS | Passed in temporary SQLite databases |
| Three-mode one-shot startup | Passed with migrated temporary databases and fake upstreams |
| Replay CLI, explicit rules evaluation | Passed without an LLM client or paid request |

The clean baseline was 439 passed and 2 skipped. Remaining warnings are eight existing HTTP cookie deprecations in disabled legacy scraper tests and one existing `datetime.utcnow` deprecation. Quote test fixtures now dispose every database connection: an independent lifecycle check counted 66 created and 66 closed, with no leaked connections or worker-thread warnings.

## Independent review

Source/ingestion/event/health/rules/quote review and delivery/runtime reviews completed without remaining material findings after fixes. Regression tests cover signed simhash distance, silent empty-source recovery, stronger-evidence reassessment, restarted send deduplication, stale decisions, repeat target chains and cycles, per-source ingestion statistics, shutdown cleanup, actual digest display counts, mixed-market links, all assessment labels, recap-only output, omitted-event footers and local-market dates.

Immediate decisions and deliveries commit together. Digest deliveries for all target channels are enqueued in one transaction; candidate consumption waits for all channels to succeed. Shadow news and digests never dispatch. Infrastructure reports remain live during shadow observation. The manual smoke command sends its report by default; `--no-report` prints JSON without sending, and probes never ingest articles.

## Gates that remain

- B0 requires a real three-week dataset, 150 human-reviewed labels, 30 held-out cases and explicitly authorized model benchmarking. The eight checked-in examples remain `seed_unreviewed`; their rule results are not model acceptance evidence.
- Before enabling LLM, fill verified positive per-million-token model prices and real credentials. Before using SEC, replace the contact placeholder or set `SEC_USER_AGENT`.
- Live source reachability from the deployment IP and quote volume units must be checked in a trading session. No live upstream or production latency/accuracy claim is made here.
- Observe shadow for 2–3 trading days before switching to v2. C1/C2 code/config/dependency deletion waits for one stable v2 week; D source expansion waits for two weeks and selection. These production conditions cannot be completed by offline development.
- Production deployment, outbound messages and paid model requests were not performed during this implementation.

The rollback paths, old dependencies and historical tables are intentionally retained under those gates. Referenced legacy articles are protected by retention, as described in the storage guide. Digest selection currently reads a market's retained delivery history; limiting that query to necessary metadata is a future performance improvement, not an unresolved correctness issue.

See [implementation plan](../plans/2026-10-06-pipeline-optimization-impl.md), [deployment guide](../../getting-started/deployment-current.md) and [post-stability cleanup checklist](../../operations/staged-cleanup.md).
