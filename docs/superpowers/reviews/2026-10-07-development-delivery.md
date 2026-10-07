# Pipeline optimization development delivery

2026-10-07. A–C implementation is complete as local, separately staged releases. This does not mean production deployment, model acceptance or the observation periods are complete. D is optional under design §5 and remains unselected.

## Reviewable code

| Release | Branch / implementation commit | Validation |
|---|---|---|
| v0.7.0 A/B plus C3–C5 and rollout fixes | `feature/pipeline-optimization` / `f97e328` | 900 passed, 1 legacy real-model test skipped; independent specification and quality review approved |
| v0.7.1 C1/C2 cleanup candidate | `codex/pipeline-cleanup` / `96ddc49`, final record `d9eba5f` | 805 passed, no skips; 78 cleanup contracts; both independent reviews approved |

The rollout release remains in the original workspace and retains legacy/shadow/v2. The cleanup branch is preserved at `/Users/qingbin.zhuang/.config/superpowers/worktrees/NewsProject/pipeline-cleanup`; it is based on `f97e328`, supports only v2, and has not been merged into the rollout branch or deployed. Its full record is `docs/superpowers/reviews/2026-10-07-pipeline-cleanup-verification.md` on that branch.

C1/C2 removes 52 legacy source files, 49 obsolete test/fixture files, four old prompts and 14 unused direct dependencies. Akshare is locked at 1.19.1; historical models/migrations, retention protections, quote functionality and generic WeCom remain. Current configuration rejects retired settings and checks qualified consumers for 35 AppConfig leaves. Ruff, mypy, strict documentation and Compose checks pass. The wheel builds and both entrypoints import successfully in a clean production-only environment using Docker's pinned uv 0.5.11. No Docker image build is claimed because the local daemon is unavailable.

The cleanup branch also passed a local upgrade of 60,832 actual raw rows on a synthetic migration-0003 schema through 0005: all original raw-column fingerprints were identical, integrity/foreign-key checks passed, all historical rows remained excluded from new processing, and no deliveries were queued. This is not a full production backup or server smoke test.

## External acceptance still required

The real three-week snapshot and source-backed 150-event CSV are prepared in the original workspace's ignored `data/b0/2026-09-14_2026-10-06/`. All 150 rows remain unreviewed. Human label/ticker correction, reviewed import with fixed 120/30 membership, actual provider-account checks, explicit paid-run confirmation and train/final-holdout model acceptance remain outstanding. No paid request or actual notification was sent by this work.

Production-IP upstream and trading-session volume checks, 2–3 trading days of shadow comparison and a stable v2 week are required before the cleanup release is deployed. D1–D7 require selection after two stable weeks and are not part of the completed mandatory A–C code scope. No production service, database or mode was changed.

See [rollout verification](2026-10-07-rollout-hardening-verification.md), [B0 acceptance](../../operations/b0-acceptance.md), [staged cleanup](../../operations/staged-cleanup.md) and the [approved design](../specs/2026-10-06-pipeline-optimization-design.md).
