# Pipeline v0.7.1 cleanup implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans task-by-task. Track progress with checkboxes.

**Goal:** Complete the approved design §4.1–4.4 cleanup as reviewable development on an isolated future-release branch, preserving the v0.7.0 rollback release.

**Architecture:** v0.7.1 runs only the event/assessment/outbox path. Remove legacy runtime, scrapers, LLM tiers, commands and charts; preserve database migrations, historical tables and quote-watcher features. Do not merge this branch into the rollout release or deploy it until the design's B0/shadow/one-week stability gates are actually met.

**Tech Stack:** Existing Python/SQLModel/httpx/pytest/uv stack. No model or external notification calls during development.

**Workspace:** `/Users/qingbin.zhuang/.config/superpowers/worktrees/NewsProject/pipeline-cleanup`, branch `codex/pipeline-cleanup`, initial baseline `db33f22`, final base `f97e328`. Original `feature/pipeline-optimization` and `codex/pipeline-optimization` retain legacy/shadow rollback.

## Task 1: Remove the legacy runtime and stale configuration

**Modify:** `runtime.py`, `main.py`, `scheduler/jobs.py`, `config/{schema,loader}.py`, `ingest/store.py`, `storage/dao/raw_news.py`, `scrapers/factory.py`, `health/ops_report.py`, common hashing and active scraper imports; bundled YAML and affected tests.

**Delete:** The precise legacy modules/DAOs listed in design §4.1, their obsolete tests, old prompts, legacy sent-event cache and its runtime-only helpers if no active consumer remains. Do not delete history tables, migrations, `shared/push/wecom.py`, quote-watcher kline/alerts/reloader or active feeds.

- [x] Add failing cleanup contracts in `tests/unit/optimization/test_cleanup.py`: only v2 is accepted; removed app/watchlist fields are rejected; no legacy job is registered; same-title/different-URL articles are retained with stored simhash 0; no prohibited runtime imports or legacy source registrations; historical tables still exist after initialization.

```python
@pytest.mark.parametrize("mode", ["legacy", "shadow"])
def test_retired_modes_are_rejected(mode):
    with pytest.raises(ValidationError):
        AppConfig(pipeline={"mode": mode})
```

- [x] Run `uv run pytest tests/unit/optimization/test_cleanup.py -q` and observe the current implementation fail for these contracts, then implement minimal cleanup.
- [x] Keep `PipelineCfg.mode: Literal["v2"] = "v2"`. Keep LLM disabled and pricing empty. Remove unused runtime, classifier/dedup/charts/dead-letter/retention settings, legacy scheduler digest aliases and old tier fields. Remove watchlist's old `llm` section, unused legacy keyword/matcher/alerts settings; preserve rule aliases and first-party/scoring settings. Preserve `effective_us/cn()` as rules-only helpers for assessment/replay callers.
- [x] Replace scheduler jobs with the current `scrape_one_source` ingestion path and only its live dependencies. Remove old processing, digest, dedup and synthetic-enrichment APIs. Use `ArticleStore(raw)` with URL deduplication only, and persist simhash 0 at the raw DAO boundary. Do not mutate historical simhash values.
- [x] Remove legacy state/methods from runtime and mode branching from jobs, decisions, digest and ops report. Existing historical shadow deliveries remain excluded from live outbox by status; do not turn them into pending deliveries.
- [x] Preserve additive migrations 0001–0005, historical models/tables and retention protection for raw rows referenced by `news_processed`. No new migration or table deletion.
- [x] Update active fixtures that contain retired settings. Remove tests solely for deleted behavior; retain and adapt all active source, event, assessment, policy, delivery, retention and quote tests.
- [x] Verify cleanup contracts and full suite, then independent specification and quality review. Both reviews approved after the shared-model checker finding and documentation corrections. Commit the combined staged cleanup release.

## Task 2: Enforce configuration consumption

**Modify:** `tests/unit/optimization/test_cleanup.py` and only any genuinely unused remaining configuration leaf revealed by the check.

- [x] Walk `AppConfig` nested Pydantic models and check runtime source references for every retained leaf, excluding schema declarations and migrations. Do not let a duplicated field name in another section or a test count as a consumer.
- [x] Exercise the checker against a synthetic unused leaf to prove it fails. Remove truly unused leaves or connect an already-required consumer; do not add fake source references to pass the test.
- [x] Run `uv run pytest tests/unit/optimization/test_cleanup.py -q`, Ruff and mypy. Commit with Task 1 or as a separate focused fix if it exposes a consumer defect.

## Task 3: Slim dependencies and stage the release

**Modify:** `pyproject.toml`, `uv.lock`, `Dockerfile`, active deployment/config/component documentation, `CHANGELOG.md`.

- [x] Search retained source imports before removing the fourteen direct dependencies in §4.4: telegram, FastAPI, uvicorn, tushare, yfinance, mplfinance, matplotlib, tenacity, dashscope, BeautifulSoup, aiolimiter, simhash, anthropic, feedparser. Keep transitive dependencies required by akshare and watchdog required by quote alerts.
- [x] Verify the latest available akshare release from authoritative PyPI/project sources, update its minimum version and regenerate the lock with `uv lock --upgrade-package akshare`. Keep a record of the resolved version. Verify fixture contracts without claiming server-IP smoke.
- [x] Remove the Docker runtime CJK-font install block, set version 0.7.1, sync the clean environment with `uv sync --frozen`, and run all retained tests.
- [x] Rewrite current docs for the single v2 architecture and exact config removals. Document that v0.7.1 is staged/unreleased and gated by one stable v2 week; rollback uses the preserved v0.7.0 image and config. Keep historical evidence clearly dated.
- [x] Run `uv run pytest -W error::pytest.PytestUnhandledThreadExceptionWarning`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src/`, `uv run mkdocs build --strict`, `docker compose config --quiet`, and `git diff --check`. Build a wheel to verify packaging; no Docker daemon is available locally, so do not claim an image build.
- [x] Obtain final independent review, fix material findings, commit the staged release. Record exact commit/test evidence without merging into the v0.7.0 rollout branch.

## External and optional scope

B0 human review and paid-call confirmation remain required; the existing 150-event CSV is not human-reviewed. No production mode switch, paid request or notification is authorized by this development plan. D1–D7 are optional by §5 and are awaiting the user's selection; default is disabled and deployment remains gated by two stable weeks. Model/account and source/network checks cannot be replaced with fixture tests.

## Verification evidence

See [C1/C2 verification](../reviews/2026-10-07-pipeline-cleanup-verification.md). The rollout resume guard from `f97e328` is retained; the reviewed cleanup was rebased onto that commit. Its tree was confirmed identical to the approved pre-rebase tree; the two conflicts retained the reviewed v2 deployment guidance and v2-only runtime tests.
