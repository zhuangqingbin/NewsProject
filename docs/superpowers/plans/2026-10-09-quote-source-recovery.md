# Quote source recovery implementation plan

> **For agentic workers:** Use superpowers:executing-plans and test-driven development. Existing push/deployment authorization applies.

**Goal:** Recover market scans, industry snapshots and completed daily history when Eastmoney disconnects before sending a response.

**Architecture:** Keep Eastmoney as an explicit provider, add Tencent's public three-page stock ranking and paginated Shenwan second-level industry ranking. Production and read-only evidence choose the same environment settings. Daily history falls back to Tencent's adjusted endpoint; preserve exact shares in a nullable additive quote database column, while existing rows retain their original lot interpretation.

**Tech Stack:** Python, HTTPX, SQLAlchemy, SQLite, pytest/respx, Docker Compose.

## Evidence and limits

- Both container HTTPX and host urllib disconnect against the old, current anonymous, and daily Eastmoney endpoints. Public UT, browser headers, HTTP, proxy exclusion and DNS backend controls did not recover them. DNS differences do not establish a DNS fault or IP ban.
- Tencent rank/history endpoints return 200 from the deployed server. Three stock rankings include SH/SZ/BJ and report 5,573 stocks. This collection is not proved identical to the old Eastmoney 5,922-stock filter.
- Tencent industry `hy2` is 124 Shenwan second-level industries, different from the old multi-level Eastmoney collection. Never rename it or silently map old sector names.
- Main/ChiNext daily volume is lots, STAR is shares; amount is 万元. Persist exact shares separately rather than rounding away STAR volume.
- An after-close HTTP success is connectivity evidence. Live freshness and independent comparison remain required.

## Tasks

- [x] Write and run failing provider tests covering three sorting directions, 100-row request budget, market codes, units, industry pagination, invalid data, and provider selection.
- [x] Add strict Tencent ranking parsing and explicit provider selection to the existing feeds. Expose source/coverage in messages and evidence; log missing configured industry names.
- [x] Write and run failing history/storage tests for exact STAR shares, old schema preservation, idempotent additive migration, primary/fallback errors, completed-session filtering, and read-only legacy/new schema support.
- [x] Implement Tencent qfq history fallback, nullable `volume_shares` migration, DAO writes, and the shared exact-share read boundary. Unsupported/unverified market types must not guess units.
- [x] Update Compose to explicitly select Tencent market/industry providers and update operator instructions. Keep Eastmoney selectors available.
- [x] Run full tests, Ruff, formatting, mypy; obtain independent code review and fix blockers.
- [ ] Commit and push normally. Back up private config and consistent databases, build exact revision, restart on Aliyun, verify source probes, database integrity, image revision and health. Preserve backups and rollback image.

Verification: 871 tests passed; mypy checked 149 source files; Ruff lint and formatting passed for 292 files. Independent review approved after fixes for truncated rankings and amount overflow. Deployment evidence is saved outside Git to preserve an exact revision/image association.
