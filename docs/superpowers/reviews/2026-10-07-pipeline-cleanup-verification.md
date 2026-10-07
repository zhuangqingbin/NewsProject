# Staged v0.7.1 C1/C2 verification

2026-10-07. The user requested completion of development. C1/C2 is developed on the isolated `codex/pipeline-cleanup` branch while `feature/pipeline-optimization` retains the v0.7.0 legacy/shadow rollout and rollback paths. No production deployment, mode switch, paid model call or notification was performed.

## Implementation and preservation

Removed 52 legacy source files, 49 obsolete tests/fixtures and four old prompt YAML files. Runtime and scheduler now support only v2; old mode/config values are rejected. Ingestion keeps every distinct URL and stores new simhash values as zero, preserving historical values. Legacy tiers, commands/charts, classifier/router, unused scrapers, old write DAOs and news YAML watching are absent.

Historical models, migrations 0001–0005, raw-news retention protection, quote-watcher implementation and the generic WeCom pusher are unchanged. Historical shadow items remain excluded from sending. The reviewed rollout-resume guard from `f97e328` remains in DeliveryDAO, including seven DAO cases for successful legacy sends and their exclusions.

The configuration check covers 35 AppConfig leaf paths, excluding schema declarations, migrations and test code. It follows typed roots, aliases and actual method-call arguments. Initial cleanup contracts failed before implementation. Self-review and independent review then exposed false credit for repeated model types; separate red/green probes now prevent unused sections, duplicated field names and an unrelated helper from satisfying a setting. All 78 cleanup contracts pass, including real Alembic initialization of historical tables and preservation of old simhash values.

## Dependencies and packaging

Fourteen unused direct dependencies were removed; the application now has 14 direct dependencies and 90 lock entries (previously 134; 44 entries removed). `watchdog` remains for quote alerts. `beautifulsoup4` remains transitively required by akshare. Docker's runtime font installation was removed.

The [PyPI release](https://pypi.org/project/akshare/) and [upstream release](https://github.com/akfamily/akshare/releases/tag/release-v1.19.1) identified akshare 1.19.1 as the latest available version; its minimum and lock are updated. Fixture contracts pass with this installed version, but server-IP reachability has not been measured.

`uv sync --frozen` passed. A separate clean environment installed 54 production packages using the Dockerfile's pinned uv 0.5.11 with `--frozen --no-dev --no-install-project`. The wheel builds successfully and contains active v2, quote-watcher, WeCom and retained migrations, without retired package paths. Installing that wheel without dependencies into this environment and importing both application entrypoints under isolated Python mode passed; imports resolve to installed site-packages, not the checkout. The local Docker daemon is unavailable; no container image build is claimed.

## Actual raw-data migration check

A temporary local database was created with the real migrations through 0003, populated with all **60,832** rows from the verified read-only source snapshot, then upgraded through 0005. It is a synthetic schema populated with actual raw data, **not** a full production clone or backup; historical/source-state rows were not extracted from production.

Integrity and foreign-key checks passed. Every original raw column, including old status and simhash, has the same ordered SHA-256 fingerprint before and after: `61be9d4f5aa64537f54b503428204354591d18c1cee97c72d7782cf10e26f226`. All 60,832 rows become `v2_state='legacy'`, with no queued deliveries. The original snapshot hash remains `0a012a9fb12ce9586a07ed4943dfe1668e7c11e8c201588f6a772acb60e1923d`.

## Checks

| Check | Result |
|---|---|
| `uv run pytest -o addopts='' -W error::pytest.PytestUnhandledThreadExceptionWarning` | 805 passed; no skipped legacy model test remains |
| `uv run ruff check .` | Passed |
| `uv run ruff format --check .` | Passed, 285 files |
| `uv run mypy src/` | Passed, 146 source files |
| `uv run mkdocs build --strict` | Passed |
| `docker compose config --quiet` | Passed |
| `git diff --check` | Passed |
| `uv build --wheel` and wheel inventory | Passed |
| Independent specification review | Approved; 142 targeted tests passed |
| Independent quality review | Approved; 526 targeted tests passed, Ruff/mypy/diff checks passed |

## Remaining release conditions

The 150 real B0 events remain unreviewed. Human annotation, actual account/model checks, paid-run confirmation, train/final-holdout acceptance, production-IP smoke and trading-session volume checks remain outstanding. v0.7.0 still needs 2–3 trading days of shadow observation and one stable v2 week before this cleanup release is deployed. D1–D7 are optional and require selection after two stable weeks; none was silently added to this release. See [staged cleanup](../../operations/staged-cleanup.md), [B0 acceptance](../../operations/b0-acceptance.md) and [deployment](../../getting-started/deployment-current.md).
