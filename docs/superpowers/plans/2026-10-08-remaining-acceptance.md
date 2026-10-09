# Remaining pipeline acceptance implementation

**Goal:** Fix the daily-volume unit mismatch and make the remaining live feed acceptance reproducible without changing production data or sending alerts.

**Architecture:** Keep existing daily K-line database volumes in AKShare lots for compatibility. Convert to shares once when reading domain bars, sharing that boundary with rule preview. Add a read-only evidence collector that uses the existing feed clients and cached completed bars; it reports missing evidence explicitly and does not claim human acceptance.

**Tech stack:** Python 3.13, asyncio/httpx, SQLAlchemy/SQLite, pytest.

## 1. Normalize daily volume at the read boundary

- [x] Add regressions covering cold/warm/legacy caches, main board/ChiNext/STAR tickers, preview, and alert units.
- [x] Run the tests and confirm the expected unit mismatch failures.
- [x] Convert persisted lots to domain shares once, reuse in preview, and label alert shares correctly.
- [x] Run focused quote tests.

## 2. Collect read-only A7 feed evidence

- [x] Test collection with fresh/stale/absent quotes, outside market hours, failing sources, and unchanged SQLite files.
- [x] Add a CLI collecting Tencent representative quotes, market/sector feed counts and cached 5/20-day share averages.
- [x] Make eligibility depend on an open trading session and fresh quotes; keep independent software comparison as a required manual step.
- [x] Document usage, evidence meaning and the October 8 live acceptance procedure (correcting the design's October 9 date against the exchange calendar).

## 3. Verify against the deployed source version

- [x] Export `575b35b` to a permitted temporary directory and apply the local source/test changes.
- [x] Run the relevant tests and latest-version full checks, then request focused review.
- [x] Save a reviewable patch and record what cannot currently be verified: SSH/network access, human B0 labels and paid model budget, trading-day and stability observation gates.

No paid model calls, human label approvals, production database migrations or deployment are implied by these offline checks. The current session denies SSH and Git metadata writes, so publication remains pending.

## Execution record

Implemented and verified locally on October 8. Independent review found stale and partial daily-cache risks; both have regression coverage and fixes. Full latest-version export: 841 tests passed. A separate historical replay-clock bug discovered by the full run was fixed with a failing-then-passing regression. Publication and live/manual gates remain pending; see `../reviews/2026-10-08-remaining-acceptance-verification.md`.
