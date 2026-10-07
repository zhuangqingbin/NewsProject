# B0 preparation and local upstream verification

2026-10-07, initial B0 tooling checkpoint. This extends the approved design §3.10 tooling. At this checkpoint no real 150-event dataset, human review, model quality acceptance, production deployment or outbound message was performed, and the workspace had no news database or local secrets configuration. The [later follow-up](2026-10-07-rollout-hardening-verification.md) records the real snapshot and review CSV subsequently obtained.

## Development changes

- Review CSV retains stable identifiers, source/market/time/URL/metadata and corrected annotations. Missing stratum quota is reported rather than filled from another stratum; existing files are preserved.
- The new `news_pipeline.tools.gold` importer requires explicit reviewed status, rejects malformed/duplicate evidence and publishes JSONL atomically without replacing an existing file. Seed cases remain usable only for regression.
- Validation checks exactly 150 events, 50/50/30/20 strata, eight known cases, complete evidence and deterministic persisted 120/30 train/holdout membership. Reordering or correcting labels does not move the reserved members.
- Replay defaults to train whenever membership exists, retains full-dataset identity in the selected-set report and checks all five thresholds. Rules, seed and train reports are not eligible for final model acceptance. Budget fallbacks from evaluated gold rows are included in the report.
- A shared Eastmoney request now follows HTTP redirects, with market/sector regression tests that fail on the former 302 handling.

## Local upstream observations

Read-only requests from the developer Mac ran at **2026-10-07 02:41:22–02:41:26 UTC**. There were 13 probes and 16 requests: 11 probes returned successfully, while two Eastmoney quote probes failed before parsing. No database/ingestion/pusher/model was used; no secrets were read. Finnhub and SEC were excluded because a real token/contact User-Agent was unavailable.

| Source | Result | Coverage |
|---|---|---|
| CLS | HTTP 200, 20 parsed | Broad news |
| Eastmoney global | HTTP 200, 65 parsed | Broad news |
| THS | HTTP 200, 11 parsed | Broad news |
| Sina | HTTP 200, 20 parsed | Broad news |
| CJZC | Two HTTP 200 pages, 0 after lookback | Empty result is not a freshness pass |
| CCTV | HTTP 200, 1 parsed | Index and one segment only |
| Futu | HTTP 200, 50 parsed | Broad news |
| WallStreetCN | HTTP 200, 40 parsed | Broad news |
| Eastmoney stock news | HTTP 200, 1 parsed | One ticker: 600519 |
| CNInfo | HTTP 200, 30 parsed | Organization map and one ticker's page one only |
| Tencent | HTTP 200, 3 parsed | Mainboard/ChiNext/STAR representatives |
| Eastmoney spot | HTTP 302 to push2delay, raised HTTPStatusError | Before redirect fix |
| Eastmoney sector | HTTP 302 to push2delay, raised HTTPStatusError | Before redirect fix |

CNInfo's date-only announcement times were normalized to fetch time as required by the design; their parsed timestamps do not establish publication freshness. Tencent timestamps were 2026-09-30, not the probe date. Volume outputs were 3,833,100 shares (600519), 29,699,500 (300750), 8,588,771 (688256); these were not independently verified against a trading-session reference.

After the redirect fix, public read-only Eastmoney rechecks at **02:44:02–02:44:03 UTC** both returned HTTP 502 from the original host. No redirect was available to follow in that recheck. The handling fix is established by regression tests; upstream recovery is not established.

These developer-IP observations do not replace production-IP reachability, trading-session freshness or volume-unit acceptance.

## Verification

Specification review approved the final behavior and independently ran 108 affected tests. Code-quality review found and verified fixes for URL validation consistency and long CSV fields; the final 80 gold/replay tests passed in independent review. Long bodies remain intact, and the CSV field-size setting is restored after success and failure. An integration regression covers export, explicit review corrections, import and rules replay.

Full repository verification after these fixes:

| Check | Result |
|---|---|
| `uv run pytest -W error::pytest.PytestUnhandledThreadExceptionWarning` | 868 passed, 1 real-model test skipped |
| `uv run ruff check .` | Passed |
| `uv run ruff format --check .` | Passed, 384 files |
| `uv run mypy src/` | Passed, 198 source files |
| `uv run mkdocs build --strict` | Passed |
| `docker compose config --quiet` | Passed |
| `git diff --check` | Passed |
| Actual seed CLI validation | Exit 1 for acceptance, explicit incomplete evidence; rules replay remains `not_eligible` |

The nine existing deprecation warnings are unchanged; there were no worker-thread warnings. The skipped integration test requires a real model and was not enabled.

## Remaining gates

The user has been asked for the real three-week database location. Real source-backed samples and human annotation remain necessary. Candidate models, verified prices and a concrete cost estimate must be confirmed before paid model calls. B0 model acceptance still precedes shadow observation, then stable v2 observation and the gated C1/C2/D work. See the [B0 workflow](../../operations/b0-acceptance.md) and [implementation plan](../plans/2026-10-07-b0-acceptance-impl.md).
