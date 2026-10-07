# Rollout hardening and real B0 sample preparation

2026-10-07. This continues the approved pipeline design without deploying, migrating the server database, enabling LLMs or sending messages. Paid model requests: **0**.

## Changes and regression evidence

The shared model client now explicitly sends `enable_thinking: false` for assessment and digest JSON requests. Replay cache identities include this setting, preventing reuse of earlier responses generated with provider-default thinking. Eight request cases cover four candidate models and both token limits; a ninth test proves old-cache isolation and current-cache reuse. All nine failed against the prior implementation and pass with the fix. The current public-price and input-cost proposal is in [B0 model preparation](../../operations/b0-model-proposal.md).

A runtime audit found two rollback defects: legacy/shadow could dispatch pending v2 news, and the legacy send cache ignored successful v2 immediate deliveries. The outbox now filters delivery kinds in SQL before pagination, allowing ops through a backlog of paused news. Legacy cache rebuilding includes recent successful v2 immediate sends, without changing either raw-news status column. Seven regression cases failed against the prior implementation; all 36 affected runtime/cache tests passed after the fix. They also cover resuming v2, more than one page of paused news, shadow/pending/failed/expired sends, old sends, missing send timestamps and digest exclusion.

Independent specification and quality review subsequently completed. The quality reviewer reproduced another rollback case: a pending v2 item could be sent successfully by the legacy path during rollback, then sent again on resuming v2. Reservation now checks successful legacy sends for the same event and channel inside its existing write transaction. It marks the queue item `superseded` without adding an attempt, setting `sent_at`, or counting a v2 send. Nine new cases failed on the prior code or exercise exclusions: both rollback modes, successful statuses, failed sends, other channels/events, digest and ops items. Both reviewers approved the final fix; 45 affected tests passed. Concurrent supersession, expiry ordering and future-dated evidence were also checked.

The initial post-integration full run exposed an existing hot-reload test race: it stopped waiting after any callback, including an old-value filesystem notification. A deterministic old-then-updated callback schedule reproduced the failure. The test now waits for the expected value within the original bounded timeout; the same schedule passes, while an old-only schedule still fails. This is a test-only correction; production hot-reload behavior is unchanged. The final full run also treats unhandled worker-thread warnings as errors.

## Real source snapshot

The repository's deployment documentation identified the existing SSH target. A single read-only SQLite transaction selected the raw-news window, compressed it in server memory, closed the transaction and streamed it locally. No remote file, service, configuration, migration or database row was changed. The server was still at migration **0003**.

The window is 2026-09-14 through 2026-10-06 in Asia/Shanghai: UTC `[2026-09-13 16:00:00, 2026-10-06 16:00:00)`. Snapshot time: **2026-10-07 05:38:20 UTC**. Header count, extracted rows and completion footer all agree at **60,832**. The locally reconstructed raw-news-only SQLite snapshot passed `PRAGMA integrity_check`; it is not a full production backup.

| Source | Rows |
|---|---:|
| Sina | 33,327 |
| Futu | 12,205 |
| Eastmoney global | 8,255 |
| THS | 6,401 |
| CCTV | 321 |
| WallStreetCN | 260 |
| Finnhub | 43 |
| CJZC | 14 |
| SEC | 6 |

Local artifacts are under the original workspace's ignored `data/b0/2026-09-14_2026-10-06/`, not committed to Git:

| Artifact | SHA-256 |
|---|---|
| Complete archive `raw-news-snapshot-r2.jsonl.gz` | `53ed9d51b7b99598018c9c82391993c2d3d33bcd530a26e6bd82aa83f20d193e` |
| Read-only `news-snapshot.db` | `0a012a9fb12ce9586a07ed4943dfe1668e7c11e8c201588f6a772acb60e1923d` |
| Review CSV `review-150.csv` before human edits | `08b3bb4c5a2d72fad39efac89495b1f4a083370e177a001928238f1e818c59e4` |

The first transfer timed out and was incomplete; it was excluded from every replay and replaced by the verified complete archive. `manifest.json` records source counts, status counts, integrity and hashes. The sample directory is private to the local user, and the SQLite snapshot is read-only.

## Review dataset

Rules replay found **10,675 candidate articles, 8,473 events and 251 push events**, with a 1.2599 article/event merge ratio. These counts describe the captured window and current rules, not model acceptance or live feed health.

The seed-42 quota export contains 150 events. Eight actual source-backed cases were then forced into the selection by replacing non-case rows in the same stratum. The correctly dropped 药明巨诺 and 宁德市 articles were added as ambiguous-company hard negatives in the mention stratum. Final strata remain **50 push / 50 digest_hi / 30 mention / 20 macro**. `selection-manifest.json` records replacements, representative raw IDs and all raw IDs in the known-case groups; `prepare_review.py` records the selection procedure. Every selected title, body, source, market and raw metadata value was checked against the snapshot by its original URL. Known cases use real timestamps and URLs, not seed placeholders.

All **150** annotations remain **unreviewed**. Dataset identity before human review is `54584d47235b0a717738dcddfedec6b3c92c9023f766ef5e39921cce2bef2132`. `gold validate --acceptance` correctly exits **1** for the unreviewed dataset and absent persisted split. The actual selected-set rules replay returns **not_eligible**. Its metrics compare rules with their own prefilled labels and must not be presented as human ground truth or LLM quality evidence.

Human review must correct `label` and `tickers`, then mark genuinely reviewed rows. Import will freeze 120/30 membership by ID. An offline preview of that membership and the exact first-request text gives a conservative one-attempt reservation of **3.8403 CNY** for four training passes and the most expensive single holdout pass, using UTF-8 byte reservations and 400 output tokens. This is not billed usage, excludes retries and does not authorize paid calls.

## Verification

| Check | Result |
|---|---|
| `uv run pytest -W error::pytest.PytestUnhandledThreadExceptionWarning` | 900 passed, 1 real-model test skipped; nine existing deprecation warnings |
| `uv run ruff check .` | Passed |
| `uv run ruff format --check .` | Passed, 384 files |
| `uv run mypy src/` | Passed, 198 source files |
| `uv run mkdocs build --strict` | Passed |
| `docker compose config --quiet` | Passed |
| `git diff --check` | Passed |
| Real selected-set rules replay | 150 events; `not_eligible`; no model client or sends |

## Remaining gates

Human annotation, provider-account/model capability checks, explicit paid-run confirmation and actual train/final-holdout evaluation remain outstanding. Production-IP upstream checks and trading-session volume validation have not been completed. The 2–3 trading-day shadow period, one stable v2 week before C1/C2 and two stable weeks plus source selection before D remain unchanged. See [B0 acceptance](../../operations/b0-acceptance.md) and the [deployment guide](../../getting-started/deployment-current.md).
