# Quote Watcher MVP Implementation Plan — Part A (S0-S3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up a working `quote_watcher` subsystem (sibling to `news_pipeline`) that polls Sina A-shares quotes every 5s, evaluates `threshold` + `composite` (holdings) alert rules, and pushes to Feishu via a shared push layer. End state: a useful but minimal盯盘 service running alongside news pipeline.

**Architecture:** Two-step refactor + new subsystem. S0 moves `pushers/` + `observability/` + the cross-cutting parts of `common/` from `news_pipeline/` to `shared/` so both subsystems can import. S1-S3 build `quote_watcher/` from scratch: `feeds/sina.py` polls Sina, `store/tick.py` buffers, `alerts/engine.py` evaluates `asteval` expressions against `QuoteSnapshot` context, `state/tracker.py` enforces cooldowns, `emit/message.py` produces `CommonMessage`, and `shared/push/dispatcher.py` delivers.

**Tech Stack:** Python 3.12, pydantic v2, asteval, aiohttp, chinese_calendar, APScheduler, SQLAlchemy + alembic, pytest + pytest-asyncio.

**Reference spec:** `docs/superpowers/specs/2026-05-08-quote-watcher-design.md` — consult for any ambiguity.

**Out of scope (deferred to Plan B):** S4 全市场扫描 / S5 技术指标(MA/MACD/RSI) / S6 事件 + 板块 / S7 观测+文档. Build Plan B after Plan A is running in production for ≥1 week.

---

## File Structure

```
src/
├── shared/                                     # NEW package (created in S0)
│   ├── __init__.py
│   ├── push/                                   # ← git mv from news_pipeline/pushers/
│   │   ├── __init__.py  base.py  burst.py
│   │   ├── dispatcher.py  factory.py
│   │   ├── feishu.py  wecom.py
│   │   └── common/
│   │       ├── __init__.py  message_builder.py  retry.py
│   ├── observability/                          # ← git mv from news_pipeline/observability/
│   │   ├── __init__.py  alert.py  log.py
│   │   └── weekly_report.py
│   └── common/                                 # ← split out shared parts
│       ├── __init__.py
│       ├── contracts.py                        # CommonMessage / Badge / Deeplink / DigestItem
│       ├── enums.py                            # Market enum (used by both)
│       ├── timeutil.py                         # utc_now, beijing_now
│       └── hashing.py                          # url_hash, title_simhash (move-only; news still uses)
│
├── quote_watcher/                              # NEW subsystem
│   ├── __init__.py
│   ├── main.py                                 # async entry point
│   ├── feeds/
│   │   ├── __init__.py
│   │   ├── base.py                             # QuoteFeed Protocol
│   │   ├── sina.py                             # Sina HTTP poll
│   │   └── calendar.py                         # MarketCalendar
│   ├── store/
│   │   ├── __init__.py
│   │   ├── tick.py                             # in-memory ring buffer
│   │   └── bar.py                              # 1min bar aggregator (writes SQLite)
│   ├── alerts/
│   │   ├── __init__.py
│   │   ├── rule.py                             # AlertRule, AlertKind, AlertsFile schema
│   │   ├── verdict.py                          # AlertVerdict, AlertContext
│   │   ├── context.py                          # build_context(snap, holdings, portfolio)
│   │   └── engine.py                           # AlertEngine
│   ├── state/
│   │   ├── __init__.py
│   │   └── tracker.py                          # StateTracker (cooldown + bump_count)
│   ├── emit/
│   │   ├── __init__.py
│   │   └── message.py                          # AlertVerdict[] → CommonMessage
│   ├── scheduler/
│   │   ├── __init__.py
│   │   └── jobs.py                             # poll_quotes, evaluate_alerts, evaluate_portfolio
│   └── storage/
│       ├── __init__.py
│       ├── db.py                               # QuoteDatabase wrapper (uses data/quotes.db)
│       ├── models.py                           # QuoteBar1min, QuoteBarDaily, AlertState, AlertHistory
│       ├── migrations/                         # Alembic migrations for quotes.db
│       │   └── versions/0001_initial.py
│       └── dao/
│           ├── __init__.py
│           ├── alert_state.py
│           ├── alert_history.py
│           └── quote_bars.py
│
└── news_pipeline/                              # MODIFIED in S0 (imports change only)
    └── (everything that referenced pushers/observability/common moved/shared bits)

config/
├── quote_watchlist.yml                         # NEW
├── alerts.yml                                  # NEW
├── holdings.yml                                # NEW
└── (existing yml files: app/channels/secrets/sources/watchlist — unchanged)

scripts/
├── alembic_quotes.ini                          # NEW
└── seed_quote_watchlist.py                     # NEW (interactive helper)

tests/
├── unit/
│   ├── shared/                                 # ← moved from tests/unit/{pushers,observability,common}/
│   │   ├── push/test_*                         #  + import-only changes
│   │   ├── observability/test_*
│   │   └── common/test_contracts.py  test_enums.py
│   └── quote_watcher/                          # NEW
│       ├── feeds/test_calendar.py  test_sina_parse.py
│       ├── store/test_tick.py  test_bar.py
│       ├── alerts/test_rule_schema.py  test_context.py  test_engine.py
│       ├── state/test_tracker.py
│       ├── emit/test_message.py  test_burst_merge.py
│       └── storage/test_dao.py
└── integration/
    └── quote_watcher/
        ├── test_e2e_threshold.py               # fake Sina → trigger → mock feishu
        ├── test_e2e_composite.py               # holdings → portfolio rule
        └── test_news_pipeline_unchanged.py     # regression after refactor
```

---

## Conventions

- **Working dir**: `/Users/qingbin.zhuang/Personal/NewsProject`
- **Test runner**: `uv run pytest`
- **Lint**: `uv run ruff check src/ tests/`
- **Type**: `uv run mypy src/`
- **Async tests**: `@pytest.mark.asyncio` (project config has `pytest-asyncio mode=auto`)
- **TDD where applicable**: test → fail → impl → pass → commit. Pure config / glue / migrations skip TDD.
- **Commit format**:
  - S0 refactor: `refactor(v0.4.0): ...`
  - S1-S3 features: `feat(v0.4.0): ...`
  - Tests-only: `test(v0.4.0): ...`
- **Each task ends with a commit step** so progress is recoverable.

---

## Phase 0 — Dependencies + Empty Skeleton

### Task 1: Add deps and create empty package skeletons

**Files:**
- Modify: `pyproject.toml`
- Create: `src/shared/__init__.py`, `src/shared/push/__init__.py`, `src/shared/observability/__init__.py`, `src/shared/common/__init__.py`
- Create: `src/quote_watcher/__init__.py` and all subpackage `__init__.py` files (feeds, store, alerts, state, emit, scheduler, storage, storage/dao, storage/migrations, storage/migrations/versions)
- Create: `tests/unit/shared/__init__.py`, `tests/unit/quote_watcher/__init__.py` and subpackage tests dirs

- [ ] **Step 1: Add deps**

```bash
uv add asteval chinese-calendar
```

Verify they appear in `pyproject.toml` under `[project.dependencies]`.

- [ ] **Step 2: Create empty package skeletons**

```bash
mkdir -p src/shared/push src/shared/observability src/shared/common
mkdir -p src/quote_watcher/{feeds,store,alerts,state,emit,scheduler,storage/dao,storage/migrations/versions}
mkdir -p tests/unit/shared/{push,observability,common}
mkdir -p tests/unit/quote_watcher/{feeds,store,alerts,state,emit,storage}
mkdir -p tests/integration/quote_watcher

for d in \
  src/shared src/shared/push src/shared/observability src/shared/common \
  src/quote_watcher src/quote_watcher/feeds src/quote_watcher/store \
  src/quote_watcher/alerts src/quote_watcher/state src/quote_watcher/emit \
  src/quote_watcher/scheduler src/quote_watcher/storage \
  src/quote_watcher/storage/dao src/quote_watcher/storage/migrations \
  src/quote_watcher/storage/migrations/versions \
  tests/unit/shared tests/unit/shared/push tests/unit/shared/observability \
  tests/unit/shared/common tests/unit/quote_watcher \
  tests/unit/quote_watcher/feeds tests/unit/quote_watcher/store \
  tests/unit/quote_watcher/alerts tests/unit/quote_watcher/state \
  tests/unit/quote_watcher/emit tests/unit/quote_watcher/storage \
  tests/integration/quote_watcher
do
  touch "$d/__init__.py"
done
```

- [ ] **Step 3: Verify pyproject.toml `packages.find` discovers shared and quote_watcher**

```bash
uv run python -c "import shared, quote_watcher; print('ok')"
```
Expected: `ok`. If it fails with ModuleNotFoundError, check `pyproject.toml` has `[tool.setuptools.packages.find] where = ["src"]` (or equivalent for hatchling).

- [ ] **Step 4: Run baseline tests to confirm nothing broke**

```bash
uv run pytest -q
```
Expected: all existing tests pass.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock src/shared src/quote_watcher tests/unit/shared tests/unit/quote_watcher tests/integration/quote_watcher
git commit -m "feat(v0.4.0): add asteval+chinese-calendar deps and empty shared/quote_watcher skeleton"
```

---

## Phase 1 (S0) — Refactor: move shared infra out of news_pipeline

> Each refactor task is a self-contained git mv + import-rewrite + tests-pass + commit. **All news_pipeline tests must remain green after each task** — that's the whole point of S0.

### Task R1: Move `pushers/` → `shared/push/`

**Files:**
- Move: entire `src/news_pipeline/pushers/` directory tree → `src/shared/push/`
- Move: `tests/unit/pushers/` → `tests/unit/shared/push/`
- Modify: every file with `from news_pipeline.pushers` (in `src/` and `tests/`)

- [ ] **Step 1: Inventory imports first**

```bash
grep -rn "from news_pipeline.pushers\|import news_pipeline.pushers" src/ tests/ | tee /tmp/r1_imports.txt
```
Save the count for later verification.

- [ ] **Step 2: git mv the source tree**

```bash
git rm -r src/shared/push        # remove the empty placeholder dir we made in Task 1
git mv src/news_pipeline/pushers src/shared/push
```

- [ ] **Step 3: git mv the tests**

```bash
git rm -r tests/unit/shared/push
git mv tests/unit/pushers tests/unit/shared/push
```

- [ ] **Step 4: Rewrite imports en masse**

```bash
grep -rl "news_pipeline.pushers" src/ tests/ \
  | xargs sed -i '' 's|news_pipeline\.pushers|shared.push|g'
```

Verify:
```bash
grep -rn "news_pipeline.pushers" src/ tests/ || echo "ALL CLEAR"
```
Expected: `ALL CLEAR`.

- [ ] **Step 5: Run all tests and lint**

```bash
uv run pytest -q
uv run ruff check src/ tests/
uv run mypy src/
```
Expected: green across the board. If a test fails, it's an import or path issue — fix before committing.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor(v0.4.0): move news_pipeline/pushers → shared/push (R1)"
git tag refactor-step-r1
```

---

### Task R2: Move `observability/` → `shared/observability/`

**Files:**
- Move: `src/news_pipeline/observability/` → `src/shared/observability/`
- Move: `tests/unit/observability/` → `tests/unit/shared/observability/`
- Rewrite imports in all `src/` and `tests/`

- [ ] **Step 1: Inventory imports**

```bash
grep -rn "from news_pipeline.observability\|import news_pipeline.observability" src/ tests/
```

- [ ] **Step 2: git mv source + tests**

```bash
git rm -r src/shared/observability
git mv src/news_pipeline/observability src/shared/observability

if [ -d tests/unit/observability ]; then
  git rm -r tests/unit/shared/observability
  git mv tests/unit/observability tests/unit/shared/observability
fi
```

- [ ] **Step 3: Rewrite imports**

```bash
grep -rl "news_pipeline.observability" src/ tests/ \
  | xargs sed -i '' 's|news_pipeline\.observability|shared.observability|g'

grep -rn "news_pipeline.observability" src/ tests/ || echo "ALL CLEAR"
```

- [ ] **Step 4: Tests + lint + type**

```bash
uv run pytest -q
uv run ruff check src/ tests/
uv run mypy src/
```

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor(v0.4.0): move news_pipeline/observability → shared/observability (R2)"
git tag refactor-step-r2
```

---

### Task R3: Split `common/contracts.py` — push types → `shared/common/contracts.py`

`CommonMessage`, `Badge`, `Deeplink`, `DigestItem` go to `shared/`. `RawArticle`, `EnrichedNews`, `ScoredNews`, `Entity`, `Relation` stay in `news_pipeline/common/contracts.py` (news-pipeline-specific).

**Files:**
- Create: `src/shared/common/contracts.py`
- Modify: `src/news_pipeline/common/contracts.py` (remove migrated classes; re-export them for backward compat)
- Modify: every importer of those classes
- Move: `tests/unit/common/test_contracts.py` cases for migrated classes → `tests/unit/shared/common/test_contracts.py`

- [ ] **Step 1: Read current contracts.py to identify what to migrate**

```bash
uv run python -c "
from news_pipeline.common import contracts
import inspect
for name in dir(contracts):
    if name.startswith('_'): continue
    obj = getattr(contracts, name)
    if inspect.isclass(obj) and obj.__module__ == 'news_pipeline.common.contracts':
        print(name)
"
```

You should see: `RawArticle, EnrichedNews, ScoredNews, Entity, Relation, CommonMessage, Badge, Deeplink, DigestItem`. The first 5 stay; the last 4 + `_Base` move.

- [ ] **Step 2: Create `src/shared/common/contracts.py`**

```python
# src/shared/common/contracts.py
"""Push-layer data contracts shared between news_pipeline and quote_watcher."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from shared.common.enums import Market


class _Base(BaseModel):
    model_config = ConfigDict(use_enum_values=False, extra="forbid")


class Badge(_Base):
    text: str
    color: str = "gray"  # gray|green|red|yellow|blue


class Deeplink(_Base):
    label: str
    url: HttpUrl


class DigestItem(_Base):
    source_label: str
    url: HttpUrl
    summary: str


class CommonMessage(_Base):
    title: str
    summary: str
    source_label: str
    source_url: HttpUrl
    badges: list[Badge] = Field(default_factory=list)
    chart_url: HttpUrl | None = None
    chart_image: bytes | None = None
    deeplinks: list[Deeplink] = Field(default_factory=list)
    market: Market
    digest_items: list[DigestItem] = Field(default_factory=list)
    kind: Literal["news", "alert", "alert_burst", "market_scan", "digest"] = "news"
```

Note: this requires `shared/common/enums.py` to exist with `Market`. We do that in Task R4. **For now, leave Market import as `from news_pipeline.common.enums import Market`** and we'll patch it in R4.

Adjust the import in this file accordingly:

```python
# Temporary in R3 — fixed in R4
from news_pipeline.common.enums import Market
```

- [ ] **Step 3: Trim `news_pipeline/common/contracts.py` and add re-exports**

Edit `src/news_pipeline/common/contracts.py`: delete the `Badge`, `Deeplink`, `DigestItem`, `CommonMessage` class definitions. Add this re-export block at the bottom:

```python
# Re-exports for backward compatibility (R3 — will be removed once all imports migrated in step 4)
from shared.common.contracts import Badge, Deeplink, DigestItem, CommonMessage  # noqa: F401, E402
```

This keeps `from news_pipeline.common.contracts import CommonMessage` working until step 4 finishes.

- [ ] **Step 4: Migrate importers to direct shared.common.contracts imports**

Find them:
```bash
grep -rln "from news_pipeline.common.contracts import" src/ tests/ | tee /tmp/r3_files.txt
```

For each file, leave imports of `RawArticle / EnrichedNews / ScoredNews / Entity / Relation` alone, but rewrite the message-related ones. Manual edit (script-able but error-prone — review each):

For example in `src/news_pipeline/scheduler/jobs.py`:
```python
# before
from news_pipeline.common.contracts import (
    Badge, CommonMessage, DigestItem, EnrichedNews, RawArticle, ScoredNews,
)

# after
from news_pipeline.common.contracts import EnrichedNews, RawArticle, ScoredNews
from shared.common.contracts import Badge, CommonMessage, DigestItem
```

Apply the same split to `src/news_pipeline/main.py`, `src/news_pipeline/pushers/...` (now at `src/shared/push/...` — these should already be using `from shared.common.contracts` since they live in shared now), `src/news_pipeline/router/routes.py`, etc.

- [ ] **Step 5: Move tests for migrated classes**

```bash
# If tests/unit/common/test_contracts.py exists, split it.
# Move CommonMessage/Badge/Deeplink/DigestItem cases into tests/unit/shared/common/test_contracts.py
# Leave news-specific contract tests in tests/unit/common/test_contracts.py
```

If the tests for the migrated classes are minimal, you may just `git mv` the whole file:
```bash
git mv tests/unit/common/test_contracts.py tests/unit/shared/common/test_contracts.py
```
Then split mentally — but the tests use `from news_pipeline.common.contracts import ...` which still works (re-export). After Step 6 we drop re-exports.

- [ ] **Step 6: Drop re-exports from news_pipeline/common/contracts.py**

After step 4 completes — all importers migrated — remove the re-export block. Verify no breakage:
```bash
grep -rn "from news_pipeline.common.contracts import.*\(Badge\|Deeplink\|DigestItem\|CommonMessage\)" src/ tests/ || echo "ALL CLEAR"
```

- [ ] **Step 7: Tests + lint + type**

```bash
uv run pytest -q
uv run ruff check src/ tests/
uv run mypy src/
```

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "refactor(v0.4.0): split contracts.py — push types to shared/common (R3)"
git tag refactor-step-r3
```

---

### Task R4: Move shared parts of `common/{enums,timeutil,hashing}.py` → `shared/common/`

`Market` enum is used by both subsystems → moves to shared. News-specific enums (`EntityType`, `EventType`, `Magnitude`, `Predicate`, `Sentiment`) stay in `news_pipeline/common/enums.py`. `utc_now` and friends in `timeutil.py` are universal → move. `hashing.py` is only used by news scrapers right now → keep in news_pipeline (do NOT migrate).

**Files:**
- Create: `src/shared/common/enums.py`, `src/shared/common/timeutil.py`
- Modify: `src/news_pipeline/common/enums.py` (remove `Market`, add re-export)
- Modify: `src/news_pipeline/common/timeutil.py` (re-export from shared) — OR delete entirely if it has no news-specific code
- Modify: `src/shared/common/contracts.py` (fix the temporary import from R3)
- Modify: every importer of `Market` / `utc_now`

- [ ] **Step 1: Inspect the files to decide split**

```bash
uv run python -c "
from news_pipeline.common import enums
print([n for n in dir(enums) if not n.startswith('_')])
"
```
Expected: includes `EntityType, EventType, Magnitude, Market, Predicate, Sentiment`. Only `Market` moves.

```bash
cat src/news_pipeline/common/timeutil.py
```
If this file is just `utc_now()` and similar timezone-agnostic helpers, move it whole to `shared/common/timeutil.py`. Otherwise split.

- [ ] **Step 2: Create `src/shared/common/enums.py`**

```python
# src/shared/common/enums.py
from enum import StrEnum


class Market(StrEnum):
    US = "us"
    CN = "cn"
```

- [ ] **Step 3: Create `src/shared/common/timeutil.py`**

If the existing file is fully shareable, move it:
```bash
git mv src/news_pipeline/common/timeutil.py src/shared/common/timeutil.py
```
Then add a re-export shim at `src/news_pipeline/common/timeutil.py` (re-create file):
```python
# src/news_pipeline/common/timeutil.py
"""Re-export shim. Prefer `from shared.common.timeutil import ...` in new code."""
from shared.common.timeutil import *  # noqa: F401, F403
```

If the file has news-specific helpers, copy the shareable parts to shared and leave the rest.

- [ ] **Step 4: Trim `news_pipeline/common/enums.py`**

Edit `src/news_pipeline/common/enums.py`: delete `Market` class. Add re-export:
```python
from shared.common.enums import Market  # noqa: F401
```

- [ ] **Step 5: Patch `src/shared/common/contracts.py` import**

Replace the temporary line from R3:
```python
# before
from news_pipeline.common.enums import Market

# after
from shared.common.enums import Market
```

- [ ] **Step 6: Migrate Market importers in src/ and tests/ (the bulk are here)**

```bash
# Find all Market uses
grep -rln "from news_pipeline.common.enums import.*Market" src/ tests/ | tee /tmp/r4_files.txt
```

For each file: keep news-specific enums in the existing import line; add a separate `from shared.common.enums import Market`. Example:
```python
# before
from news_pipeline.common.enums import EntityType, EventType, Market, Sentiment

# after
from news_pipeline.common.enums import EntityType, EventType, Sentiment
from shared.common.enums import Market
```

You can do this with sed for the simple uniform case but **review the diff** before committing — some imports might be on multiple lines.

- [ ] **Step 7: Tests + lint + type**

```bash
uv run pytest -q
uv run ruff check src/ tests/
uv run mypy src/
```

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "refactor(v0.4.0): move Market enum + timeutil to shared/common (R4)"
git tag refactor-step-r4
```

---

### Task R5: Final regression sweep

**Files:** none (verification only)

- [ ] **Step 1: Full test + lint + type + pre-commit**

```bash
uv run pytest -v 2>&1 | tail -20
uv run ruff check src/ tests/
uv run mypy src/
uv run pre-commit run --all-files
```
Expected: all green. If pre-commit auto-fixes anything, stage and amend the previous commit:
```bash
git add -A
git commit --amend --no-edit
```

- [ ] **Step 2: Quick smoke import check**

```bash
uv run python -c "
from shared.push.feishu import FeishuPusher
from shared.push.dispatcher import PusherDispatcher
from shared.observability.log import get_logger
from shared.common.contracts import CommonMessage, Badge
from shared.common.enums import Market
from shared.common.timeutil import utc_now
print('shared imports OK')

from news_pipeline.main import _amain
from news_pipeline.scrapers.factory import build_registry
from news_pipeline.common.contracts import RawArticle, EnrichedNews
print('news_pipeline imports OK')
"
```
Expected: both lines printed.

- [ ] **Step 3: Run the existing news_pipeline once-mode end-to-end (no real network if env not set)**

```bash
# This may need NEWS_PIPELINE_ONCE=1 and a test secrets.yml — skip if not feasible
NEWS_PIPELINE_ONCE=1 uv run python -m news_pipeline.main 2>&1 | tail -5
```
The exact behavior depends on env. Goal: confirm there are no `ImportError` / `AttributeError` at startup. Failure modes from missing secrets are acceptable, but `ModuleNotFoundError: shared.push` is not.

- [ ] **Step 4: Tag refactor done**

```bash
git tag refactor-complete-s0
```

No new commit needed — just a tag for rollback.

---

## Phase 2 (S1) — Quote Watcher skeleton + Sina poll

### Task 2.1: Market calendar

**Files:**
- Create: `src/quote_watcher/feeds/calendar.py`
- Create: `tests/unit/quote_watcher/feeds/test_calendar.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/quote_watcher/feeds/test_calendar.py
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from quote_watcher.feeds.calendar import MarketCalendar

BJ = ZoneInfo("Asia/Shanghai")


@pytest.mark.parametrize("dt_str,expected", [
    ("2026-05-08 10:00", True),    # Friday, 10:00 — morning session
    ("2026-05-08 12:30", False),   # noon break
    ("2026-05-08 14:00", True),    # afternoon session
    ("2026-05-08 16:00", False),   # post-close
    ("2026-05-08 08:00", False),   # pre-open
    ("2026-05-09 10:00", False),   # Saturday
    ("2026-05-10 10:00", False),   # Sunday
    ("2026-05-01 10:00", False),   # Labor Day holiday
])
def test_is_open(dt_str, expected):
    dt = datetime.fromisoformat(dt_str).replace(tzinfo=BJ)
    cal = MarketCalendar()
    assert cal.is_open(dt) is expected


def test_session_labels():
    cal = MarketCalendar()
    assert cal.session(datetime(2026, 5, 8, 9, 0, tzinfo=BJ)) == "pre"
    assert cal.session(datetime(2026, 5, 8, 10, 0, tzinfo=BJ)) == "morning"
    assert cal.session(datetime(2026, 5, 8, 12, 0, tzinfo=BJ)) == "noon_break"
    assert cal.session(datetime(2026, 5, 8, 14, 0, tzinfo=BJ)) == "afternoon"
    assert cal.session(datetime(2026, 5, 8, 16, 0, tzinfo=BJ)) == "post"
    assert cal.session(datetime(2026, 5, 9, 10, 0, tzinfo=BJ)) == "closed"  # Saturday
```

- [ ] **Step 2: Run test, expect it to fail**

```bash
uv run pytest tests/unit/quote_watcher/feeds/test_calendar.py -v
```
Expected: ModuleNotFoundError on `MarketCalendar`.

- [ ] **Step 3: Implement MarketCalendar**

```python
# src/quote_watcher/feeds/calendar.py
"""A-share market calendar: trading hours + holidays."""
from __future__ import annotations

from datetime import datetime, time
from typing import Literal
from zoneinfo import ZoneInfo

import chinese_calendar

BJ = ZoneInfo("Asia/Shanghai")
MORNING_OPEN = time(9, 30)
MORNING_CLOSE = time(11, 30)
AFTERNOON_OPEN = time(13, 0)
AFTERNOON_CLOSE = time(15, 0)

Session = Literal["pre", "morning", "noon_break", "afternoon", "post", "closed"]


class MarketCalendar:
    """A-share trading calendar (timezone-aware)."""

    def is_open(self, dt: datetime) -> bool:
        return self.session(dt) in ("morning", "afternoon")

    def session(self, dt: datetime) -> Session:
        if dt.tzinfo is None:
            raise ValueError("dt must be timezone-aware")
        bj = dt.astimezone(BJ)
        date = bj.date()
        if date.weekday() >= 5 or chinese_calendar.is_holiday(date):
            return "closed"
        t = bj.time()
        if t < MORNING_OPEN:
            return "pre"
        if t < MORNING_CLOSE:
            return "morning"
        if t < AFTERNOON_OPEN:
            return "noon_break"
        if t < AFTERNOON_CLOSE:
            return "afternoon"
        return "post"
```

- [ ] **Step 4: Run tests, expect them to pass**

```bash
uv run pytest tests/unit/quote_watcher/feeds/test_calendar.py -v
```
Expected: 8/9 PASS (8 parametrized + 1 session test).

- [ ] **Step 5: Commit**

```bash
git add src/quote_watcher/feeds/calendar.py tests/unit/quote_watcher/feeds/test_calendar.py
git commit -m "feat(v0.4.0): MarketCalendar for A-share trading hours + holidays"
```

---

### Task 2.2: QuoteSnapshot dataclass + Sina parser

**Files:**
- Create: `src/quote_watcher/feeds/base.py` (Protocol + QuoteSnapshot)
- Create: `src/quote_watcher/feeds/sina.py` (parser only — HTTP layer in next task)
- Create: `tests/unit/quote_watcher/feeds/test_sina_parse.py`

Sina returns lines like:
```
var hq_str_sh600519="贵州茅台,1820.000,1815.500,1789.500,1825.000,1788.000,1789.500,1789.510,2823100,5043500000.00,200,1789.500,500,1789.450,...,2026-05-08,15:00:25,00";
```
We parse the comma-separated payload into `QuoteSnapshot`. Field order is documented at sina; we use the canonical first 11 fields + timestamp.

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/quote_watcher/feeds/test_sina_parse.py
import pytest

from quote_watcher.feeds.base import QuoteSnapshot
from quote_watcher.feeds.sina import parse_sina_response

SAMPLE_SH = (
    'var hq_str_sh600519="贵州茅台,1820.000,1815.500,1789.500,'
    '1825.000,1788.000,1789.500,1789.510,2823100,5043500000.00,'
    '200,1789.500,500,1789.450,300,1789.400,400,1789.350,500,1789.300,'
    '100,1789.510,200,1789.520,300,1789.530,400,1789.540,500,1789.550,'
    '2026-05-08,15:00:25,00";\n'
)
SAMPLE_SZ_SUSPENDED = 'var hq_str_sz000001="";\n'  # suspended/halted


def test_parse_sina_normal():
    out = parse_sina_response(SAMPLE_SH)
    assert len(out) == 1
    snap = out[0]
    assert snap.ticker == "600519"
    assert snap.market == "SH"
    assert snap.name == "贵州茅台"
    assert snap.open == 1820.0
    assert snap.prev_close == 1815.5
    assert snap.price == 1789.5
    assert snap.high == 1825.0
    assert snap.low == 1788.0
    assert snap.bid1 == 1789.5
    assert snap.ask1 == 1789.51
    assert snap.volume == 2823100
    assert snap.amount == pytest.approx(5043500000.0)
    assert snap.pct_change == pytest.approx((1789.5 - 1815.5) / 1815.5 * 100, rel=1e-6)
    assert snap.ts.year == 2026 and snap.ts.month == 5 and snap.ts.day == 8


def test_parse_sina_suspended_stock_skipped():
    out = parse_sina_response(SAMPLE_SZ_SUSPENDED)
    assert out == []


def test_parse_sina_multi_line():
    payload = SAMPLE_SH + SAMPLE_SZ_SUSPENDED
    out = parse_sina_response(payload)
    assert len(out) == 1
    assert out[0].ticker == "600519"
```

- [ ] **Step 2: Run, expect fail**

```bash
uv run pytest tests/unit/quote_watcher/feeds/test_sina_parse.py -v
```
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement QuoteSnapshot in `feeds/base.py`**

```python
# src/quote_watcher/feeds/base.py
"""Quote feed contracts."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class QuoteSnapshot:
    ticker: str
    market: str         # "SH" | "SZ" | "BJ"
    name: str
    ts: datetime        # timezone-aware (Asia/Shanghai)
    price: float
    open: float
    high: float
    low: float
    prev_close: float
    volume: int
    amount: float
    bid1: float
    ask1: float

    @property
    def pct_change(self) -> float:
        if self.prev_close == 0:
            return 0.0
        return (self.price - self.prev_close) / self.prev_close * 100


class QuoteFeed(Protocol):
    source_id: str

    async def fetch(self, tickers: list[tuple[str, str]]) -> Sequence[QuoteSnapshot]:
        """tickers: list of (market, ticker) — e.g. [('SH', '600519'), ('SZ', '300750')]."""
        ...
```

- [ ] **Step 4: Implement `parse_sina_response` in `feeds/sina.py`**

```python
# src/quote_watcher/feeds/sina.py
"""Sina HQ feed parser. Network layer follows in next task."""
from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from quote_watcher.feeds.base import QuoteSnapshot

BJ = ZoneInfo("Asia/Shanghai")
_LINE_RE = re.compile(
    r'var hq_str_(?P<mkt>sh|sz|bj)(?P<code>\d{6})="(?P<payload>[^"]*)";'
)


def parse_sina_response(text: str) -> list[QuoteSnapshot]:
    """Parse Sina hq.sinajs.cn response into QuoteSnapshot list.

    Suspended / halted stocks return empty payload — skipped.
    """
    out: list[QuoteSnapshot] = []
    for m in _LINE_RE.finditer(text):
        payload = m.group("payload")
        if not payload.strip():
            continue
        fields = payload.split(",")
        if len(fields) < 32:
            continue
        try:
            snap = QuoteSnapshot(
                ticker=m.group("code"),
                market=m.group("mkt").upper(),
                name=fields[0],
                ts=_parse_ts(fields[30], fields[31]),
                open=float(fields[1]),
                prev_close=float(fields[2]),
                price=float(fields[3]),
                high=float(fields[4]),
                low=float(fields[5]),
                bid1=float(fields[6]),
                ask1=float(fields[7]),
                volume=int(fields[8]),
                amount=float(fields[9]),
            )
        except (ValueError, IndexError):
            continue
        out.append(snap)
    return out


def _parse_ts(date_str: str, time_str: str) -> datetime:
    return datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=BJ)
```

- [ ] **Step 5: Run tests, expect pass**

```bash
uv run pytest tests/unit/quote_watcher/feeds/test_sina_parse.py -v
```
Expected: 3 PASS.

- [ ] **Step 6: Commit**

```bash
git add src/quote_watcher/feeds/base.py src/quote_watcher/feeds/sina.py tests/unit/quote_watcher/feeds/test_sina_parse.py
git commit -m "feat(v0.4.0): QuoteSnapshot dataclass + Sina HQ response parser"
```

---

### Task 2.3: Sina HTTP client (network layer)

**Files:**
- Modify: `src/quote_watcher/feeds/sina.py` (add `SinaFeed` class)
- Create: `tests/unit/quote_watcher/feeds/test_sina_feed.py`

- [ ] **Step 1: Write the failing test (uses respx for httpx mock)**

```python
# tests/unit/quote_watcher/feeds/test_sina_feed.py
import httpx
import pytest
import respx

from quote_watcher.feeds.sina import SinaFeed

SAMPLE = (
    'var hq_str_sh600519="贵州茅台,1820.000,1815.500,1789.500,1825.000,'
    '1788.000,1789.500,1789.510,2823100,5043500000.00,'
    '200,1789.500,500,1789.450,300,1789.400,400,1789.350,500,1789.300,'
    '100,1789.510,200,1789.520,300,1789.530,400,1789.540,500,1789.550,'
    '2026-05-08,15:00:25,00";\n'
)


@pytest.mark.asyncio
@respx.mock
async def test_fetch_builds_url_and_parses():
    respx.get("https://hq.sinajs.cn/list=sh600519").mock(
        return_value=httpx.Response(200, content=SAMPLE.encode("gbk"))
    )
    feed = SinaFeed()
    snaps = await feed.fetch([("SH", "600519")])
    assert len(snaps) == 1
    assert snaps[0].ticker == "600519"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_retries_on_5xx():
    route = respx.get("https://hq.sinajs.cn/list=sh600519").mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(200, content=SAMPLE.encode("gbk")),
        ]
    )
    feed = SinaFeed()
    snaps = await feed.fetch([("SH", "600519")])
    assert len(snaps) == 1
    assert route.call_count == 2
```

If respx is not yet a dev dep:
```bash
uv add --dev respx
```

- [ ] **Step 2: Run, expect fail**

```bash
uv run pytest tests/unit/quote_watcher/feeds/test_sina_feed.py -v
```

- [ ] **Step 3: Implement SinaFeed**

Append to `src/quote_watcher/feeds/sina.py`:

```python
import asyncio
import httpx

from collections.abc import Sequence

from shared.observability.log import get_logger

log = get_logger(__name__)


class SinaFeed:
    source_id = "sina_hq"

    def __init__(self, *, timeout_sec: float = 5.0, max_retries: int = 1) -> None:
        self._timeout = timeout_sec
        self._max_retries = max_retries

    async def fetch(self, tickers: list[tuple[str, str]]) -> Sequence[QuoteSnapshot]:
        if not tickers:
            return []
        codes = ",".join(f"{m.lower()}{c}" for m, c in tickers)
        url = f"https://hq.sinajs.cn/list={codes}"
        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.get(url, headers={"Referer": "https://finance.sina.com.cn/"})
                if resp.status_code >= 500:
                    last_exc = httpx.HTTPStatusError(
                        f"sina {resp.status_code}", request=resp.request, response=resp
                    )
                    await asyncio.sleep(2.0)
                    continue
                resp.raise_for_status()
                # Sina returns gbk-encoded body
                text = resp.content.decode("gbk", errors="replace")
                return parse_sina_response(text)
            except (httpx.TimeoutException, httpx.HTTPError) as e:
                last_exc = e
                if attempt < self._max_retries:
                    await asyncio.sleep(2.0)
                    continue
                log.warning("sina_fetch_failed", error=str(e), tickers=len(tickers))
        if last_exc is not None:
            log.warning("sina_fetch_exhausted", error=str(last_exc))
        return []
```

- [ ] **Step 4: Run, expect pass**

```bash
uv run pytest tests/unit/quote_watcher/feeds/test_sina_feed.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/quote_watcher/feeds/sina.py tests/unit/quote_watcher/feeds/test_sina_feed.py pyproject.toml uv.lock
git commit -m "feat(v0.4.0): SinaFeed HTTP client with retry on 5xx"
```

---

### Task 2.4: Tick ring buffer

**Files:**
- Create: `src/quote_watcher/store/tick.py`
- Create: `tests/unit/quote_watcher/store/test_tick.py`

- [ ] **Step 1: Failing test**

```python
# tests/unit/quote_watcher/store/test_tick.py
from datetime import datetime, timezone

from quote_watcher.feeds.base import QuoteSnapshot
from quote_watcher.store.tick import TickRing


def make_snap(ticker: str, price: float, ts: int = 0) -> QuoteSnapshot:
    return QuoteSnapshot(
        ticker=ticker, market="SH", name="X",
        ts=datetime.fromtimestamp(ts, tz=timezone.utc),
        price=price, open=0, high=0, low=0, prev_close=price,
        volume=0, amount=0.0, bid1=0, ask1=0,
    )


def test_append_and_latest():
    ring = TickRing(max_per_ticker=3)
    ring.append(make_snap("600519", 100.0, 1))
    ring.append(make_snap("600519", 101.0, 2))
    assert ring.latest("600519").price == 101.0
    assert ring.size("600519") == 2


def test_ring_max_size_evicts_oldest():
    ring = TickRing(max_per_ticker=2)
    ring.append(make_snap("600519", 1.0, 1))
    ring.append(make_snap("600519", 2.0, 2))
    ring.append(make_snap("600519", 3.0, 3))
    assert ring.size("600519") == 2
    assert ring.latest("600519").price == 3.0
    history = ring.history("600519")
    assert [s.price for s in history] == [2.0, 3.0]


def test_no_data_returns_none():
    ring = TickRing()
    assert ring.latest("000001") is None
    assert ring.size("000001") == 0
    assert ring.history("000001") == []
```

- [ ] **Step 2: Run, expect fail**

```bash
uv run pytest tests/unit/quote_watcher/store/test_tick.py -v
```

- [ ] **Step 3: Implement TickRing**

```python
# src/quote_watcher/store/tick.py
"""In-memory ring buffer for current-day ticks per ticker."""
from __future__ import annotations

from collections import deque
from collections.abc import Sequence

from quote_watcher.feeds.base import QuoteSnapshot


class TickRing:
    def __init__(self, max_per_ticker: int = 1000) -> None:
        self._max = max_per_ticker
        self._data: dict[str, deque[QuoteSnapshot]] = {}

    def append(self, snap: QuoteSnapshot) -> None:
        dq = self._data.setdefault(snap.ticker, deque(maxlen=self._max))
        dq.append(snap)

    def latest(self, ticker: str) -> QuoteSnapshot | None:
        dq = self._data.get(ticker)
        return dq[-1] if dq else None

    def history(self, ticker: str) -> Sequence[QuoteSnapshot]:
        dq = self._data.get(ticker)
        return list(dq) if dq else []

    def size(self, ticker: str) -> int:
        dq = self._data.get(ticker)
        return len(dq) if dq else 0
```

- [ ] **Step 4: Run, expect pass**

```bash
uv run pytest tests/unit/quote_watcher/store/test_tick.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/quote_watcher/store/tick.py tests/unit/quote_watcher/store/test_tick.py
git commit -m "feat(v0.4.0): TickRing in-memory buffer"
```

---

### Task 2.5: QuoteWatchlistFile schema + sample yaml

**Files:**
- Modify: `src/news_pipeline/config/schema.py` (add new schemas — keep alongside existing)
- Create: `config/quote_watchlist.yml`
- Create: `tests/unit/config/test_quote_watchlist_schema.py`

> Note: even though `quote_watcher` is a sibling subsystem, we keep the pydantic schemas in the existing `news_pipeline/config/schema.py` for now to avoid scope creep. A future refactor can move config schemas to `shared/config/`.

- [ ] **Step 1: Failing test**

```python
# tests/unit/config/test_quote_watchlist_schema.py
import pytest
from pydantic import ValidationError

from news_pipeline.config.schema import (
    QuoteTickerEntry,
    QuoteWatchlistFile,
    MarketScansCfg,
)


def test_minimal_quote_watchlist():
    f = QuoteWatchlistFile(cn=[
        QuoteTickerEntry(ticker="600519", name="贵州茅台", market="SH"),
    ])
    assert f.cn[0].ticker == "600519"
    assert f.us == []
    assert f.market_scans == {}


def test_duplicate_ticker_rejected():
    with pytest.raises(ValidationError, match="duplicate"):
        QuoteWatchlistFile(cn=[
            QuoteTickerEntry(ticker="600519", name="X", market="SH"),
            QuoteTickerEntry(ticker="600519", name="Y", market="SH"),
        ])


def test_market_scans_defaults():
    cfg = MarketScansCfg()
    assert cfg.top_gainers_n == 50
    assert cfg.push_top_n == 5
```

- [ ] **Step 2: Run, expect fail**

```bash
uv run pytest tests/unit/config/test_quote_watchlist_schema.py -v
```

- [ ] **Step 3: Add schemas to `src/news_pipeline/config/schema.py`**

Locate the file and append these classes (do not remove existing classes):

```python
from typing import Literal

from pydantic import Field, model_validator

# ... existing imports + classes above this point ...


class QuoteTickerEntry(_Base):
    ticker: str
    name: str
    market: Literal["SH", "SZ", "BJ"]


class MarketScansCfg(_Base):
    top_gainers_n: int = 50
    top_losers_n: int = 50
    top_volume_ratio_n: int = 50
    push_top_n: int = 5
    only_when_score_above: float = 8.0


class QuoteWatchlistFile(_Base):
    cn: list[QuoteTickerEntry] = Field(default_factory=list)
    us: list[QuoteTickerEntry] = Field(default_factory=list)
    market_scans: dict[str, MarketScansCfg] = Field(default_factory=dict)

    @model_validator(mode="after")
    def cn_tickers_unique(self) -> "QuoteWatchlistFile":
        for market_attr in ("cn", "us"):
            seen: set[str] = set()
            for e in getattr(self, market_attr):
                if e.ticker in seen:
                    raise ValueError(f"duplicate ticker {e.ticker} in {market_attr}")
                seen.add(e.ticker)
        return self
```

- [ ] **Step 4: Add config loader support**

Find `src/news_pipeline/config/loader.py`. Add a method to load `quote_watchlist.yml`. Look at how `watchlist.yml` is loaded and follow the same pattern. (The exact code depends on the existing loader structure.) Example pattern:

```python
# In ConfigSnapshot dataclass or equivalent — add:
quote_watchlist: QuoteWatchlistFile

# In ConfigLoader.load():
qw_path = self._dir / "quote_watchlist.yml"
quote_watchlist = (
    QuoteWatchlistFile.model_validate(yaml.safe_load(qw_path.read_text()))
    if qw_path.exists()
    else QuoteWatchlistFile()
)
```

- [ ] **Step 5: Create sample yaml**

```yaml
# config/quote_watchlist.yml
cn:
  - ticker: "600519"
    name: 贵州茅台
    market: SH
  - ticker: "300750"
    name: 宁德时代
    market: SZ
  - ticker: "002594"
    name: 比亚迪
    market: SZ
us: []
market_scans:
  cn:
    top_gainers_n: 50
    top_losers_n: 50
    top_volume_ratio_n: 50
    push_top_n: 5
    only_when_score_above: 8.0
```

- [ ] **Step 6: Tests**

```bash
uv run pytest tests/unit/config/test_quote_watchlist_schema.py -v
uv run pytest -q  # full suite to confirm news_pipeline tests still pass
```

- [ ] **Step 7: Commit**

```bash
git add src/news_pipeline/config/schema.py src/news_pipeline/config/loader.py config/quote_watchlist.yml tests/unit/config/test_quote_watchlist_schema.py
git commit -m "feat(v0.4.0): QuoteWatchlistFile schema + sample config"
```

---

### Task 2.6: SQLite models + alembic migration for quotes.db

**Files:**
- Create: `src/quote_watcher/storage/db.py` (Database wrapper)
- Create: `src/quote_watcher/storage/models.py`
- Create: `src/quote_watcher/storage/migrations/env.py` + `versions/0001_initial.py`
- Create: `scripts/alembic_quotes.ini` (separate from news alembic)
- Create: `tests/unit/quote_watcher/storage/test_models.py`

- [ ] **Step 1: Failing model test**

```python
# tests/unit/quote_watcher/storage/test_models.py
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import select

from quote_watcher.storage.models import Base, QuoteBar1min, AlertState


@pytest.mark.asyncio
async def test_create_and_query():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSession(engine) as sess:
        sess.add(AlertState(rule_id="rule_a", ticker="600519", last_triggered_at=12345, last_value=1.0, trigger_count_today=1))
        await sess.commit()

        result = await sess.execute(select(AlertState).where(AlertState.rule_id == "rule_a"))
        row = result.scalar_one()
        assert row.ticker == "600519"
        assert row.trigger_count_today == 1
```

- [ ] **Step 2: Run, expect fail**

```bash
uv run pytest tests/unit/quote_watcher/storage/test_models.py -v
```

- [ ] **Step 3: Implement models**

```python
# src/quote_watcher/storage/models.py
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class QuoteBar1min(Base):
    __tablename__ = "quote_bars_1min"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(10), nullable=False)
    bar_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    __table_args__ = (
        UniqueConstraint("ticker", "bar_start", name="uq_bar1min_ticker_start"),
        Index("idx_bar1min_ticker_ts", "ticker", "bar_start"),
    )


class QuoteBarDaily(Base):
    __tablename__ = "quote_bars_daily"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(10), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    prev_close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    __table_args__ = (
        UniqueConstraint("ticker", "trade_date", name="uq_bardaily_ticker_date"),
    )


class AlertState(Base):
    __tablename__ = "alert_state"
    rule_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    ticker: Mapped[str] = mapped_column(String(10), primary_key=True)
    last_triggered_at: Mapped[int] = mapped_column(BigInteger, nullable=False)  # unix sec
    last_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    trigger_count_today: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    __table_args__ = (
        Index("idx_alert_state_ticker", "ticker"),
    )


class AlertHistory(Base):
    __tablename__ = "alert_history"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_id: Mapped[str] = mapped_column(String(64), nullable=False)
    ticker: Mapped[str] = mapped_column(String(10), nullable=False)
    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    pushed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    push_message_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
```

- [ ] **Step 4: Implement Database wrapper**

Look at `src/news_pipeline/storage/db.py` and clone the pattern:

```python
# src/quote_watcher/storage/db.py
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from quote_watcher.storage.models import Base


class QuoteDatabase:
    def __init__(self, url: str) -> None:
        self._engine: AsyncEngine = create_async_engine(url, echo=False, future=True)
        self._sessionmaker = async_sessionmaker(self._engine, expire_on_commit=False)

    async def initialize(self) -> None:
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    def session(self) -> AsyncSession:
        return self._sessionmaker()

    async def close(self) -> None:
        await self._engine.dispose()
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/unit/quote_watcher/storage/test_models.py -v
```

- [ ] **Step 6: Skip alembic for now (use `Base.metadata.create_all()` at startup)**

Alembic for quote_watcher can be added in Plan B (S7 docs). For S1 we'll just call `db.initialize()` at startup which creates all tables.

- [ ] **Step 7: Commit**

```bash
git add src/quote_watcher/storage tests/unit/quote_watcher/storage/test_models.py
git commit -m "feat(v0.4.0): QuoteDatabase + 4 SQLAlchemy models for quotes.db"
```

---

### Task 2.7: Scheduler poll job + main entry

**Files:**
- Create: `src/quote_watcher/scheduler/jobs.py`
- Create: `src/quote_watcher/main.py`
- Modify: `docker-compose.yml` (add quote_watcher service)
- Create: `tests/unit/quote_watcher/scheduler/test_poll_quotes.py`
- Create: `tests/unit/quote_watcher/scheduler/__init__.py`

This task wires the smallest end-to-end loop: scheduler tick → SinaFeed → TickRing. No alerts yet (those come in Phase 3).

- [ ] **Step 1: Failing test for poll_quotes**

```python
# tests/unit/quote_watcher/scheduler/test_poll_quotes.py
from datetime import datetime
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest

from quote_watcher.feeds.base import QuoteSnapshot
from quote_watcher.feeds.calendar import MarketCalendar
from quote_watcher.scheduler.jobs import poll_quotes
from quote_watcher.store.tick import TickRing

BJ = ZoneInfo("Asia/Shanghai")


@pytest.mark.asyncio
async def test_poll_quotes_skips_when_market_closed():
    feed = AsyncMock()
    cal = MarketCalendar()
    ring = TickRing()
    # Saturday — closed
    closed_dt = datetime(2026, 5, 9, 10, 0, tzinfo=BJ)
    n = await poll_quotes(
        feed=feed, calendar=cal, ring=ring,
        tickers=[("SH", "600519")],
        now=closed_dt,
    )
    assert n == 0
    feed.fetch.assert_not_called()


@pytest.mark.asyncio
async def test_poll_quotes_appends_to_ring():
    snap = QuoteSnapshot(
        ticker="600519", market="SH", name="X",
        ts=datetime(2026, 5, 8, 10, 0, tzinfo=BJ),
        price=1789.5, open=1820, high=1825, low=1788, prev_close=1815.5,
        volume=100, amount=1.0, bid1=1789.5, ask1=1789.6,
    )
    feed = AsyncMock()
    feed.fetch.return_value = [snap]
    cal = MarketCalendar()
    ring = TickRing()

    open_dt = datetime(2026, 5, 8, 10, 0, tzinfo=BJ)  # Friday morning
    n = await poll_quotes(
        feed=feed, calendar=cal, ring=ring,
        tickers=[("SH", "600519")],
        now=open_dt,
    )
    assert n == 1
    assert ring.latest("600519").price == 1789.5
    feed.fetch.assert_awaited_once_with([("SH", "600519")])
```

- [ ] **Step 2: Run, expect fail**

```bash
uv run pytest tests/unit/quote_watcher/scheduler/test_poll_quotes.py -v
```

- [ ] **Step 3: Implement poll_quotes**

```python
# src/quote_watcher/scheduler/jobs.py
"""Quote watcher scheduler jobs."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from quote_watcher.feeds.base import QuoteFeed
from quote_watcher.feeds.calendar import MarketCalendar
from quote_watcher.store.tick import TickRing
from shared.observability.log import get_logger

BJ = ZoneInfo("Asia/Shanghai")
log = get_logger(__name__)


async def poll_quotes(
    *,
    feed: QuoteFeed,
    calendar: MarketCalendar,
    ring: TickRing,
    tickers: list[tuple[str, str]],
    now: datetime | None = None,
) -> int:
    now = now or datetime.now(BJ)
    if not calendar.is_open(now):
        return 0
    snaps = await feed.fetch(tickers)
    for s in snaps:
        ring.append(s)
    if snaps:
        log.info("poll_quotes_ok", count=len(snaps))
    return len(snaps)
```

- [ ] **Step 4: Run tests, expect pass**

```bash
uv run pytest tests/unit/quote_watcher/scheduler/test_poll_quotes.py -v
```

- [ ] **Step 5: Implement main.py (skeleton — will grow in Phase 3)**

```python
# src/quote_watcher/main.py
"""Quote watcher entry point."""
from __future__ import annotations

import asyncio
import os
import signal
from pathlib import Path

from news_pipeline.config.loader import ConfigLoader
from quote_watcher.feeds.calendar import MarketCalendar
from quote_watcher.feeds.sina import SinaFeed
from quote_watcher.scheduler.jobs import poll_quotes
from quote_watcher.storage.db import QuoteDatabase
from quote_watcher.store.tick import TickRing
from shared.observability.log import configure_logging, get_logger

log = get_logger(__name__)


async def _amain() -> None:
    cfg_dir = Path(os.environ.get("QUOTE_WATCHER_CONFIG_DIR", "config"))
    db_path = os.environ.get("QUOTE_WATCHER_DB", "data/quotes.db")
    poll_interval_sec = float(os.environ.get("QUOTE_POLL_INTERVAL_SEC", "5"))

    configure_logging(level=os.environ.get("LOG_LEVEL", "INFO"), json_output=True)

    loader = ConfigLoader(cfg_dir)
    snap = loader.load()

    db = QuoteDatabase(f"sqlite+aiosqlite:///{db_path}")
    await db.initialize()

    feed = SinaFeed()
    calendar = MarketCalendar()
    ring = TickRing(max_per_ticker=1000)

    tickers: list[tuple[str, str]] = [
        (e.market, e.ticker) for e in snap.quote_watchlist.cn
    ]
    log.info("quote_watcher_starting", tickers=len(tickers), poll_sec=poll_interval_sec)

    stop = asyncio.Event()

    def _on_signal(*_: object) -> None:
        log.info("shutdown_signal")
        stop.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, _on_signal)

    while not stop.is_set():
        try:
            await poll_quotes(feed=feed, calendar=calendar, ring=ring, tickers=tickers)
        except Exception as e:
            log.warning("poll_iteration_failed", error=str(e))
        try:
            await asyncio.wait_for(stop.wait(), timeout=poll_interval_sec)
        except asyncio.TimeoutError:
            pass

    await db.close()
    log.info("quote_watcher_stopped")


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Add docker-compose service**

Edit `docker-compose.yml` (read it first to see existing structure):

```bash
cat docker-compose.yml
```

Then duplicate the news_pipeline service block, renaming for quote_watcher. The exact diff depends on the existing file — typically:

```yaml
  quote_watcher:
    build:
      context: .
      dockerfile: Dockerfile
    image: news-pipeline:latest      # reuse the same image
    command: uv run python -m quote_watcher.main
    restart: unless-stopped
    volumes:
      - ./config:/app/config:ro
      - ./data:/app/data
      - ./logs:/app/logs
    environment:
      QUOTE_WATCHER_DB: /app/data/quotes.db
      LOG_LEVEL: INFO
```

- [ ] **Step 7: Smoke test main.py — dry run with all stocks suspended**

```bash
QUOTE_POLL_INTERVAL_SEC=3 timeout 8 uv run python -m quote_watcher.main 2>&1 | grep -E "(quote_watcher_starting|poll_quotes_ok|poll_iteration_failed|quote_watcher_stopped)"
```
Expected: at least `quote_watcher_starting` and `quote_watcher_stopped`. `poll_quotes_ok` only appears if market is open at runtime.

- [ ] **Step 8: Commit**

```bash
git add src/quote_watcher/scheduler src/quote_watcher/main.py tests/unit/quote_watcher/scheduler docker-compose.yml
git commit -m "feat(v0.4.0): quote_watcher scheduler + main entry, polls Sina to TickRing"
```

---

## Phase 3 (S2) — Threshold alerts end-to-end

### Task 3.1: AlertRule schema + sample alerts.yml

**Files:**
- Create: `src/quote_watcher/alerts/rule.py`
- Modify: `src/news_pipeline/config/schema.py` (add AlertsFile)
- Modify: `src/news_pipeline/config/loader.py` (load alerts.yml)
- Create: `config/alerts.yml`
- Create: `tests/unit/quote_watcher/alerts/test_rule_schema.py`

- [ ] **Step 1: Failing test**

```python
# tests/unit/quote_watcher/alerts/test_rule_schema.py
import pytest
from pydantic import ValidationError

from quote_watcher.alerts.rule import AlertRule, AlertKind, AlertsFile


def test_threshold_minimal():
    r = AlertRule(
        id="t1", kind=AlertKind.THRESHOLD,
        ticker="600519", expr="pct_change_intraday <= -3.0",
    )
    assert r.cooldown_min == 30
    assert r.severity == "warning"


def test_threshold_requires_ticker():
    with pytest.raises(ValidationError, match="ticker"):
        AlertRule(id="t1", kind=AlertKind.THRESHOLD, expr="x > 0")


def test_event_sector_target():
    r = AlertRule(
        id="e1", kind=AlertKind.EVENT,
        target_kind="sector", sector="半导体",
        expr="sector_pct_change >= 3.0",
    )
    assert r.sector == "半导体"


def test_composite_requires_holding_or_portfolio():
    with pytest.raises(ValidationError, match="holding|portfolio"):
        AlertRule(id="c1", kind=AlertKind.COMPOSITE, expr="x > 0")


def test_alerts_file_unique_ids():
    with pytest.raises(ValidationError, match="duplicate"):
        AlertsFile(alerts=[
            AlertRule(id="dup", kind=AlertKind.THRESHOLD, ticker="A", expr="1"),
            AlertRule(id="dup", kind=AlertKind.THRESHOLD, ticker="B", expr="1"),
        ])


def test_alerts_file_invalid_expr_rejected():
    with pytest.raises(ValidationError, match="syntax"):
        AlertsFile(alerts=[
            AlertRule(id="bad", kind=AlertKind.THRESHOLD, ticker="A", expr="if if"),
        ])
```

- [ ] **Step 2: Run, expect fail**

```bash
uv run pytest tests/unit/quote_watcher/alerts/test_rule_schema.py -v
```

- [ ] **Step 3: Implement rule.py**

```python
# src/quote_watcher/alerts/rule.py
from __future__ import annotations

import asteval
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AlertKind(StrEnum):
    THRESHOLD = "threshold"
    INDICATOR = "indicator"
    EVENT = "event"
    COMPOSITE = "composite"


class _Base(BaseModel):
    model_config = ConfigDict(use_enum_values=False, extra="forbid")


class AlertRule(_Base):
    id: str
    kind: AlertKind
    expr: str
    cooldown_min: int = 30
    severity: Literal["info", "warning", "critical"] = "warning"

    ticker: str | None = None
    name: str | None = None
    target_kind: Literal["ticker", "sector"] = "ticker"
    sector: str | None = None
    holding: str | None = None
    portfolio: bool = False
    needs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_target_consistency(self) -> "AlertRule":
        if self.kind in (AlertKind.THRESHOLD, AlertKind.INDICATOR):
            if self.ticker is None:
                raise ValueError(f"rule {self.id}: kind={self.kind} requires ticker")
        elif self.kind == AlertKind.EVENT:
            if self.target_kind == "ticker" and self.ticker is None:
                raise ValueError(f"rule {self.id}: event with target_kind=ticker requires ticker")
            if self.target_kind == "sector" and not self.sector:
                raise ValueError(f"rule {self.id}: event with target_kind=sector requires sector")
        elif self.kind == AlertKind.COMPOSITE:
            if not self.holding and not self.portfolio:
                raise ValueError(f"rule {self.id}: composite requires holding or portfolio=true")
        return self


class AlertsFile(_Base):
    alerts: list[AlertRule] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_ids(self) -> "AlertsFile":
        seen: set[str] = set()
        for r in self.alerts:
            if r.id in seen:
                raise ValueError(f"duplicate alert id: {r.id}")
            seen.add(r.id)
        return self

    @model_validator(mode="after")
    def expr_syntax_ok(self) -> "AlertsFile":
        for r in self.alerts:
            interp = asteval.Interpreter(no_print=True, no_assert=True)
            try:
                interp.parse(r.expr)
            except SyntaxError as e:
                raise ValueError(f"rule {r.id}: expr syntax error: {e}") from e
            if interp.error:
                msgs = "; ".join(str(e.get_error()) for e in interp.error)
                raise ValueError(f"rule {r.id}: expr syntax error: {msgs}")
        return self
```

- [ ] **Step 4: Add to news_pipeline schema + loader**

In `src/news_pipeline/config/schema.py` add:
```python
from quote_watcher.alerts.rule import AlertsFile  # noqa: E402
```
(or copy AlertsFile here — either is fine; importing is cleaner.)

Add to `ConfigSnapshot` / `ConfigLoader.load()` in `src/news_pipeline/config/loader.py`:
```python
alerts_path = self._dir / "alerts.yml"
alerts = (
    AlertsFile.model_validate(yaml.safe_load(alerts_path.read_text()))
    if alerts_path.exists()
    else AlertsFile()
)
# ... attach to snap.alerts
```

- [ ] **Step 5: Sample alerts.yml**

```yaml
# config/alerts.yml
alerts:
  - id: maotai_drop_3pct
    kind: threshold
    ticker: "600519"
    name: 贵州茅台
    expr: "pct_change_intraday <= -3.0"
    cooldown_min: 30
    severity: warning

  - id: catl_volume_spike
    kind: threshold
    ticker: "300750"
    name: 宁德时代
    expr: "volume_ratio >= 2.0"
    cooldown_min: 60
```

- [ ] **Step 6: Tests**

```bash
uv run pytest tests/unit/quote_watcher/alerts/test_rule_schema.py -v
uv run pytest -q
```

- [ ] **Step 7: Commit**

```bash
git add src/quote_watcher/alerts/rule.py src/news_pipeline/config/schema.py src/news_pipeline/config/loader.py config/alerts.yml tests/unit/quote_watcher/alerts/test_rule_schema.py
git commit -m "feat(v0.4.0): AlertRule + AlertsFile schema with asteval syntax check"
```

---

### Task 3.2: Alert context builder

**Files:**
- Create: `src/quote_watcher/alerts/verdict.py`
- Create: `src/quote_watcher/alerts/context.py`
- Create: `tests/unit/quote_watcher/alerts/test_context.py`

- [ ] **Step 1: Failing test**

```python
# tests/unit/quote_watcher/alerts/test_context.py
from datetime import datetime
from zoneinfo import ZoneInfo

from quote_watcher.alerts.context import build_threshold_context
from quote_watcher.feeds.base import QuoteSnapshot

BJ = ZoneInfo("Asia/Shanghai")


def make_snap(price: float, prev_close: float, volume: int = 100) -> QuoteSnapshot:
    return QuoteSnapshot(
        ticker="600519", market="SH", name="X",
        ts=datetime(2026, 5, 8, 10, 0, tzinfo=BJ),
        price=price, open=prev_close, high=price, low=prev_close,
        prev_close=prev_close,
        volume=volume, amount=1.0, bid1=price, ask1=price + 0.01,
    )


def test_basic_threshold_ctx():
    snap = make_snap(price=1789.5, prev_close=1845.36)
    ctx = build_threshold_context(snap, volume_avg5d=50)
    assert ctx["price_now"] == 1789.5
    assert ctx["prev_close"] == 1845.36
    assert abs(ctx["pct_change_intraday"] - ((1789.5 - 1845.36) / 1845.36 * 100)) < 1e-6
    assert ctx["volume_today"] == 100
    assert ctx["volume_avg5d"] == 50
    assert ctx["volume_ratio"] == 2.0
    assert ctx["now_hhmm"] == 1000


def test_zero_avg_volume_ratio_zero():
    snap = make_snap(price=10, prev_close=10, volume=100)
    ctx = build_threshold_context(snap, volume_avg5d=0)
    assert ctx["volume_ratio"] == 0.0
```

- [ ] **Step 2: Run, expect fail**

- [ ] **Step 3: Implement**

```python
# src/quote_watcher/alerts/verdict.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from quote_watcher.alerts.rule import AlertRule
from quote_watcher.feeds.base import QuoteSnapshot


@dataclass(frozen=True)
class AlertVerdict:
    rule: AlertRule
    snapshot: QuoteSnapshot
    ctx_dump: dict[str, Any] = field(default_factory=dict)
```

```python
# src/quote_watcher/alerts/context.py
"""Context builder for AlertEngine — produces the variable map injected into asteval."""
from __future__ import annotations

from typing import Any

from quote_watcher.feeds.base import QuoteSnapshot


def build_threshold_context(
    snap: QuoteSnapshot,
    *,
    volume_avg5d: float = 0.0,
    volume_avg20d: float = 0.0,
    price_high_today_yday: float = 0.0,
    price_low_today_yday: float = 0.0,
) -> dict[str, Any]:
    volume_ratio = (snap.volume / volume_avg5d) if volume_avg5d > 0 else 0.0
    is_limit_up = snap.ask1 == 0 and snap.bid1 > 0 and snap.price > snap.prev_close * 1.099
    is_limit_down = snap.bid1 == 0 and snap.ask1 > 0 and snap.price < snap.prev_close * 0.901
    bj = snap.ts
    return {
        "price_now": snap.price,
        "price_open": snap.open,
        "high_today": snap.high,
        "low_today": snap.low,
        "prev_close": snap.prev_close,
        "price_high_today_yday": price_high_today_yday,
        "price_low_today_yday": price_low_today_yday,
        "pct_change_intraday": snap.pct_change,
        "volume_today": snap.volume,
        "amount_today": snap.amount,
        "volume_avg5d": volume_avg5d,
        "volume_avg20d": volume_avg20d,
        "volume_ratio": volume_ratio,
        "bid1": snap.bid1,
        "ask1": snap.ask1,
        "is_limit_up": is_limit_up,
        "is_limit_down": is_limit_down,
        "now_hhmm": bj.hour * 100 + bj.minute,
    }
```

- [ ] **Step 4: Run, expect pass**

```bash
uv run pytest tests/unit/quote_watcher/alerts/test_context.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/quote_watcher/alerts/verdict.py src/quote_watcher/alerts/context.py tests/unit/quote_watcher/alerts/test_context.py
git commit -m "feat(v0.4.0): AlertVerdict + threshold context builder"
```

---

### Task 3.3: StateTracker (cooldown state machine)

**Files:**
- Create: `src/quote_watcher/state/tracker.py`
- Create: `src/quote_watcher/storage/dao/alert_state.py`
- Create: `tests/unit/quote_watcher/state/test_tracker.py`

- [ ] **Step 1: Failing test**

```python
# tests/unit/quote_watcher/state/test_tracker.py
import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from quote_watcher.state.tracker import StateTracker
from quote_watcher.storage.dao.alert_state import AlertStateDAO
from quote_watcher.storage.db import QuoteDatabase
from quote_watcher.storage.models import Base


@pytest.fixture
async def db() -> QuoteDatabase:
    db = QuoteDatabase("sqlite+aiosqlite:///:memory:")
    await db.initialize()
    return db


@pytest.mark.asyncio
async def test_first_trigger_not_in_cooldown(db: QuoteDatabase):
    tracker = StateTracker(dao=AlertStateDAO(db), now_fn=lambda: 1000)
    assert await tracker.is_in_cooldown("rule_a", "600519", cooldown_min=30) is False


@pytest.mark.asyncio
async def test_after_mark_triggered_in_cooldown(db: QuoteDatabase):
    tracker = StateTracker(dao=AlertStateDAO(db), now_fn=lambda: 1000)
    await tracker.mark_triggered("rule_a", "600519", value=1.0)
    assert await tracker.is_in_cooldown("rule_a", "600519", cooldown_min=30) is True


@pytest.mark.asyncio
async def test_cooldown_expires(db: QuoteDatabase):
    times = iter([1000, 1000, 3000])  # mark @ 1000, check @ 3000 (33 min later)
    tracker = StateTracker(dao=AlertStateDAO(db), now_fn=lambda: next(times))
    await tracker.mark_triggered("rule_a", "600519", value=1.0)
    assert await tracker.is_in_cooldown("rule_a", "600519", cooldown_min=30) is False


@pytest.mark.asyncio
async def test_bump_count_increments(db: QuoteDatabase):
    tracker = StateTracker(dao=AlertStateDAO(db), now_fn=lambda: 1000)
    await tracker.mark_triggered("rule_a", "600519", value=1.0)
    await tracker.bump_count("rule_a", "600519")
    state = await tracker._dao.get("rule_a", "600519")
    assert state.trigger_count_today == 2
```

- [ ] **Step 2: Run, expect fail**

```bash
uv run pytest tests/unit/quote_watcher/state/test_tracker.py -v
```

- [ ] **Step 3: Implement DAO**

```python
# src/quote_watcher/storage/dao/alert_state.py
from __future__ import annotations

from sqlalchemy import select

from quote_watcher.storage.db import QuoteDatabase
from quote_watcher.storage.models import AlertState


class AlertStateDAO:
    def __init__(self, db: QuoteDatabase) -> None:
        self._db = db

    async def get(self, rule_id: str, ticker: str) -> AlertState | None:
        async with self._db.session() as sess:
            result = await sess.execute(
                select(AlertState).where(
                    AlertState.rule_id == rule_id,
                    AlertState.ticker == ticker,
                )
            )
            return result.scalar_one_or_none()

    async def upsert(
        self, *, rule_id: str, ticker: str, last_triggered_at: int, last_value: float | None
    ) -> None:
        async with self._db.session() as sess:
            existing = (
                await sess.execute(
                    select(AlertState).where(
                        AlertState.rule_id == rule_id,
                        AlertState.ticker == ticker,
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                sess.add(AlertState(
                    rule_id=rule_id, ticker=ticker,
                    last_triggered_at=last_triggered_at,
                    last_value=last_value,
                    trigger_count_today=1,
                ))
            else:
                existing.last_triggered_at = last_triggered_at
                existing.last_value = last_value
                existing.trigger_count_today += 1
            await sess.commit()

    async def bump(self, *, rule_id: str, ticker: str) -> None:
        async with self._db.session() as sess:
            existing = (
                await sess.execute(
                    select(AlertState).where(
                        AlertState.rule_id == rule_id,
                        AlertState.ticker == ticker,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                existing.trigger_count_today += 1
                await sess.commit()
```

- [ ] **Step 4: Implement StateTracker**

```python
# src/quote_watcher/state/tracker.py
from __future__ import annotations

import time
from collections.abc import Callable

from quote_watcher.storage.dao.alert_state import AlertStateDAO


class StateTracker:
    def __init__(self, *, dao: AlertStateDAO, now_fn: Callable[[], int] | None = None) -> None:
        self._dao = dao
        self._now = now_fn or (lambda: int(time.time()))

    async def is_in_cooldown(self, rule_id: str, ticker: str, cooldown_min: int) -> bool:
        state = await self._dao.get(rule_id, ticker)
        if state is None:
            return False
        return (self._now() - state.last_triggered_at) < cooldown_min * 60

    async def mark_triggered(self, rule_id: str, ticker: str, *, value: float | None) -> None:
        await self._dao.upsert(
            rule_id=rule_id, ticker=ticker,
            last_triggered_at=self._now(), last_value=value,
        )

    async def bump_count(self, rule_id: str, ticker: str) -> None:
        await self._dao.bump(rule_id=rule_id, ticker=ticker)
```

- [ ] **Step 5: Run tests, expect pass**

```bash
uv run pytest tests/unit/quote_watcher/state/test_tracker.py -v
```

- [ ] **Step 6: Commit**

```bash
git add src/quote_watcher/state src/quote_watcher/storage/dao tests/unit/quote_watcher/state
git commit -m "feat(v0.4.0): AlertStateDAO + StateTracker cooldown state machine"
```

---

### Task 3.4: AlertEngine (threshold-only)

**Files:**
- Create: `src/quote_watcher/alerts/engine.py`
- Create: `tests/unit/quote_watcher/alerts/test_engine.py`

- [ ] **Step 1: Failing test**

```python
# tests/unit/quote_watcher/alerts/test_engine.py
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from quote_watcher.alerts.engine import AlertEngine
from quote_watcher.alerts.rule import AlertRule, AlertKind
from quote_watcher.feeds.base import QuoteSnapshot
from quote_watcher.state.tracker import StateTracker
from quote_watcher.storage.dao.alert_state import AlertStateDAO
from quote_watcher.storage.db import QuoteDatabase

BJ = ZoneInfo("Asia/Shanghai")


@pytest.fixture
async def engine_pieces():
    db = QuoteDatabase("sqlite+aiosqlite:///:memory:")
    await db.initialize()
    tracker = StateTracker(dao=AlertStateDAO(db), now_fn=lambda: 1000)
    return db, tracker


def make_snap(price: float, prev: float) -> QuoteSnapshot:
    return QuoteSnapshot(
        ticker="600519", market="SH", name="X",
        ts=datetime(2026, 5, 8, 10, 0, tzinfo=BJ),
        price=price, open=prev, high=max(price, prev), low=min(price, prev),
        prev_close=prev, volume=100, amount=1.0, bid1=price, ask1=price + 0.01,
    )


@pytest.mark.asyncio
async def test_threshold_triggers(engine_pieces):
    db, tracker = engine_pieces
    rule = AlertRule(id="r1", kind=AlertKind.THRESHOLD,
                     ticker="600519", expr="pct_change_intraday <= -3.0", cooldown_min=30)
    engine = AlertEngine(rules=[rule], tracker=tracker)
    snap = make_snap(price=96.5, prev=100.0)  # -3.5%
    verdicts = await engine.evaluate_for_snapshot(snap, volume_avg5d=50)
    assert len(verdicts) == 1
    assert verdicts[0].rule.id == "r1"


@pytest.mark.asyncio
async def test_threshold_does_not_trigger(engine_pieces):
    db, tracker = engine_pieces
    rule = AlertRule(id="r1", kind=AlertKind.THRESHOLD,
                     ticker="600519", expr="pct_change_intraday <= -3.0")
    engine = AlertEngine(rules=[rule], tracker=tracker)
    snap = make_snap(price=98.0, prev=100.0)  # only -2%
    verdicts = await engine.evaluate_for_snapshot(snap, volume_avg5d=50)
    assert verdicts == []


@pytest.mark.asyncio
async def test_cooldown_silences_repeat(engine_pieces):
    db, tracker = engine_pieces
    rule = AlertRule(id="r1", kind=AlertKind.THRESHOLD,
                     ticker="600519", expr="pct_change_intraday <= -3.0", cooldown_min=30)
    engine = AlertEngine(rules=[rule], tracker=tracker)
    snap = make_snap(price=96.5, prev=100.0)
    v1 = await engine.evaluate_for_snapshot(snap, volume_avg5d=50)
    v2 = await engine.evaluate_for_snapshot(snap, volume_avg5d=50)
    assert len(v1) == 1
    assert v2 == []  # second call within cooldown silenced


@pytest.mark.asyncio
async def test_target_filter(engine_pieces):
    db, tracker = engine_pieces
    rule = AlertRule(id="r1", kind=AlertKind.THRESHOLD,
                     ticker="000001", expr="pct_change_intraday <= -3.0")
    engine = AlertEngine(rules=[rule], tracker=tracker)
    snap = make_snap(price=96.5, prev=100.0)  # ticker=600519, not 000001
    verdicts = await engine.evaluate_for_snapshot(snap, volume_avg5d=50)
    assert verdicts == []
```

- [ ] **Step 2: Run, expect fail**

```bash
uv run pytest tests/unit/quote_watcher/alerts/test_engine.py -v
```

- [ ] **Step 3: Implement engine**

```python
# src/quote_watcher/alerts/engine.py
from __future__ import annotations

import asteval

from quote_watcher.alerts.context import build_threshold_context
from quote_watcher.alerts.rule import AlertKind, AlertRule
from quote_watcher.alerts.verdict import AlertVerdict
from quote_watcher.feeds.base import QuoteSnapshot
from quote_watcher.state.tracker import StateTracker
from shared.observability.log import get_logger

log = get_logger(__name__)


class AlertEngine:
    def __init__(self, *, rules: list[AlertRule], tracker: StateTracker) -> None:
        self._rules = rules
        self._tracker = tracker

    async def evaluate_for_snapshot(
        self,
        snap: QuoteSnapshot,
        *,
        volume_avg5d: float = 0.0,
        volume_avg20d: float = 0.0,
        price_high_today_yday: float = 0.0,
        price_low_today_yday: float = 0.0,
    ) -> list[AlertVerdict]:
        applicable = [
            r for r in self._rules
            if r.kind == AlertKind.THRESHOLD and r.ticker == snap.ticker
        ]
        if not applicable:
            return []
        ctx = build_threshold_context(
            snap,
            volume_avg5d=volume_avg5d,
            volume_avg20d=volume_avg20d,
            price_high_today_yday=price_high_today_yday,
            price_low_today_yday=price_low_today_yday,
        )
        out: list[AlertVerdict] = []
        for rule in applicable:
            interp = asteval.Interpreter(usersyms=ctx, no_print=True, no_assert=True)
            try:
                result = bool(interp(rule.expr))
            except Exception as e:
                log.warning("rule_eval_failed", rule=rule.id, error=str(e))
                continue
            if interp.error:
                log.warning("rule_eval_runtime_error", rule=rule.id,
                            errors=[str(e.get_error()) for e in interp.error])
                continue
            if not result:
                continue
            if await self._tracker.is_in_cooldown(rule.id, snap.ticker, rule.cooldown_min):
                await self._tracker.bump_count(rule.id, snap.ticker)
                continue
            await self._tracker.mark_triggered(
                rule.id, snap.ticker, value=ctx.get("price_now"),
            )
            out.append(AlertVerdict(rule=rule, snapshot=snap, ctx_dump=dict(ctx)))
        return out
```

- [ ] **Step 4: Run, expect pass**

```bash
uv run pytest tests/unit/quote_watcher/alerts/test_engine.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/quote_watcher/alerts/engine.py tests/unit/quote_watcher/alerts/test_engine.py
git commit -m "feat(v0.4.0): AlertEngine.evaluate_for_snapshot for threshold rules"
```

---

### Task 3.5: emit/message.py — AlertVerdict → CommonMessage

**Files:**
- Create: `src/quote_watcher/emit/message.py`
- Create: `tests/unit/quote_watcher/emit/test_message.py`

- [ ] **Step 1: Failing test**

```python
# tests/unit/quote_watcher/emit/test_message.py
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from quote_watcher.alerts.rule import AlertRule, AlertKind
from quote_watcher.alerts.verdict import AlertVerdict
from quote_watcher.emit.message import build_alert_message, build_burst_message
from quote_watcher.feeds.base import QuoteSnapshot

BJ = ZoneInfo("Asia/Shanghai")


def _v(rule_id: str, expr: str, ctx: dict) -> AlertVerdict:
    rule = AlertRule(id=rule_id, kind=AlertKind.THRESHOLD, ticker="600519", expr=expr)
    snap = QuoteSnapshot(
        ticker="600519", market="SH", name="贵州茅台",
        ts=datetime(2026, 5, 8, 14, 30, 25, tzinfo=BJ),
        price=1789.5, open=1820, high=1825, low=1788, prev_close=1845.36,
        volume=2823100, amount=5.04e9, bid1=1789.5, ask1=1789.51,
    )
    return AlertVerdict(rule=rule, snapshot=snap, ctx_dump=ctx)


def test_single_alert_message():
    v = _v("maotai_drop_3pct", "pct_change_intraday <= -3.0",
           {"price_now": 1789.5, "pct_change_intraday": -3.03, "volume_ratio": 2.1})
    msg = build_alert_message(v)
    assert msg.kind == "alert"
    assert "贵州茅台" in msg.title
    assert "600519" in msg.title
    assert "rules" not in [b.text for b in msg.badges]
    assert any(b.text == "alert" for b in msg.badges)


def test_burst_merge_combines_verdicts():
    v1 = _v("a", "x<-1", {"price_now": 1789.5})
    v2 = _v("b", "y>2", {"price_now": 1789.5})
    msg = build_burst_message([v1, v2])
    assert msg.kind == "alert_burst"
    assert "多规则触发" in msg.title or "(2)" in msg.title
    assert "(a)" in msg.summary
    assert "(b)" in msg.summary
```

- [ ] **Step 2: Run, expect fail**

- [ ] **Step 3: Implement message builder**

```python
# src/quote_watcher/emit/message.py
from __future__ import annotations

from quote_watcher.alerts.verdict import AlertVerdict
from shared.common.contracts import Badge, CommonMessage, Deeplink
from shared.common.enums import Market


def _deeplinks_for_ticker(ticker: str, market: str) -> list[Deeplink]:
    market_lc = "sh" if market == "SH" else "sz" if market == "SZ" else "bj"
    return [
        Deeplink(label="东财 K 线", url=f"https://quote.eastmoney.com/{market_lc}{ticker}.html"),
        Deeplink(label="雪球", url=f"https://xueqiu.com/S/{market}{ticker}"),
    ]


def build_alert_message(v: AlertVerdict) -> CommonMessage:
    snap = v.snapshot
    pct = v.ctx_dump.get("pct_change_intraday", snap.pct_change)
    vol_ratio = v.ctx_dump.get("volume_ratio")

    summary_lines = [
        f"⚡ 触发: {v.rule.id}（{v.rule.expr}）",
        f"当前价: {snap.price:.2f}  ({pct:+.2f}%)",
        f"今日量: {snap.volume / 10000:.1f}万手",
    ]
    if vol_ratio:
        summary_lines.append(f"量比: {vol_ratio:.2f}")
    summary_lines.append(f"⏱ {snap.ts.strftime('%H:%M:%S')}")

    badges = [
        Badge(text=f"#{snap.ticker}", color="blue"),
        Badge(text="alert", color="red" if pct < 0 else "green"),
    ]
    arrow = "🔻" if pct < 0 else "🚀" if pct > 0 else "⚡"

    return CommonMessage(
        title=f"{arrow} {snap.name} ({snap.ticker}) {v.rule.id}",
        summary="\n".join(summary_lines),
        source_label="quote_watcher",
        source_url=f"https://quote.eastmoney.com/{('sh' if snap.market == 'SH' else 'sz')}{snap.ticker}.html",
        badges=badges,
        deeplinks=_deeplinks_for_ticker(snap.ticker, snap.market),
        market=Market.CN,
        kind="alert",
    )


def build_burst_message(verdicts: list[AlertVerdict]) -> CommonMessage:
    assert verdicts, "verdicts must be non-empty"
    snap = verdicts[0].snapshot
    pct = snap.pct_change
    arrow = "🔻" if pct < 0 else "🚀" if pct > 0 else "⚡"

    lines = [f"✓ {v.rule.id}: {v.rule.expr}" for v in verdicts]
    lines.append(f"当前价: {snap.price:.2f}  ({pct:+.2f}%)")
    lines.append(f"⏱ {snap.ts.strftime('%H:%M:%S')}")

    badges = [
        Badge(text=f"#{snap.ticker}", color="blue"),
        Badge(text=f"多规则×{len(verdicts)}", color="yellow"),
        Badge(text="alert", color="red" if pct < 0 else "green"),
    ]
    return CommonMessage(
        title=f"{arrow} {snap.name} ({snap.ticker}) 多规则触发(×{len(verdicts)})",
        summary="\n".join(lines),
        source_label="quote_watcher",
        source_url=f"https://quote.eastmoney.com/{('sh' if snap.market == 'SH' else 'sz')}{snap.ticker}.html",
        badges=badges,
        deeplinks=_deeplinks_for_ticker(snap.ticker, snap.market),
        market=Market.CN,
        kind="alert_burst",
    )
```

- [ ] **Step 4: Run, expect pass**

```bash
uv run pytest tests/unit/quote_watcher/emit/test_message.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/quote_watcher/emit tests/unit/quote_watcher/emit
git commit -m "feat(v0.4.0): emit/message — single + burst alert CommonMessage builders"
```

---

### Task 3.6: Wire engine + emitter + push into scheduler tick + main

**Files:**
- Modify: `src/quote_watcher/scheduler/jobs.py` — add `evaluate_alerts(snaps, engine, emitter, dispatcher)` job
- Modify: `src/quote_watcher/main.py` — build engine, tracker, dispatcher; loop ticks both poll + evaluate
- Create: `tests/unit/quote_watcher/scheduler/test_evaluate_alerts.py`

- [ ] **Step 1: Failing test**

```python
# tests/unit/quote_watcher/scheduler/test_evaluate_alerts.py
from datetime import datetime
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest

from quote_watcher.alerts.engine import AlertEngine
from quote_watcher.alerts.rule import AlertRule, AlertKind
from quote_watcher.feeds.base import QuoteSnapshot
from quote_watcher.scheduler.jobs import evaluate_alerts
from quote_watcher.state.tracker import StateTracker
from quote_watcher.storage.dao.alert_state import AlertStateDAO
from quote_watcher.storage.db import QuoteDatabase

BJ = ZoneInfo("Asia/Shanghai")


@pytest.mark.asyncio
async def test_evaluate_alerts_dispatches_when_triggered():
    db = QuoteDatabase("sqlite+aiosqlite:///:memory:")
    await db.initialize()
    tracker = StateTracker(dao=AlertStateDAO(db), now_fn=lambda: 1000)
    rule = AlertRule(
        id="maotai_drop", kind=AlertKind.THRESHOLD,
        ticker="600519", expr="pct_change_intraday <= -3.0",
    )
    engine = AlertEngine(rules=[rule], tracker=tracker)
    dispatcher = AsyncMock()
    dispatcher.dispatch.return_value = {}

    snap = QuoteSnapshot(
        ticker="600519", market="SH", name="贵州茅台",
        ts=datetime(2026, 5, 8, 10, 0, tzinfo=BJ),
        price=96.5, open=100, high=100, low=95, prev_close=100,
        volume=1000, amount=1.0, bid1=96.5, ask1=96.51,
    )
    n = await evaluate_alerts(
        snaps=[snap], engine=engine, dispatcher=dispatcher,
        channels=["feishu_cn"],
    )
    assert n == 1
    dispatcher.dispatch.assert_awaited_once()
```

- [ ] **Step 2: Run, expect fail**

- [ ] **Step 3: Implement evaluate_alerts**

Add to `src/quote_watcher/scheduler/jobs.py`:

```python
from collections.abc import Sequence

from quote_watcher.alerts.engine import AlertEngine
from quote_watcher.alerts.verdict import AlertVerdict
from quote_watcher.emit.message import build_alert_message, build_burst_message
from shared.push.dispatcher import PusherDispatcher


async def evaluate_alerts(
    *,
    snaps: Sequence[QuoteSnapshot],
    engine: AlertEngine,
    dispatcher: PusherDispatcher,
    channels: list[str],
) -> int:
    pushed = 0
    for snap in snaps:
        verdicts = await engine.evaluate_for_snapshot(snap)
        if not verdicts:
            continue
        if len(verdicts) == 1:
            msg = build_alert_message(verdicts[0])
        else:
            msg = build_burst_message(list(verdicts))
        await dispatcher.dispatch(msg, channels=channels)
        pushed += 1
    return pushed
```

- [ ] **Step 4: Wire into main.py**

Edit `src/quote_watcher/main.py`. Add (after existing setup):

```python
from quote_watcher.alerts.engine import AlertEngine
from quote_watcher.scheduler.jobs import evaluate_alerts
from quote_watcher.state.tracker import StateTracker
from quote_watcher.storage.dao.alert_state import AlertStateDAO
from shared.push.dispatcher import PusherDispatcher
from shared.push.factory import build_pushers
```

In `_amain()` after the existing config + db setup, add:

```python
    pushers = build_pushers(snap.channels, snap.secrets)
    dispatcher = PusherDispatcher(pushers)
    cn_alert_channels = [
        c for c, ch in snap.channels.channels.items() if ch.market == "cn" and ch.enabled
    ]

    tracker = StateTracker(dao=AlertStateDAO(db))
    engine = AlertEngine(rules=snap.alerts.alerts, tracker=tracker)
```

Modify the polling loop body:

```python
    while not stop.is_set():
        try:
            snaps = await feed.fetch(tickers) if calendar.is_open(datetime.now(BJ)) else []
            for s in snaps:
                ring.append(s)
            if snaps:
                await evaluate_alerts(
                    snaps=snaps, engine=engine,
                    dispatcher=dispatcher, channels=cn_alert_channels,
                )
        except Exception as e:
            log.warning("tick_failed", error=str(e))
        try:
            await asyncio.wait_for(stop.wait(), timeout=poll_interval_sec)
        except asyncio.TimeoutError:
            pass
```

(Reorganize as needed — the goal is: poll → ring.append → evaluate_alerts → push. The earlier `poll_quotes` helper can be retained as it is and called instead of inlining; pick whichever reads cleaner.)

- [ ] **Step 5: Run scheduler tests + full suite**

```bash
uv run pytest tests/unit/quote_watcher/scheduler -v
uv run pytest -q
```

- [ ] **Step 6: Smoke test main with sample alerts.yml**

```bash
QUOTE_POLL_INTERVAL_SEC=3 timeout 10 uv run python -m quote_watcher.main 2>&1 | tail -20
```
Expected: starts up cleanly. Will not actually trigger anything outside trading hours.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat(v0.4.0): wire AlertEngine into scheduler + main, end-to-end threshold push"
```

---

### Task 3.7: Multi-rule same-ticker burst merge in scheduler

**Files:**
- Modify: `src/quote_watcher/alerts/engine.py` (add `evaluate_for_snapshots_grouped(snaps)` returning `dict[ticker, list[verdict]]`)
- Modify: `src/quote_watcher/scheduler/jobs.py` (use grouped output)
- Create: `tests/unit/quote_watcher/emit/test_burst_merge.py`

- [ ] **Step 1: Failing test for full-flow burst merge**

```python
# tests/unit/quote_watcher/emit/test_burst_merge.py
from datetime import datetime
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest

from quote_watcher.alerts.engine import AlertEngine
from quote_watcher.alerts.rule import AlertRule, AlertKind
from quote_watcher.feeds.base import QuoteSnapshot
from quote_watcher.scheduler.jobs import evaluate_alerts
from quote_watcher.state.tracker import StateTracker
from quote_watcher.storage.dao.alert_state import AlertStateDAO
from quote_watcher.storage.db import QuoteDatabase

BJ = ZoneInfo("Asia/Shanghai")


@pytest.mark.asyncio
async def test_two_rules_same_ticker_merged():
    db = QuoteDatabase("sqlite+aiosqlite:///:memory:")
    await db.initialize()
    tracker = StateTracker(dao=AlertStateDAO(db), now_fn=lambda: 1000)
    rules = [
        AlertRule(id="r_pct", kind=AlertKind.THRESHOLD,
                  ticker="600519", expr="pct_change_intraday <= -3.0"),
        AlertRule(id="r_vol", kind=AlertKind.THRESHOLD,
                  ticker="600519", expr="volume_today >= 500"),
    ]
    engine = AlertEngine(rules=rules, tracker=tracker)
    dispatcher = AsyncMock()
    dispatcher.dispatch.return_value = {}

    snap = QuoteSnapshot(
        ticker="600519", market="SH", name="贵州茅台",
        ts=datetime(2026, 5, 8, 10, 0, tzinfo=BJ),
        price=96.5, open=100, high=100, low=95, prev_close=100,
        volume=1000, amount=1.0, bid1=96.5, ask1=96.51,
    )
    await evaluate_alerts(
        snaps=[snap], engine=engine, dispatcher=dispatcher, channels=["feishu_cn"],
    )
    assert dispatcher.dispatch.await_count == 1   # one merged push, not two
    msg = dispatcher.dispatch.call_args.args[0]
    assert msg.kind == "alert_burst"
```

- [ ] **Step 2: Verify the existing `evaluate_for_snapshot` already returns multiple verdicts when both rules trigger**

The existing implementation returns `list[AlertVerdict]` — multi-rule case is already handled. The only additional logic needed is choosing between `build_alert_message` (single) vs `build_burst_message` (multi) — which `evaluate_alerts` already does in Task 3.6.

So this task is mostly verifying behavior. Run:
```bash
uv run pytest tests/unit/quote_watcher/emit/test_burst_merge.py -v
```
Expected: PASS.

- [ ] **Step 3: Commit (only the test)**

```bash
git add tests/unit/quote_watcher/emit/test_burst_merge.py
git commit -m "test(v0.4.0): verify same-ticker multi-rule burst merge produces alert_burst"
```

---

### Task 3.8: Integration test — fake Sina to mock Feishu (S2 acceptance)

**Files:**
- Create: `tests/integration/quote_watcher/test_e2e_threshold.py`

- [ ] **Step 1: Write the integration test**

```python
# tests/integration/quote_watcher/test_e2e_threshold.py
"""S2 acceptance: fake Sina HQ → AlertEngine → mock dispatcher.

Verifies the full chain works without hitting network or real Feishu.
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import httpx
import pytest
import respx

from quote_watcher.alerts.engine import AlertEngine
from quote_watcher.alerts.rule import AlertKind, AlertRule
from quote_watcher.feeds.calendar import MarketCalendar
from quote_watcher.feeds.sina import SinaFeed
from quote_watcher.scheduler.jobs import evaluate_alerts
from quote_watcher.state.tracker import StateTracker
from quote_watcher.storage.dao.alert_state import AlertStateDAO
from quote_watcher.storage.db import QuoteDatabase

BJ = ZoneInfo("Asia/Shanghai")

# Sina response with -3.07% drop: 96.93 vs prev_close 100.0
SINA_DROP = (
    'var hq_str_sh600519="贵州茅台,100.000,100.000,96.930,'
    '100.000,96.000,96.930,96.940,2823100,5043500000.00,'
    '200,96.930,500,96.880,300,96.830,400,96.780,500,96.730,'
    '100,96.940,200,96.950,300,96.960,400,96.970,500,96.980,'
    '2026-05-08,10:00:25,00";\n'
)


@pytest.mark.asyncio
@respx.mock
async def test_e2e_threshold_drop_3pct_pushes():
    respx.get("https://hq.sinajs.cn/list=sh600519").mock(
        return_value=httpx.Response(200, content=SINA_DROP.encode("gbk"))
    )

    feed = SinaFeed()
    calendar = MarketCalendar()

    db = QuoteDatabase("sqlite+aiosqlite:///:memory:")
    await db.initialize()
    tracker = StateTracker(dao=AlertStateDAO(db), now_fn=lambda: 1000)
    rule = AlertRule(
        id="maotai_drop_3pct", kind=AlertKind.THRESHOLD,
        ticker="600519", name="贵州茅台",
        expr="pct_change_intraday <= -3.0", cooldown_min=30,
    )
    engine = AlertEngine(rules=[rule], tracker=tracker)
    dispatcher = AsyncMock()
    dispatcher.dispatch.return_value = {"feishu_cn": "ok"}

    # simulate one tick at trading-hours time
    open_dt = datetime(2026, 5, 8, 10, 0, tzinfo=BJ)
    assert calendar.is_open(open_dt)

    snaps = await feed.fetch([("SH", "600519")])
    assert len(snaps) == 1
    pushed = await evaluate_alerts(
        snaps=snaps, engine=engine, dispatcher=dispatcher, channels=["feishu_cn"],
    )
    assert pushed == 1
    msg = dispatcher.dispatch.call_args.args[0]
    assert msg.kind == "alert"
    assert "贵州茅台" in msg.title
    assert "600519" in msg.title


@pytest.mark.asyncio
@respx.mock
async def test_e2e_no_trigger_when_drop_under_threshold():
    """1.5% drop should not trigger 3% rule."""
    no_drop = SINA_DROP.replace("96.930", "98.500")  # only -1.5%
    respx.get("https://hq.sinajs.cn/list=sh600519").mock(
        return_value=httpx.Response(200, content=no_drop.encode("gbk"))
    )

    db = QuoteDatabase("sqlite+aiosqlite:///:memory:")
    await db.initialize()
    tracker = StateTracker(dao=AlertStateDAO(db), now_fn=lambda: 1000)
    engine = AlertEngine(
        rules=[AlertRule(id="r1", kind=AlertKind.THRESHOLD,
                         ticker="600519", expr="pct_change_intraday <= -3.0")],
        tracker=tracker,
    )
    dispatcher = AsyncMock()
    feed = SinaFeed()
    snaps = await feed.fetch([("SH", "600519")])
    pushed = await evaluate_alerts(
        snaps=snaps, engine=engine, dispatcher=dispatcher, channels=["feishu_cn"],
    )
    assert pushed == 0
    dispatcher.dispatch.assert_not_called()
```

- [ ] **Step 2: Run integration tests**

```bash
uv run pytest tests/integration/quote_watcher/test_e2e_threshold.py -v
```
Expected: 2 PASS.

- [ ] **Step 3: Commit + tag S2 done**

```bash
git add tests/integration/quote_watcher/test_e2e_threshold.py
git commit -m "test(v0.4.0): S2 e2e — fake Sina drop triggers alert + no-trigger case"
git tag s2-complete
```

---

## Phase 4 (S3) — Composite + holdings + portfolio rules

### Task 4.1: HoldingsFile schema + sample yaml

**Files:**
- Modify: `src/news_pipeline/config/schema.py` (add HoldingsFile)
- Modify: `src/news_pipeline/config/loader.py` (load holdings.yml)
- Create: `config/holdings.yml`
- Create: `tests/unit/config/test_holdings_schema.py`

- [ ] **Step 1: Failing test**

```python
# tests/unit/config/test_holdings_schema.py
import pytest
from pydantic import ValidationError

from news_pipeline.config.schema import HoldingEntry, HoldingsFile, PortfolioCfg


def test_minimal_holdings():
    h = HoldingsFile(holdings=[
        HoldingEntry(ticker="600519", qty=100, cost_per_share=1850.0),
    ])
    assert h.holdings[0].ticker == "600519"
    assert h.portfolio.base_currency == "CNY"


def test_duplicate_holding_rejected():
    with pytest.raises(ValidationError, match="duplicate"):
        HoldingsFile(holdings=[
            HoldingEntry(ticker="600519", qty=100, cost_per_share=1850.0),
            HoldingEntry(ticker="600519", qty=200, cost_per_share=1900.0),
        ])


def test_negative_qty_rejected():
    with pytest.raises(ValidationError):
        HoldingEntry(ticker="600519", qty=-10, cost_per_share=1850.0)
```

- [ ] **Step 2: Run, expect fail**

- [ ] **Step 3: Add schemas**

In `src/news_pipeline/config/schema.py` append:

```python
class HoldingEntry(_Base):
    ticker: str
    name: str | None = None
    qty: int = Field(gt=0)
    cost_per_share: float = Field(gt=0)


class PortfolioCfg(_Base):
    total_capital: float | None = None
    base_currency: str = "CNY"


class HoldingsFile(_Base):
    holdings: list[HoldingEntry] = Field(default_factory=list)
    portfolio: PortfolioCfg = Field(default_factory=PortfolioCfg)

    @model_validator(mode="after")
    def unique_holdings(self) -> "HoldingsFile":
        seen: set[str] = set()
        for h in self.holdings:
            if h.ticker in seen:
                raise ValueError(f"duplicate holding: {h.ticker}")
            seen.add(h.ticker)
        return self
```

- [ ] **Step 4: Loader integration**

In `src/news_pipeline/config/loader.py`, mirror the alerts.yml loader:
```python
holdings_path = self._dir / "holdings.yml"
holdings = (
    HoldingsFile.model_validate(yaml.safe_load(holdings_path.read_text()))
    if holdings_path.exists()
    else HoldingsFile()
)
# attach to ConfigSnapshot.holdings
```

- [ ] **Step 5: Sample config**

```yaml
# config/holdings.yml
holdings:
  - ticker: "600519"
    name: 贵州茅台
    qty: 100
    cost_per_share: 1850.0
  - ticker: "300750"
    name: 宁德时代
    qty: 200
    cost_per_share: 220.0

portfolio:
  total_capital: 200000
  base_currency: CNY
```

- [ ] **Step 6: Tests**

```bash
uv run pytest tests/unit/config/test_holdings_schema.py -v
uv run pytest -q
```

- [ ] **Step 7: Commit**

```bash
git add src/news_pipeline/config/schema.py src/news_pipeline/config/loader.py config/holdings.yml tests/unit/config/test_holdings_schema.py
git commit -m "feat(v0.4.0): HoldingsFile schema + sample holdings.yml"
```

---

### Task 4.2: Composite rule context (holdings + portfolio)

**Files:**
- Modify: `src/quote_watcher/alerts/context.py` (add `build_composite_context`)
- Create: `tests/unit/quote_watcher/alerts/test_composite_context.py`

- [ ] **Step 1: Failing test**

```python
# tests/unit/quote_watcher/alerts/test_composite_context.py
from datetime import datetime
from zoneinfo import ZoneInfo

from news_pipeline.config.schema import HoldingEntry, HoldingsFile, PortfolioCfg
from quote_watcher.alerts.context import (
    build_composite_holding_context,
    build_composite_portfolio_context,
)
from quote_watcher.feeds.base import QuoteSnapshot

BJ = ZoneInfo("Asia/Shanghai")


def make_snap(ticker: str, price: float) -> QuoteSnapshot:
    return QuoteSnapshot(
        ticker=ticker, market="SH", name="X",
        ts=datetime(2026, 5, 8, 10, 0, tzinfo=BJ),
        price=price, open=price, high=price, low=price,
        prev_close=price, volume=100, amount=1.0, bid1=price, ask1=price + 0.01,
    )


def test_holding_context_pnl_negative():
    snap = make_snap("600519", 1700.0)
    holding = HoldingEntry(ticker="600519", qty=100, cost_per_share=1850.0)
    ctx = build_composite_holding_context(snap, holding, volume_avg5d=50)
    assert ctx["price_now"] == 1700.0
    assert ctx["cost_per_share"] == 1850.0
    assert ctx["qty"] == 100
    assert abs(ctx["pct_change_from_cost"] - ((1700 - 1850) / 1850 * 100)) < 1e-6
    assert ctx["unrealized_pnl"] == (1700 - 1850) * 100
    assert abs(ctx["unrealized_pnl_pct"] - ((1700 - 1850) / (1850 * 100) * 100 * 100)) < 1e-3


def test_portfolio_context_total_pnl():
    holdings = HoldingsFile(
        holdings=[
            HoldingEntry(ticker="600519", qty=100, cost_per_share=1850.0),
            HoldingEntry(ticker="300750", qty=200, cost_per_share=220.0),
        ],
        portfolio=PortfolioCfg(total_capital=200000),
    )
    snaps = {
        "600519": make_snap("600519", 1700.0),  # -150 × 100 = -15000
        "300750": make_snap("300750", 200.0),   # -20 × 200 = -4000
    }
    ctx = build_composite_portfolio_context(holdings, snaps)
    assert ctx["total_unrealized_pnl"] == -15000 + -4000
    assert ctx["total_unrealized_pnl_pct"] == (-19000 / 200000) * 100
    assert ctx["holding_count_in_loss"] == 2
```

- [ ] **Step 2: Run, expect fail**

- [ ] **Step 3: Implement**

Append to `src/quote_watcher/alerts/context.py`:

```python
from news_pipeline.config.schema import HoldingEntry, HoldingsFile


def build_composite_holding_context(
    snap: QuoteSnapshot,
    holding: HoldingEntry,
    *,
    volume_avg5d: float = 0.0,
    volume_avg20d: float = 0.0,
) -> dict[str, Any]:
    base = build_threshold_context(
        snap, volume_avg5d=volume_avg5d, volume_avg20d=volume_avg20d,
    )
    pct_from_cost = (
        (snap.price - holding.cost_per_share) / holding.cost_per_share * 100
        if holding.cost_per_share > 0 else 0.0
    )
    pnl = (snap.price - holding.cost_per_share) * holding.qty
    pnl_pct = (
        pnl / (holding.cost_per_share * holding.qty) * 100
        if holding.cost_per_share > 0 and holding.qty > 0 else 0.0
    )
    base.update({
        "cost_per_share": holding.cost_per_share,
        "qty": holding.qty,
        "pct_change_from_cost": pct_from_cost,
        "unrealized_pnl": pnl,
        "unrealized_pnl_pct": pnl_pct,
    })
    return base


def build_composite_portfolio_context(
    holdings: HoldingsFile,
    snaps_by_ticker: dict[str, QuoteSnapshot],
) -> dict[str, Any]:
    total_pnl = 0.0
    in_loss = 0
    for h in holdings.holdings:
        snap = snaps_by_ticker.get(h.ticker)
        if snap is None:
            continue
        pnl = (snap.price - h.cost_per_share) * h.qty
        total_pnl += pnl
        if pnl < 0:
            in_loss += 1
    capital = holdings.portfolio.total_capital
    pnl_pct = (total_pnl / capital * 100) if capital and capital > 0 else 0.0
    return {
        "total_unrealized_pnl": total_pnl,
        "total_unrealized_pnl_pct": pnl_pct,
        "holding_count_in_loss": in_loss,
    }
```

- [ ] **Step 4: Run, expect pass**

```bash
uv run pytest tests/unit/quote_watcher/alerts/test_composite_context.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/quote_watcher/alerts/context.py tests/unit/quote_watcher/alerts/test_composite_context.py
git commit -m "feat(v0.4.0): composite context — per-holding + portfolio variables"
```

---

### Task 4.3: AlertEngine extension — composite kind support

**Files:**
- Modify: `src/quote_watcher/alerts/engine.py` (add composite branches + `evaluate_portfolio` method)
- Create: `tests/unit/quote_watcher/alerts/test_composite_engine.py`

- [ ] **Step 1: Failing test**

```python
# tests/unit/quote_watcher/alerts/test_composite_engine.py
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from news_pipeline.config.schema import HoldingEntry, HoldingsFile, PortfolioCfg
from quote_watcher.alerts.engine import AlertEngine
from quote_watcher.alerts.rule import AlertKind, AlertRule
from quote_watcher.feeds.base import QuoteSnapshot
from quote_watcher.state.tracker import StateTracker
from quote_watcher.storage.dao.alert_state import AlertStateDAO
from quote_watcher.storage.db import QuoteDatabase

BJ = ZoneInfo("Asia/Shanghai")


@pytest.mark.asyncio
async def test_composite_holding_triggers_on_loss():
    db = QuoteDatabase("sqlite+aiosqlite:///:memory:")
    await db.initialize()
    tracker = StateTracker(dao=AlertStateDAO(db), now_fn=lambda: 1000)
    holdings = HoldingsFile(holdings=[
        HoldingEntry(ticker="600519", qty=100, cost_per_share=1850.0),
    ])
    rule = AlertRule(
        id="maotai_pos_alert", kind=AlertKind.COMPOSITE,
        holding="600519", expr="pct_change_from_cost <= -8.0",
    )
    engine = AlertEngine(rules=[rule], tracker=tracker, holdings=holdings)
    snap = QuoteSnapshot(
        ticker="600519", market="SH", name="贵州茅台",
        ts=datetime(2026, 5, 8, 10, 0, tzinfo=BJ),
        price=1700.0, open=1850, high=1850, low=1700, prev_close=1850,
        volume=100, amount=1.0, bid1=1700, ask1=1700.01,
    )
    verdicts = await engine.evaluate_for_snapshot(snap)
    assert len(verdicts) == 1
    assert verdicts[0].rule.id == "maotai_pos_alert"


@pytest.mark.asyncio
async def test_portfolio_rule_triggers():
    db = QuoteDatabase("sqlite+aiosqlite:///:memory:")
    await db.initialize()
    tracker = StateTracker(dao=AlertStateDAO(db), now_fn=lambda: 1000)
    holdings = HoldingsFile(
        holdings=[HoldingEntry(ticker="600519", qty=100, cost_per_share=1000.0)],
        portfolio=PortfolioCfg(total_capital=100000),
    )
    rule = AlertRule(
        id="port_pnl_alert", kind=AlertKind.COMPOSITE,
        portfolio=True, expr="total_unrealized_pnl_pct <= -3.0",
    )
    engine = AlertEngine(rules=[rule], tracker=tracker, holdings=holdings)
    snap = QuoteSnapshot(
        ticker="600519", market="SH", name="X",
        ts=datetime(2026, 5, 8, 10, 0, tzinfo=BJ),
        price=950.0, open=1000, high=1000, low=950, prev_close=1000,
        volume=100, amount=1.0, bid1=950, ask1=950.01,
    )
    # current snapshots map
    verdicts = await engine.evaluate_portfolio(snaps_by_ticker={"600519": snap})
    assert len(verdicts) == 1
```

- [ ] **Step 2: Run, expect fail**

- [ ] **Step 3: Refactor AlertEngine**

Modify `src/quote_watcher/alerts/engine.py`:

```python
from quote_watcher.alerts.context import (
    build_composite_holding_context,
    build_composite_portfolio_context,
    build_threshold_context,
)
from news_pipeline.config.schema import HoldingsFile


class AlertEngine:
    def __init__(
        self,
        *,
        rules: list[AlertRule],
        tracker: StateTracker,
        holdings: HoldingsFile | None = None,
    ) -> None:
        self._rules = rules
        self._tracker = tracker
        self._holdings = holdings or HoldingsFile()
        self._holdings_by_ticker = {h.ticker: h for h in self._holdings.holdings}

    async def evaluate_for_snapshot(
        self, snap: QuoteSnapshot, **avg_kwargs: float,
    ) -> list[AlertVerdict]:
        out: list[AlertVerdict] = []
        out += await self._evaluate_threshold_rules(snap, **avg_kwargs)
        out += await self._evaluate_composite_holding_rules(snap, **avg_kwargs)
        return out

    async def evaluate_portfolio(
        self, *, snaps_by_ticker: dict[str, QuoteSnapshot],
    ) -> list[AlertVerdict]:
        portfolio_rules = [
            r for r in self._rules
            if r.kind == AlertKind.COMPOSITE and r.portfolio
        ]
        if not portfolio_rules:
            return []
        ctx = build_composite_portfolio_context(self._holdings, snaps_by_ticker)
        # Use the first holding snapshot as a stand-in for AlertVerdict.snapshot
        # (portfolio verdicts aren't tied to a single ticker, but verdict needs *some* snap).
        any_snap = next(iter(snaps_by_ticker.values()), None)
        if any_snap is None:
            return []
        out: list[AlertVerdict] = []
        for rule in portfolio_rules:
            triggered = self._eval_expr(rule, ctx)
            if not triggered:
                continue
            if await self._tracker.is_in_cooldown(rule.id, "_portfolio", rule.cooldown_min):
                await self._tracker.bump_count(rule.id, "_portfolio")
                continue
            await self._tracker.mark_triggered(
                rule.id, "_portfolio", value=ctx.get("total_unrealized_pnl_pct"),
            )
            out.append(AlertVerdict(rule=rule, snapshot=any_snap, ctx_dump=dict(ctx)))
        return out

    async def _evaluate_threshold_rules(
        self, snap: QuoteSnapshot, **avg_kwargs: float,
    ) -> list[AlertVerdict]:
        applicable = [
            r for r in self._rules
            if r.kind == AlertKind.THRESHOLD and r.ticker == snap.ticker
        ]
        if not applicable:
            return []
        ctx = build_threshold_context(snap, **avg_kwargs)
        return await self._run_rules(applicable, snap, ctx)

    async def _evaluate_composite_holding_rules(
        self, snap: QuoteSnapshot, **avg_kwargs: float,
    ) -> list[AlertVerdict]:
        applicable = [
            r for r in self._rules
            if r.kind == AlertKind.COMPOSITE and r.holding == snap.ticker
        ]
        if not applicable:
            return []
        holding = self._holdings_by_ticker.get(snap.ticker)
        if holding is None:
            log.warning("composite_rule_holding_missing", ticker=snap.ticker)
            return []
        ctx = build_composite_holding_context(snap, holding, **avg_kwargs)
        return await self._run_rules(applicable, snap, ctx)

    async def _run_rules(
        self,
        rules: list[AlertRule],
        snap: QuoteSnapshot,
        ctx: dict,
    ) -> list[AlertVerdict]:
        out: list[AlertVerdict] = []
        for rule in rules:
            if not self._eval_expr(rule, ctx):
                continue
            if await self._tracker.is_in_cooldown(rule.id, snap.ticker, rule.cooldown_min):
                await self._tracker.bump_count(rule.id, snap.ticker)
                continue
            await self._tracker.mark_triggered(
                rule.id, snap.ticker, value=ctx.get("price_now"),
            )
            out.append(AlertVerdict(rule=rule, snapshot=snap, ctx_dump=dict(ctx)))
        return out

    def _eval_expr(self, rule: AlertRule, ctx: dict) -> bool:
        interp = asteval.Interpreter(usersyms=ctx, no_print=True, no_assert=True)
        try:
            result = bool(interp(rule.expr))
        except Exception as e:
            log.warning("rule_eval_failed", rule=rule.id, error=str(e))
            return False
        if interp.error:
            log.warning("rule_eval_runtime_error", rule=rule.id,
                        errors=[str(e.get_error()) for e in interp.error])
            return False
        return result
```

- [ ] **Step 4: Run all alert tests, expect pass**

```bash
uv run pytest tests/unit/quote_watcher/alerts -v
```
Expected: all PASS (including the older `test_engine.py` cases — make sure refactor didn't break them).

- [ ] **Step 5: Commit**

```bash
git add src/quote_watcher/alerts/engine.py tests/unit/quote_watcher/alerts/test_composite_engine.py
git commit -m "feat(v0.4.0): AlertEngine — composite holding + portfolio support"
```

---

### Task 4.4: Wire holdings + portfolio evaluation into scheduler tick

**Files:**
- Modify: `src/quote_watcher/main.py` (pass holdings to AlertEngine, run evaluate_portfolio per tick)
- Modify: `src/quote_watcher/scheduler/jobs.py` (extend evaluate_alerts with portfolio path)
- Create: `tests/integration/quote_watcher/test_e2e_composite.py`

- [ ] **Step 1: Update main.py**

In `src/quote_watcher/main.py`:

```python
    engine = AlertEngine(
        rules=snap.alerts.alerts,
        tracker=tracker,
        holdings=snap.holdings,
    )
```

In the polling loop body, after `evaluate_alerts`:

```python
    snaps_by_ticker = {s.ticker: s for s in snaps}
    portfolio_verdicts = await engine.evaluate_portfolio(snaps_by_ticker=snaps_by_ticker)
    for v in portfolio_verdicts:
        msg = build_alert_message(v)
        await dispatcher.dispatch(msg, channels=cn_alert_channels)
```

(import `build_alert_message` from `quote_watcher.emit.message` — adjust as needed.)

- [ ] **Step 2: Integration test for composite holding rule**

```python
# tests/integration/quote_watcher/test_e2e_composite.py
from datetime import datetime
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import httpx
import pytest
import respx

from news_pipeline.config.schema import HoldingEntry, HoldingsFile, PortfolioCfg
from quote_watcher.alerts.engine import AlertEngine
from quote_watcher.alerts.rule import AlertKind, AlertRule
from quote_watcher.emit.message import build_alert_message
from quote_watcher.feeds.sina import SinaFeed
from quote_watcher.scheduler.jobs import evaluate_alerts
from quote_watcher.state.tracker import StateTracker
from quote_watcher.storage.dao.alert_state import AlertStateDAO
from quote_watcher.storage.db import QuoteDatabase

BJ = ZoneInfo("Asia/Shanghai")

# Maotai @ 1700 (cost was 1850 → -8.1% from cost)
SINA_AT_LOSS = (
    'var hq_str_sh600519="贵州茅台,1850.000,1850.000,1700.000,'
    '1850.000,1700.000,1700.000,1700.010,2823100,5043500000.00,'
    '200,1700.000,500,1699.500,300,1699.000,400,1698.500,500,1698.000,'
    '100,1700.010,200,1700.020,300,1700.030,400,1700.040,500,1700.050,'
    '2026-05-08,10:00:25,00";\n'
)


@pytest.mark.asyncio
@respx.mock
async def test_e2e_composite_holding_loss_pushes():
    respx.get("https://hq.sinajs.cn/list=sh600519").mock(
        return_value=httpx.Response(200, content=SINA_AT_LOSS.encode("gbk"))
    )

    db = QuoteDatabase("sqlite+aiosqlite:///:memory:")
    await db.initialize()
    tracker = StateTracker(dao=AlertStateDAO(db), now_fn=lambda: 1000)
    holdings = HoldingsFile(
        holdings=[HoldingEntry(ticker="600519", qty=100, cost_per_share=1850.0)],
        portfolio=PortfolioCfg(total_capital=200000),
    )
    rule = AlertRule(
        id="maotai_pos_alert", kind=AlertKind.COMPOSITE,
        holding="600519", expr="pct_change_from_cost <= -8.0",
    )
    engine = AlertEngine(rules=[rule], tracker=tracker, holdings=holdings)
    dispatcher = AsyncMock()
    dispatcher.dispatch.return_value = {"feishu_cn": "ok"}

    feed = SinaFeed()
    snaps = await feed.fetch([("SH", "600519")])
    pushed = await evaluate_alerts(
        snaps=snaps, engine=engine, dispatcher=dispatcher, channels=["feishu_cn"],
    )
    assert pushed == 1
    msg = dispatcher.dispatch.call_args.args[0]
    assert "贵州茅台" in msg.title
```

- [ ] **Step 3: Run integration tests**

```bash
uv run pytest tests/integration/quote_watcher -v
```

- [ ] **Step 4: Commit + tag**

```bash
git add -A
git commit -m "feat(v0.4.0): wire composite holdings + portfolio rules end-to-end"
git tag s3-complete
```

---

### Task 4.5: Final S0-S3 regression sweep

**Files:** none (verification only)

- [ ] **Step 1: Full test + lint + type + pre-commit**

```bash
uv run pytest -v 2>&1 | tail -30
uv run ruff check src/ tests/
uv run mypy src/
uv run pre-commit run --all-files
```
All green.

- [ ] **Step 2: News pipeline regression check**

```bash
NEWS_PIPELINE_ONCE=1 uv run python -m news_pipeline.main 2>&1 | tail -10
```
Expected: no `ImportError` / `AttributeError`. Functional behavior unchanged from before refactor.

- [ ] **Step 3: Quote watcher dry run**

```bash
QUOTE_POLL_INTERVAL_SEC=3 timeout 12 uv run python -m quote_watcher.main 2>&1 | tail -20
```
Expected: clean startup, clean shutdown, no exceptions.

- [ ] **Step 4: Tag MVP done**

```bash
git tag v0.4.0-mvp-plan-a
```

- [ ] **Step 5: Manual verification (live)**

If A-share market is open, run the watcher with a real Feishu webhook (set `secrets.yml`) and the existing `alerts.yml` for ~30 minutes during a session with movement. Look at `data/quotes.db` `alert_state` table and the Feishu group for actual pushes.

```bash
uv run python -m quote_watcher.main &
PID=$!
sleep 1800   # 30 min
kill $PID
sqlite3 data/quotes.db "SELECT rule_id, ticker, trigger_count_today, datetime(last_triggered_at,'unixepoch','+8 hours') FROM alert_state ORDER BY last_triggered_at DESC LIMIT 20;"
```

If anything looks wrong (rule too noisy, false positives), tune `alerts.yml` or `cooldown_min` and iterate.

---

## Self-Review Notes

The plan is intended to be sequenced strictly: S0 must end with all news-pipeline tests green, S1 must end with the watcher polling + storing without alerts, S2 must end with end-to-end threshold push working in integration, S3 must end with composite + portfolio rules working.

**Spec coverage**:
- §1 architecture → S0 R1-R5 + S1 skeleton ✓
- §2 feeds layer → S1 Tasks 2.1-2.3 ✓
- §3 store layer → S1 Tasks 2.4 (tick) + 2.6 (SQLite); 1min bar aggregation deferred to Plan B (S5 does it for indicators) — flagged.
- §4 alerts engine threshold + composite → S2/S3 fully covered ✓
- §4 indicator + event kinds → Plan B (S5/S6)
- §5 state machine → S2 Task 3.3 ✓
- §6 yaml schemas → all three covered (S1.5, S2.1, S3.1) ✓
- §7 message styles single + burst → S2 Task 3.5 + 3.7 ✓
- §7 market_scan + position styles → Plan B (S4) + verified for position in S3
- §8 refactor → S0 R1-R5 ✓
- §9 error handling → calendar + retry + asteval safety covered ✓
- §10 testing → unit + integration ✓ (eval/replay deferred to Plan B S7)
- §11 sprint S0-S3 → fully covered ✓

**Known gaps** (deferred to Plan B):
1. 1-min bar aggregator from tick (S5)
2. Daily K SQLite + indicator computation (S5)
3. Market-scan job (S4)
4. Sector + event rules (S6)
5. preview-rules CLI (S7)
6. alembic migrations for quotes.db (S7)
7. Hot reload for alerts.yml (deferred — restart works for now)

These are all Plan B scope, not Plan A gaps.

---

## Execution

Plan complete and saved to `docs/superpowers/plans/2026-05-08-quote-watcher-impl-A.md`. Two execution options:

**1. Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
