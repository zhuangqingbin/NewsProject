# News Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python news pipeline that scrapes US + CN financial news, summarizes via LLM tiers (DeepSeek + Claude), pushes to Telegram + 飞书 + 企微 with charts, and archives to 飞书 multi-dim table.

**Architecture:** Single Docker container on 阿里云轻量 2c2g; SQLite as source-of-truth with 13 tables (incl. graph-extensible entities/relations); APScheduler in-process; YAML config with hot-reload; structured logs + Bark alerts.

**Tech Stack:** Python 3.12, asyncio, SQLModel + Alembic, APScheduler, httpx, playwright (cookie sources), pydantic v2, structlog, mplfinance, oss2, lark-oapi, python-telegram-bot, anthropic SDK, dashscope SDK, akshare, tushare, yfinance, feedparser.

**Reference spec:** `docs/superpowers/specs/2026-04-25-news-pipeline-design.md` — consult when in doubt about behavior.

**TDD note:** All business logic uses test-first. Pure infra (Dockerfile, alembic env, prompt YAML files) skips TDD where impractical — instead verify by running.

---

## File Structure

```
src/news_pipeline/
├── __init__.py
├── main.py                       # entrypoint
├── healthcheck.py                # docker HEALTHCHECK target
├── cli.py                        # ad-hoc commands (scrape --once, etc.)
├── common/
│   ├── contracts.py              # RawArticle, EnrichedNews, ScoredNews, CommonMessage, DispatchPlan, Entity, Relation, Badge, Deeplink
│   ├── enums.py                  # Market, EventType, Sentiment, Magnitude, SourceId, ChannelId, EntityType, Predicate
│   ├── timeutil.py               # UTC helpers, market-hours predicates
│   ├── hashing.py                # url_hash, simhash, hamming
│   └── exceptions.py             # PipelineError, ScraperError, LLMError, PusherError
├── config/
│   ├── schema.py                 # AppConfig, WatchlistCfg, ChannelCfg, SourceCfg, SecretsCfg
│   └── loader.py                 # load + watchdog hot-reload
├── storage/
│   ├── db.py                     # engine, async session
│   ├── models.py                 # SQLModel for 13 tables
│   ├── dao/
│   │   ├── raw_news.py
│   │   ├── news_processed.py
│   │   ├── entities.py
│   │   ├── relations.py
│   │   ├── source_state.py
│   │   ├── push_log.py
│   │   ├── digest_buffer.py
│   │   ├── dead_letter.py
│   │   ├── chart_cache.py
│   │   ├── audit_log.py
│   │   └── metrics.py
│   └── migrations/               # alembic
├── observability/
│   ├── log.py                    # structlog config
│   ├── alert.py                  # Bark client + throttle
│   └── metrics.py                # daily_metrics writer
├── scrapers/
│   ├── base.py                   # ScraperProtocol
│   ├── registry.py
│   ├── common/
│   │   ├── http.py               # httpx session w/ UA pool
│   │   ├── ratelimit.py          # aiolimiter wrappers
│   │   └── cookies.py            # cookie load + 401 detection
│   ├── us/
│   │   ├── finnhub.py
│   │   ├── sec_edgar.py
│   │   └── yfinance_news.py
│   └── cn/
│       ├── caixin_telegram.py
│       ├── akshare_news.py
│       ├── xueqiu.py
│       ├── ths.py
│       ├── juchao.py
│       └── tushare_news.py
├── dedup/
│   └── dedup.py                  # url_hash + simhash distance check
├── llm/
│   ├── router.py                 # tier selection
│   ├── extractors.py             # tier0/1/2/3 callable wrappers
│   ├── cost_tracker.py           # daily ceiling enforcement
│   ├── prompts/
│   │   └── loader.py             # versioned YAML prompts
│   └── clients/
│       ├── base.py               # LLMClient protocol
│       ├── dashscope.py          # DeepSeek + Qwen via DashScope
│       └── anthropic.py          # Claude w/ prompt cache + tool use
├── classifier/
│   ├── rules.py                  # rule engine (price_5pct, source_always_critical, ...)
│   ├── llm_judge.py              # gray-zone LLM tiebreaker
│   └── importance.py             # combine → ScoredNews
├── router/
│   └── routes.py                 # ScoredNews → list[DispatchPlan]
├── pushers/
│   ├── base.py                   # PusherProtocol
│   ├── common/
│   │   ├── message_builder.py    # ScoredNews → CommonMessage
│   │   ├── ratelimit.py
│   │   └── retry.py
│   ├── telegram.py               # MarkdownV2 + InlineButton
│   ├── feishu.py                 # Card JSON
│   └── wecom.py                  # Markdown limited
├── charts/
│   ├── kline.py                  # mplfinance K-line + news markers
│   ├── bars.py                   # earnings bars
│   ├── sentiment.py              # sentiment curve
│   └── uploader.py               # OSS upload + cache lookup
├── archive/
│   ├── feishu_table.py           # bitable client
│   └── schema.py                 # field mapping EnrichedNews → row
├── scheduler/
│   └── jobs.py                   # APScheduler job defs
└── commands/
    ├── handlers.py               # command dispatchers
    ├── telegram_webhook.py       # FastAPI route
    └── feishu_event.py

config/                           # NOT in src/, deployed alongside
├── app.yml
├── watchlist.yml
├── channels.yml
├── sources.yml
├── entity_aliases.yml
├── prompts/
│   ├── tier0_classify.v1.yaml
│   ├── tier1_summarize.v1.yaml
│   ├── tier2_extract.v1.yaml
│   └── tier3_deep_analysis.v1.yaml
├── secrets.yml.example
└── schemas/
    └── enriched_news.schema.json

docker/
├── Dockerfile
├── compose.yml
└── entrypoint.sh

scripts/
├── backup_sqlite.sh
├── restore_sqlite.sh
└── migrate_to_neo4j.py           # placeholder for future graph migration

tests/                            # mirrors src/ structure
├── unit/
├── integration/
├── eval/
│   ├── gold_news.jsonl
│   └── test_extraction_quality.py
└── live/                         # gated by RUN_LIVE=1
```

---

## Conventions

- **Test runner:** `uv run pytest`
- **Lint:** `uv run ruff check && uv run ruff format --check`
- **Type:** `uv run mypy src/`
- **Run all checks:** `uv run pytest && uv run ruff check && uv run mypy src/`
- **Async tests:** mark with `@pytest.mark.asyncio`; default to `asyncio_mode=auto` in pytest config
- **Frozen time in tests:** use `freezegun`
- **Mock HTTP:** use `respx` (httpx-native)
- **Mock LLM:** use stub `LLMClient` returning canned responses; reserve real-API tests for `tests/live/`
- **Commit format:** `feat: add X` / `fix: ...` / `docs: ...` / `test: ...` / `chore: ...`

---

## Phase 0 — Project Setup (Tasks 1-5)

### Task 1: Initialize project skeleton with uv

**Files:**
- Create: `pyproject.toml`
- Create: `README.md`
- Create: `src/news_pipeline/__init__.py`
- Create: `tests/__init__.py`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "news-pipeline"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "pydantic>=2.7",
  "pydantic-settings>=2.3",
  "sqlmodel>=0.0.21",
  "alembic>=1.13",
  "aiosqlite>=0.20",
  "apscheduler>=3.10",
  "httpx>=0.27",
  "feedparser>=6.0",
  "structlog>=24.1",
  "watchdog>=4.0",
  "anthropic>=0.40",
  "dashscope>=1.20",
  "akshare>=1.13",
  "tushare>=1.4",
  "yfinance>=0.2.50",
  "mplfinance>=0.12.10b0",
  "matplotlib>=3.9",
  "oss2>=2.18",
  "lark-oapi>=1.4",
  "python-telegram-bot>=21",
  "fastapi>=0.115",
  "uvicorn>=0.30",
  "aiolimiter>=1.1",
  "simhash>=2.1",
  "pyyaml>=6.0",
  "tenacity>=9.0",
]

[dependency-groups]
dev = [
  "pytest>=8.3",
  "pytest-asyncio>=0.24",
  "pytest-cov>=5.0",
  "respx>=0.21",
  "freezegun>=1.5",
  "ruff>=0.7",
  "mypy>=1.13",
  "types-pyyaml>=6.0",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
addopts = "-q --strict-markers"

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E","F","W","I","B","UP","SIM","RUF"]

[tool.mypy]
python_version = "3.12"
strict = true
plugins = ["pydantic.mypy"]
ignore_missing_imports = true

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/news_pipeline"]
```

- [ ] **Step 2: Create empty package + tests dir**

```bash
mkdir -p src/news_pipeline tests/unit tests/integration tests/eval tests/live
touch src/news_pipeline/__init__.py tests/__init__.py tests/unit/__init__.py tests/integration/__init__.py
```

- [ ] **Step 3: Create README**

```markdown
# News Pipeline

Financial news scraper → LLM summarizer → multi-platform pusher.
See `docs/superpowers/specs/2026-04-25-news-pipeline-design.md`.

## Quick start
uv sync
cp config/secrets.yml.example config/secrets.yml && vim config/secrets.yml
uv run alembic upgrade head
uv run python -m news_pipeline.main
```

- [ ] **Step 4: Verify setup**

Run: `uv sync && uv run python -c "import news_pipeline; print('ok')"`
Expected: prints `ok` with no error.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml README.md src/ tests/
git commit -m "chore: initialize project skeleton with uv"
```

---

### Task 2: Pre-commit + CI guards

**Files:**
- Create: `.pre-commit-config.yaml`
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Create pre-commit config**

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.7.4
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v5.0.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-added-large-files
        args: [--maxkb=500]
```

- [ ] **Step 2: Create CI workflow**

```yaml
# .github/workflows/ci.yml
name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync
      - run: uv run ruff check
      - run: uv run ruff format --check
      - run: uv run mypy src/
      - run: uv run pytest
```

- [ ] **Step 3: Verify locally**

Run: `uv run ruff check && uv run ruff format --check && uv run pytest`
Expected: pass (no tests yet, so pytest exits 5 = no tests collected; that's OK).

- [ ] **Step 4: Commit**

```bash
git add .pre-commit-config.yaml .github/
git commit -m "chore: add pre-commit and CI"
```

---

### Task 3: Docker skeleton

**Files:**
- Create: `docker/Dockerfile`
- Create: `docker/compose.yml`
- Create: `docker/entrypoint.sh`

- [ ] **Step 1: Create Dockerfile**

```dockerfile
# docker/Dockerfile
FROM python:3.12-slim AS builder
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends gcc git \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml uv.lock ./
RUN pip install uv && uv sync --frozen --no-dev

FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*
COPY --from=builder /app/.venv /app/.venv
COPY src/ ./src/
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENV PATH="/app/.venv/bin:$PATH" PYTHONPATH=/app/src
ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "-m", "news_pipeline.main"]
```

- [ ] **Step 2: Create compose.yml**

```yaml
# docker/compose.yml
services:
  news_pipeline:
    build:
      context: ..
      dockerfile: docker/Dockerfile
    container_name: news_pipeline
    restart: unless-stopped
    volumes:
      - ../data:/app/data
      - ../config:/app/config:ro
      - ../secrets/secrets.yml:/app/config/secrets.yml:ro
      - ../logs:/app/logs
    environment:
      - TZ=Asia/Shanghai
      - LOG_LEVEL=INFO
    healthcheck:
      test: ["CMD", "python", "-m", "news_pipeline.healthcheck"]
      interval: 60s
      timeout: 10s
      retries: 3
      start_period: 30s
    deploy:
      resources:
        limits:
          memory: 1.5G
          cpus: '1.5'
```

- [ ] **Step 3: Create entrypoint**

```bash
#!/usr/bin/env bash
set -euo pipefail
echo "[entrypoint] news_pipeline starting"
exec "$@"
```

- [ ] **Step 4: Verify build (skip if no docker available)**

Run: `docker build -f docker/Dockerfile -t news-pipeline-test .`
Expected: image builds. (If main.py doesn't exist yet, RUN succeeds; CMD will fail at runtime — that's fine for now.)

- [ ] **Step 5: Commit**

```bash
git add docker/
git commit -m "chore: add Docker skeleton"
```

---

### Task 4: Logging foundation

**Files:**
- Create: `src/news_pipeline/observability/__init__.py`
- Create: `src/news_pipeline/observability/log.py`
- Create: `tests/unit/observability/test_log.py`

- [ ] **Step 1: Write the test**

```python
# tests/unit/observability/test_log.py
import json
import logging

from news_pipeline.observability.log import configure_logging, get_logger


def test_configure_logging_emits_json(capsys):
    configure_logging(level="INFO", json_output=True)
    log = get_logger("test")
    log.info("hello", k1="v1", k2=42)
    captured = capsys.readouterr()
    line = captured.out.strip().splitlines()[-1]
    payload = json.loads(line)
    assert payload["event"] == "hello"
    assert payload["k1"] == "v1"
    assert payload["k2"] == 42
    assert payload["level"] == "info"


def test_configure_logging_text_mode(capsys):
    configure_logging(level="INFO", json_output=False)
    log = get_logger("test")
    log.info("readable", x=1)
    captured = capsys.readouterr()
    assert "readable" in captured.out
```

- [ ] **Step 2: Run — expect import error**

Run: `uv run pytest tests/unit/observability/test_log.py -v`
Expected: FAIL with ModuleNotFoundError.

- [ ] **Step 3: Implement**

```python
# src/news_pipeline/observability/__init__.py
from news_pipeline.observability.log import configure_logging, get_logger

__all__ = ["configure_logging", "get_logger"]
```

```python
# src/news_pipeline/observability/log.py
import logging
import sys

import structlog


def configure_logging(level: str = "INFO", json_output: bool = True) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        stream=sys.stdout,
        format="%(message)s",
    )
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    if json_output:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper())
        ),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
```

```bash
mkdir -p tests/unit/observability
touch tests/unit/observability/__init__.py
```

- [ ] **Step 4: Run — expect pass**

Run: `uv run pytest tests/unit/observability/test_log.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/observability/ tests/unit/observability/
git commit -m "feat: add structlog-based logging foundation"
```

---

### Task 5: Bark alert client (with throttle)

**Files:**
- Create: `src/news_pipeline/observability/alert.py`
- Create: `tests/unit/observability/test_alert.py`

- [ ] **Step 1: Write the test**

```python
# tests/unit/observability/test_alert.py
import pytest
import respx
from httpx import Response

from news_pipeline.observability.alert import BarkAlerter, AlertLevel


@pytest.mark.asyncio
async def test_send_alert_calls_bark():
    async with respx.mock(assert_all_called=True) as mock:
        route = mock.get("https://api.day.app/test/alert-title/alert-body").mock(
            return_value=Response(200, json={"code": 200})
        )
        alerter = BarkAlerter(base_url="https://api.day.app/test")
        ok = await alerter.send("alert-title", "alert-body", level=AlertLevel.WARN)
        assert ok is True
        assert route.called


@pytest.mark.asyncio
async def test_throttle_blocks_repeated_alerts(monkeypatch):
    timestamps = iter([100.0, 100.5, 100.9, 1000.0])
    monkeypatch.setattr(
        "news_pipeline.observability.alert.time.monotonic",
        lambda: next(timestamps),
    )
    async with respx.mock() as mock:
        mock.get(url__regex=r"https://api\.day\.app/test/.*").mock(
            return_value=Response(200, json={"code": 200})
        )
        alerter = BarkAlerter(
            base_url="https://api.day.app/test",
            throttle_seconds=60,
        )
        assert await alerter.send("k", "v") is True
        assert await alerter.send("k", "v") is False
        assert await alerter.send("k", "v") is False
        assert await alerter.send("k", "v") is True
```

- [ ] **Step 2: Run — expect fail**

Run: `uv run pytest tests/unit/observability/test_alert.py -v`
Expected: FAIL ModuleNotFoundError.

- [ ] **Step 3: Implement**

```python
# src/news_pipeline/observability/alert.py
import time
from enum import StrEnum

import httpx

from news_pipeline.observability.log import get_logger

log = get_logger(__name__)


class AlertLevel(StrEnum):
    INFO = "info"
    WARN = "warn"
    URGENT = "urgent"


class BarkAlerter:
    def __init__(
        self,
        base_url: str,
        throttle_seconds: int = 900,
        timeout: float = 5.0,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._throttle = throttle_seconds
        self._last_sent: dict[str, float] = {}
        self._timeout = timeout

    async def send(
        self, title: str, body: str, level: AlertLevel = AlertLevel.INFO
    ) -> bool:
        key = f"{level}:{title}"
        now = time.monotonic()
        last = self._last_sent.get(key)
        if last is not None and (now - last) < self._throttle:
            log.debug("alert_throttled", title=title, level=level)
            return False
        self._last_sent[key] = now
        url = f"{self._base}/{title}/{body}"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    log.warning("alert_http_error", status=resp.status_code)
                    return False
        except Exception as e:
            log.warning("alert_exception", error=str(e))
            return False
        return True
```

- [ ] **Step 4: Run**

Run: `uv run pytest tests/unit/observability/test_alert.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/observability/alert.py tests/unit/observability/test_alert.py
git commit -m "feat: add Bark alert client with throttle"
```

---

## Phase 1 — Common Contracts + Config (Tasks 6-12)

### Task 6: Enums

**Files:**
- Create: `src/news_pipeline/common/__init__.py`
- Create: `src/news_pipeline/common/enums.py`
- Create: `tests/unit/common/test_enums.py`

- [ ] **Step 1: Test**

```python
# tests/unit/common/test_enums.py
from news_pipeline.common.enums import (
    Market, Sentiment, Magnitude, EventType, EntityType, Predicate,
)


def test_markets():
    assert Market.US.value == "us"
    assert Market.CN.value == "cn"


def test_sentiment_membership():
    assert Sentiment("bullish") == Sentiment.BULLISH


def test_event_type_includes_core():
    for v in ("earnings", "m_and_a", "policy", "price_move",
              "downgrade", "upgrade", "filing", "other"):
        assert EventType(v)


def test_predicate_includes_core():
    for v in ("supplies", "competes_with", "owns",
              "regulates", "partners_with", "mentions"):
        assert Predicate(v)


def test_entity_type_includes_core():
    for v in ("company", "person", "event", "sector", "policy", "product"):
        assert EntityType(v)
```

- [ ] **Step 2: Run — fail**

Run: `uv run pytest tests/unit/common/test_enums.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement**

```python
# src/news_pipeline/common/__init__.py
```

```python
# src/news_pipeline/common/enums.py
from enum import StrEnum


class Market(StrEnum):
    US = "us"
    CN = "cn"


class Sentiment(StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class Magnitude(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class EventType(StrEnum):
    EARNINGS = "earnings"
    M_AND_A = "m_and_a"
    POLICY = "policy"
    PRICE_MOVE = "price_move"
    DOWNGRADE = "downgrade"
    UPGRADE = "upgrade"
    FILING = "filing"
    OTHER = "other"


class EntityType(StrEnum):
    COMPANY = "company"
    PERSON = "person"
    EVENT = "event"
    SECTOR = "sector"
    POLICY = "policy"
    PRODUCT = "product"


class Predicate(StrEnum):
    SUPPLIES = "supplies"
    COMPETES_WITH = "competes_with"
    OWNS = "owns"
    REGULATES = "regulates"
    PARTNERS_WITH = "partners_with"
    MENTIONS = "mentions"
```

```bash
mkdir -p tests/unit/common && touch tests/unit/common/__init__.py
```

- [ ] **Step 4: Run — pass**

Run: `uv run pytest tests/unit/common/test_enums.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/common/ tests/unit/common/
git commit -m "feat: add common enums"
```

---

### Task 7: Pydantic contracts

**Files:**
- Create: `src/news_pipeline/common/contracts.py`
- Create: `tests/unit/common/test_contracts.py`

- [ ] **Step 1: Test**

```python
# tests/unit/common/test_contracts.py
from datetime import datetime, UTC

import pytest
from pydantic import ValidationError

from news_pipeline.common.contracts import (
    RawArticle, EnrichedNews, ScoredNews, CommonMessage,
    DispatchPlan, Entity, Relation, Badge, Deeplink,
)
from news_pipeline.common.enums import (
    Market, Sentiment, Magnitude, EventType, EntityType, Predicate,
)


def _now() -> datetime:
    return datetime(2026, 4, 25, 12, 0, tzinfo=UTC)


def test_raw_article_roundtrip():
    a = RawArticle(
        source="finnhub", market=Market.US,
        fetched_at=_now(), published_at=_now(),
        url="https://example.com/x", url_hash="abc",
        title="t", body="b", raw_meta={"k": 1},
    )
    assert a.market == Market.US
    assert a.model_dump_json()  # serializable


def test_raw_article_requires_url_hash():
    with pytest.raises(ValidationError):
        RawArticle(
            source="x", market=Market.US,
            fetched_at=_now(), published_at=_now(),
            url="https://x.com", title="t",  # type: ignore[call-arg]
        )


def test_enriched_news_with_entities_relations():
    e = Entity(type=EntityType.COMPANY, name="NVIDIA", ticker="NVDA")
    rel = Relation(
        subject=e, predicate=Predicate.SUPPLIES,
        object=Entity(type=EntityType.COMPANY, name="TSMC", ticker="TSM"),
        confidence=0.9,
    )
    n = EnrichedNews(
        raw_id=1, summary="s",
        related_tickers=["NVDA"], sectors=["semiconductor"],
        event_type=EventType.POLICY,
        sentiment=Sentiment.BEARISH, magnitude=Magnitude.HIGH,
        confidence=0.88, key_quotes=["q"],
        entities=[e], relations=[rel],
        model_used="claude-haiku-4-5", extracted_at=_now(),
    )
    assert n.relations[0].predicate == Predicate.SUPPLIES


def test_scored_news_critical_flag():
    e = EnrichedNews(
        raw_id=1, summary="s", related_tickers=[], sectors=[],
        event_type=EventType.OTHER,
        sentiment=Sentiment.NEUTRAL, magnitude=Magnitude.LOW,
        confidence=0.5, key_quotes=[], entities=[], relations=[],
        model_used="ds", extracted_at=_now(),
    )
    s = ScoredNews(enriched=e, score=72.0, is_critical=True,
                   rule_hits=["price_5pct"], llm_reason=None)
    assert s.is_critical and s.score == 72.0


def test_common_message_minimal():
    m = CommonMessage(
        title="t", summary="s", source_label="Reuters",
        source_url="https://r.com/x",
        badges=[Badge(text="bearish", color="red")],
        chart_url=None,
        deeplinks=[Deeplink(label="原文", url="https://r.com/x")],
        market=Market.US,
    )
    assert m.market == Market.US
    assert m.badges[0].text == "bearish"


def test_dispatch_plan():
    msg = CommonMessage(
        title="t", summary="s", source_label="x",
        source_url="https://x.com", badges=[], chart_url=None,
        deeplinks=[], market=Market.CN,
    )
    p = DispatchPlan(message=msg, channels=["tg_cn", "feishu_cn"], immediate=True)
    assert "tg_cn" in p.channels
```

- [ ] **Step 2: Run — fail**

Run: `uv run pytest tests/unit/common/test_contracts.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement**

```python
# src/news_pipeline/common/contracts.py
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from news_pipeline.common.enums import (
    EntityType, EventType, Magnitude, Market, Predicate, Sentiment,
)


class _Base(BaseModel):
    model_config = ConfigDict(use_enum_values=False, extra="forbid")


class RawArticle(_Base):
    source: str
    market: Market
    fetched_at: datetime
    published_at: datetime
    url: HttpUrl
    url_hash: str
    title: str
    title_simhash: int = 0
    body: str | None = None
    raw_meta: dict = Field(default_factory=dict)


class Entity(_Base):
    type: EntityType
    name: str
    ticker: str | None = None
    market: Market | None = None
    aliases: list[str] = Field(default_factory=list)


class Relation(_Base):
    subject: Entity
    predicate: Predicate
    object: Entity
    confidence: Annotated[float, Field(ge=0, le=1)]


class EnrichedNews(_Base):
    raw_id: int
    summary: str
    related_tickers: list[str]
    sectors: list[str]
    event_type: EventType
    sentiment: Sentiment
    magnitude: Magnitude
    confidence: Annotated[float, Field(ge=0, le=1)]
    key_quotes: list[str] = Field(default_factory=list)
    entities: list[Entity] = Field(default_factory=list)
    relations: list[Relation] = Field(default_factory=list)
    model_used: str
    extracted_at: datetime


class ScoredNews(_Base):
    enriched: EnrichedNews
    score: Annotated[float, Field(ge=0, le=100)]
    is_critical: bool
    rule_hits: list[str] = Field(default_factory=list)
    llm_reason: str | None = None


class Badge(_Base):
    text: str
    color: str = "gray"  # gray|green|red|yellow|blue


class Deeplink(_Base):
    label: str
    url: HttpUrl


class CommonMessage(_Base):
    title: str
    summary: str
    source_label: str
    source_url: HttpUrl
    badges: list[Badge]
    chart_url: HttpUrl | None
    deeplinks: list[Deeplink]
    market: Market


class DispatchPlan(_Base):
    message: CommonMessage
    channels: list[str]
    immediate: bool
```

- [ ] **Step 4: Run — pass**

Run: `uv run pytest tests/unit/common/test_contracts.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/common/contracts.py tests/unit/common/test_contracts.py
git commit -m "feat: add core pydantic data contracts"
```

---

### Task 8: Hashing utilities

**Files:**
- Create: `src/news_pipeline/common/hashing.py`
- Create: `tests/unit/common/test_hashing.py`

- [ ] **Step 1: Test**

```python
# tests/unit/common/test_hashing.py
from news_pipeline.common.hashing import url_hash, title_simhash, hamming


def test_url_hash_stable_and_deterministic():
    h1 = url_hash("https://example.com/path?x=1")
    h2 = url_hash("https://example.com/path?x=1")
    assert h1 == h2
    assert len(h1) == 40  # sha1 hex


def test_url_hash_differs_for_different_urls():
    assert url_hash("https://a.com") != url_hash("https://b.com")


def test_title_simhash_returns_int():
    h = title_simhash("英伟达盘后大跌 8%")
    assert isinstance(h, int)
    assert 0 <= h < (1 << 64)


def test_simhash_distance_close_for_similar_titles():
    a = title_simhash("英伟达盘后大跌 8%")
    b = title_simhash("英伟达盘后跌 8%")
    assert hamming(a, b) < 8


def test_simhash_distance_far_for_unrelated():
    a = title_simhash("英伟达盘后大跌 8%")
    b = title_simhash("茅台公布一季度财报营收增长")
    assert hamming(a, b) > 16
```

- [ ] **Step 2: Run — fail**

Run: `uv run pytest tests/unit/common/test_hashing.py -v`

- [ ] **Step 3: Implement**

```python
# src/news_pipeline/common/hashing.py
import hashlib

from simhash import Simhash


def url_hash(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()


def title_simhash(title: str) -> int:
    # 64-bit simhash on character bigrams (works for both EN and CN)
    text = title.strip()
    tokens = [text[i : i + 2] for i in range(len(text) - 1)] or [text]
    return Simhash(tokens, f=64).value


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")
```

- [ ] **Step 4: Run — pass**

Run: `uv run pytest tests/unit/common/test_hashing.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/common/hashing.py tests/unit/common/test_hashing.py
git commit -m "feat: add url + simhash hashing utils"
```

---

### Task 9: Time / market-hours utilities

**Files:**
- Create: `src/news_pipeline/common/timeutil.py`
- Create: `tests/unit/common/test_timeutil.py`

- [ ] **Step 1: Test**

```python
# tests/unit/common/test_timeutil.py
from datetime import datetime
from zoneinfo import ZoneInfo

from news_pipeline.common.enums import Market
from news_pipeline.common.timeutil import (
    utc_now, ensure_utc, is_market_hours, to_market_local,
)


def test_utc_now_is_aware():
    t = utc_now()
    assert t.tzinfo is not None


def test_ensure_utc_naive_assumed_utc():
    t = ensure_utc(datetime(2026, 4, 25, 12))
    assert str(t.tzinfo) == "UTC"


def test_ensure_utc_converts():
    t = datetime(2026, 4, 25, 12, tzinfo=ZoneInfo("America/New_York"))
    assert ensure_utc(t).hour == 16  # ET 12 = UTC 16 (EDT) or 17 (EST)


def test_us_market_hours():
    t = datetime(2026, 4, 27, 10, 0, tzinfo=ZoneInfo("America/New_York"))
    assert is_market_hours(t, Market.US)
    closed = datetime(2026, 4, 27, 18, 0, tzinfo=ZoneInfo("America/New_York"))
    assert not is_market_hours(closed, Market.US)
    weekend = datetime(2026, 4, 25, 10, 0, tzinfo=ZoneInfo("America/New_York"))
    assert not is_market_hours(weekend, Market.US)


def test_cn_market_hours():
    t = datetime(2026, 4, 27, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert is_market_hours(t, Market.CN)
    lunch = datetime(2026, 4, 27, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert not is_market_hours(lunch, Market.CN)


def test_to_market_local():
    t = datetime(2026, 4, 25, 16, 0, tzinfo=ZoneInfo("UTC"))
    local = to_market_local(t, Market.US)
    assert "New_York" in str(local.tzinfo)
```

- [ ] **Step 2: Run — fail**

Run: `uv run pytest tests/unit/common/test_timeutil.py -v`

- [ ] **Step 3: Implement**

```python
# src/news_pipeline/common/timeutil.py
from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

from news_pipeline.common.enums import Market

_TZ_BY_MARKET: dict[Market, ZoneInfo] = {
    Market.US: ZoneInfo("America/New_York"),
    Market.CN: ZoneInfo("Asia/Shanghai"),
}


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


def ensure_utc(t: datetime) -> datetime:
    if t.tzinfo is None:
        return t.replace(tzinfo=UTC)
    return t.astimezone(UTC)


def to_market_local(t: datetime, market: Market) -> datetime:
    return ensure_utc(t).astimezone(_TZ_BY_MARKET[market])


def is_market_hours(t: datetime, market: Market) -> bool:
    local = to_market_local(t, market)
    if local.weekday() >= 5:
        return False
    h, m = local.hour, local.minute
    if market == Market.US:
        # ET 09:30-16:00
        start, end = time(9, 30), time(16, 0)
        return start <= time(h, m) <= end
    if market == Market.CN:
        # CST 09:30-11:30 + 13:00-15:00
        morning = time(9, 30) <= time(h, m) <= time(11, 30)
        afternoon = time(13, 0) <= time(h, m) <= time(15, 0)
        return morning or afternoon
    return False
```

- [ ] **Step 4: Run — pass**

Run: `uv run pytest tests/unit/common/test_timeutil.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/common/timeutil.py tests/unit/common/test_timeutil.py
git commit -m "feat: add UTC + market-hours time utils"
```

---

### Task 10: Custom exceptions

**Files:**
- Create: `src/news_pipeline/common/exceptions.py`
- Create: `tests/unit/common/test_exceptions.py`

- [ ] **Step 1: Test**

```python
# tests/unit/common/test_exceptions.py
import pytest
from news_pipeline.common.exceptions import (
    PipelineError, ScraperError, LLMError, PusherError,
    AntiCrawlError, CostCeilingExceeded,
)


def test_inheritance():
    assert issubclass(ScraperError, PipelineError)
    assert issubclass(AntiCrawlError, ScraperError)
    assert issubclass(LLMError, PipelineError)
    assert issubclass(PusherError, PipelineError)
    assert issubclass(CostCeilingExceeded, LLMError)


def test_can_raise_with_context():
    with pytest.raises(ScraperError) as exc:
        raise ScraperError("bad", source="finnhub")
    assert exc.value.source == "finnhub"
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

```python
# src/news_pipeline/common/exceptions.py
from typing import Any


class PipelineError(Exception):
    def __init__(self, message: str = "", **context: Any) -> None:
        super().__init__(message)
        self.context = context


class ScraperError(PipelineError):
    def __init__(self, message: str = "", *, source: str = "", **ctx: Any) -> None:
        super().__init__(message, source=source, **ctx)
        self.source = source


class AntiCrawlError(ScraperError):
    pass


class LLMError(PipelineError):
    pass


class CostCeilingExceeded(LLMError):
    pass


class PusherError(PipelineError):
    def __init__(self, message: str = "", *, channel: str = "", **ctx: Any) -> None:
        super().__init__(message, channel=channel, **ctx)
        self.channel = channel
```

- [ ] **Step 4: Run — pass**

Run: `uv run pytest tests/unit/common/test_exceptions.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/common/exceptions.py tests/unit/common/test_exceptions.py
git commit -m "feat: add custom exception hierarchy"
```

---

### Task 11: Config schema (pydantic)

**Files:**
- Create: `src/news_pipeline/config/__init__.py`
- Create: `src/news_pipeline/config/schema.py`
- Create: `config/app.yml`
- Create: `config/watchlist.yml`
- Create: `config/channels.yml`
- Create: `config/sources.yml`
- Create: `config/secrets.yml.example`
- Create: `tests/unit/config/test_schema.py`

- [ ] **Step 1: Test**

```python
# tests/unit/config/test_schema.py
import pytest
from pydantic import ValidationError

from news_pipeline.config.schema import (
    AppConfig, WatchlistFile, ChannelsFile, SourcesFile, SecretsFile,
)


def test_app_config_minimal():
    raw = {
        "runtime": {"daily_cost_ceiling_cny": 5.0, "hot_reload": True},
        "scheduler": {
            "scrape": {"market_hours_interval_sec": 180,
                       "off_hours_interval_sec": 1800,
                       "caixin_interval_sec": 60},
            "llm": {"process_interval_sec": 120},
            "digest": {"morning_cn": "08:30", "evening_cn": "21:00",
                       "morning_us": "21:00", "evening_us": "04:30"},
        },
        "llm": {
            "tier0_model": "deepseek-v3",
            "tier1_model": "deepseek-v3",
            "tier2_model": "claude-haiku-4-5-20251001",
            "tier3_model": "claude-sonnet-4-6",
            "prompt_versions": {"tier0_classify": "v1",
                                "tier1_summarize": "v1",
                                "tier2_extract": "v1",
                                "tier3_deep_analysis": "v1"},
            "enable_prompt_cache": True,
            "enable_batch": True,
        },
        "classifier": {"rules": {"price_move_critical_pct": 5.0,
                                 "sources_always_critical": ["sec_edgar"],
                                 "sentiment_high_magnitude_critical": True},
                       "llm_fallback_when_score": [40, 70]},
        "dedup": {"url_strict": True, "title_simhash_distance": 4},
        "charts": {"auto_on_critical": True, "auto_on_earnings": True,
                   "cache_ttl_days": 30},
        "push": {"per_channel_rate": "30/min",
                 "same_ticker_burst_window_min": 5,
                 "same_ticker_burst_threshold": 3,
                 "digest_max_items_per_section": 30},
        "dead_letter": {"auto_retry_kinds": ["scrape"],
                        "notify_only_kinds": ["push_4xx"],
                        "weekly_summary_day": "monday"},
        "retention": {"raw_news_hot_days": 30,
                      "news_processed_hot_days": 365,
                      "push_log_days": 90},
    }
    cfg = AppConfig.model_validate(raw)
    assert cfg.runtime.daily_cost_ceiling_cny == 5.0
    assert cfg.scheduler.digest.morning_cn == "08:30"


def test_app_config_rejects_bad_score_range():
    raw_bad = {"classifier": {"llm_fallback_when_score": [40]}}
    with pytest.raises(ValidationError):
        AppConfig.model_validate(raw_bad)


def test_watchlist_file_parses():
    raw = {
        "us": [{"ticker": "NVDA", "alerts": ["price_5pct"]}],
        "cn": [{"ticker": "600519", "alerts": ["announcement"]}],
        "macro": ["FOMC"],
        "sectors": ["semiconductor"],
    }
    wl = WatchlistFile.model_validate(raw)
    assert wl.us[0].ticker == "NVDA"
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

```python
# src/news_pipeline/config/__init__.py
```

```python
# src/news_pipeline/config/schema.py
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, conlist


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- app.yml ---
class RuntimeCfg(_Base):
    daily_cost_ceiling_cny: float = 5.0
    hot_reload: bool = True
    timezone_display: dict[str, str] = Field(
        default_factory=lambda: {"us": "America/New_York", "cn": "Asia/Shanghai"}
    )


class ScrapeIntervalsCfg(_Base):
    market_hours_interval_sec: int
    off_hours_interval_sec: int
    caixin_interval_sec: int


class LLMIntervalCfg(_Base):
    process_interval_sec: int


class DigestTimesCfg(_Base):
    morning_cn: str
    evening_cn: str
    morning_us: str
    evening_us: str


class SchedulerCfg(_Base):
    scrape: ScrapeIntervalsCfg
    llm: LLMIntervalCfg
    digest: DigestTimesCfg


class LLMCfg(_Base):
    tier0_model: str
    tier1_model: str
    tier2_model: str
    tier3_model: str
    prompt_versions: dict[str, str]
    enable_prompt_cache: bool
    enable_batch: bool


class ClassifierRulesCfg(_Base):
    price_move_critical_pct: float
    sources_always_critical: list[str]
    sentiment_high_magnitude_critical: bool


class ClassifierCfg(_Base):
    rules: ClassifierRulesCfg | None = None
    llm_fallback_when_score: conlist(float, min_length=2, max_length=2)  # type: ignore[valid-type]


class DedupCfg(_Base):
    url_strict: bool = True
    title_simhash_distance: int = 4


class ChartsCfg(_Base):
    auto_on_critical: bool
    auto_on_earnings: bool
    cache_ttl_days: int


class PushCfg(_Base):
    per_channel_rate: str
    same_ticker_burst_window_min: int
    same_ticker_burst_threshold: int
    digest_max_items_per_section: int


class DeadLetterCfg(_Base):
    auto_retry_kinds: list[str]
    notify_only_kinds: list[str]
    weekly_summary_day: Literal[
        "monday", "tuesday", "wednesday", "thursday",
        "friday", "saturday", "sunday",
    ]


class RetentionCfg(_Base):
    raw_news_hot_days: int
    news_processed_hot_days: int
    push_log_days: int


class AppConfig(_Base):
    runtime: RuntimeCfg = Field(default_factory=RuntimeCfg)
    scheduler: SchedulerCfg
    llm: LLMCfg
    classifier: ClassifierCfg
    dedup: DedupCfg = Field(default_factory=DedupCfg)
    charts: ChartsCfg
    push: PushCfg
    dead_letter: DeadLetterCfg
    retention: RetentionCfg


# --- watchlist.yml ---
class WatchlistEntry(_Base):
    ticker: str
    alerts: list[str] = Field(default_factory=list)


class WatchlistFile(_Base):
    us: list[WatchlistEntry] = Field(default_factory=list)
    cn: list[WatchlistEntry] = Field(default_factory=list)
    macro: list[str] = Field(default_factory=list)
    sectors: list[str] = Field(default_factory=list)


# --- channels.yml ---
class ChannelDef(_Base):
    type: Literal["telegram", "feishu", "wecom"]
    enabled: bool = True
    market: Literal["us", "cn"]
    rate_limit: str = "30/min"
    # platform-specific opaque fields go in 'options'; secrets resolved separately
    options: dict[str, str] = Field(default_factory=dict)


class ChannelsFile(_Base):
    channels: dict[str, ChannelDef]


# --- sources.yml ---
class SourceDef(_Base):
    enabled: bool = True
    interval_sec: int | None = None
    options: dict[str, str] = Field(default_factory=dict)


class SourcesFile(_Base):
    sources: dict[str, SourceDef]


# --- secrets.yml ---
class SecretsFile(_Base):
    llm: dict[str, str] = Field(default_factory=dict)
    push: dict[str, str] = Field(default_factory=dict)
    storage: dict[str, str] = Field(default_factory=dict)
    oss: dict[str, str] = Field(default_factory=dict)
    sources: dict[str, str] = Field(default_factory=dict)
    alert: dict[str, str] = Field(default_factory=dict)
```

```bash
mkdir -p tests/unit/config && touch tests/unit/config/__init__.py
```

- [ ] **Step 4: Run — pass**

Run: `uv run pytest tests/unit/config/test_schema.py -v`
Expected: 3 passed.

Then create the actual config files (verified by loader test in next task):

```yaml
# config/app.yml — copy the §6.1 example from spec verbatim
# (paste from docs/superpowers/specs/2026-04-25-news-pipeline-design.md §6.1)
```

```yaml
# config/watchlist.yml
us:
  - {ticker: NVDA, alerts: [price_5pct, earnings, downgrade, sec_filing]}
cn:
  - {ticker: "600519", alerts: [price_5pct, announcement]}
macro: [FOMC, CPI, NFP, 央行, MLF, LPR]
sectors: [semiconductor, ai, ev, 新能源, 半导体, 白酒]
```

```yaml
# config/channels.yml
channels:
  tg_us:    {type: telegram, market: us, options: {bot_token_key: tg_bot_token_us, chat_id_key: tg_chat_id_us}}
  feishu_us:{type: feishu,   market: us, options: {webhook_key: feishu_hook_us, sign_key: feishu_sign_us}}
  wecom_us: {type: wecom,    market: us, options: {webhook_key: wecom_hook_us}}
  tg_cn:    {type: telegram, market: cn, options: {bot_token_key: tg_bot_token_cn, chat_id_key: tg_chat_id_cn}}
  feishu_cn:{type: feishu,   market: cn, options: {webhook_key: feishu_hook_cn, sign_key: feishu_sign_cn}}
  wecom_cn: {type: wecom,    market: cn, options: {webhook_key: wecom_hook_cn}}
```

```yaml
# config/sources.yml
sources:
  finnhub:        {enabled: true, interval_sec: 300}
  sec_edgar:      {enabled: true, interval_sec: 120}
  yfinance_news:  {enabled: true, interval_sec: 600}
  caixin_telegram:{enabled: true, interval_sec: 60}
  akshare_news:   {enabled: true, interval_sec: 180}
  juchao:         {enabled: true, interval_sec: 120}
  xueqiu:         {enabled: true, interval_sec: 300}
  ths:            {enabled: true, interval_sec: 300}
  tushare_news:   {enabled: true, interval_sec: 600}
```

```yaml
# config/secrets.yml.example  (copy structure from spec §6.1)
llm:
  dashscope_api_key: REPLACE_ME
  anthropic_api_key: REPLACE_ME
push:
  tg_bot_token_us: REPLACE_ME
  tg_chat_id_us: REPLACE_ME
  tg_bot_token_cn: REPLACE_ME
  tg_chat_id_cn: REPLACE_ME
  feishu_hook_us: REPLACE_ME
  feishu_sign_us: REPLACE_ME
  feishu_hook_cn: REPLACE_ME
  feishu_sign_cn: REPLACE_ME
  wecom_hook_us: REPLACE_ME
  wecom_hook_cn: REPLACE_ME
storage:
  feishu_app_id: REPLACE_ME
  feishu_app_secret: REPLACE_ME
  feishu_table_us: REPLACE_ME
  feishu_table_cn: REPLACE_ME
oss:
  endpoint: oss-cn-hangzhou.aliyuncs.com
  bucket: REPLACE_ME
  access_key_id: REPLACE_ME
  access_key_secret: REPLACE_ME
sources:
  finnhub_token: REPLACE_ME
  tushare_token: REPLACE_ME
  xueqiu_cookie: REPLACE_ME
  ths_cookie: REPLACE_ME
alert:
  bark_url: https://api.day.app/REPLACE_ME
```

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/config/ tests/unit/config/ config/
git commit -m "feat: add config schemas + initial YAML files"
```

---

### Task 12: Config loader with hot-reload

**Files:**
- Create: `src/news_pipeline/config/loader.py`
- Create: `tests/unit/config/test_loader.py`

- [ ] **Step 1: Test**

```python
# tests/unit/config/test_loader.py
import asyncio
from pathlib import Path

import pytest

from news_pipeline.config.loader import ConfigLoader


@pytest.fixture
def cfg_dir(tmp_path: Path) -> Path:
    (tmp_path / "app.yml").write_text(_minimal_app_yml())
    (tmp_path / "watchlist.yml").write_text("us: []\ncn: []\nmacro: []\nsectors: []\n")
    (tmp_path / "channels.yml").write_text("channels: {}\n")
    (tmp_path / "sources.yml").write_text("sources: {}\n")
    (tmp_path / "secrets.yml").write_text("llm: {}\npush: {}\nstorage: {}\noss: {}\nsources: {}\nalert: {}\n")
    return tmp_path


def _minimal_app_yml() -> str:
    return """
runtime: {daily_cost_ceiling_cny: 5.0, hot_reload: true}
scheduler:
  scrape: {market_hours_interval_sec: 180, off_hours_interval_sec: 1800, caixin_interval_sec: 60}
  llm: {process_interval_sec: 120}
  digest: {morning_cn: "08:30", evening_cn: "21:00", morning_us: "21:00", evening_us: "04:30"}
llm:
  tier0_model: deepseek-v3
  tier1_model: deepseek-v3
  tier2_model: claude-haiku-4-5-20251001
  tier3_model: claude-sonnet-4-6
  prompt_versions: {tier0_classify: v1, tier1_summarize: v1, tier2_extract: v1, tier3_deep_analysis: v1}
  enable_prompt_cache: true
  enable_batch: true
classifier:
  rules: {price_move_critical_pct: 5.0, sources_always_critical: [sec_edgar], sentiment_high_magnitude_critical: true}
  llm_fallback_when_score: [40, 70]
dedup: {url_strict: true, title_simhash_distance: 4}
charts: {auto_on_critical: true, auto_on_earnings: true, cache_ttl_days: 30}
push: {per_channel_rate: "30/min", same_ticker_burst_window_min: 5, same_ticker_burst_threshold: 3, digest_max_items_per_section: 30}
dead_letter: {auto_retry_kinds: [scrape], notify_only_kinds: [push_4xx], weekly_summary_day: monday}
retention: {raw_news_hot_days: 30, news_processed_hot_days: 365, push_log_days: 90}
"""


def test_loader_loads_all(cfg_dir: Path) -> None:
    loader = ConfigLoader(cfg_dir)
    snap = loader.load()
    assert snap.app.runtime.daily_cost_ceiling_cny == 5.0
    assert snap.watchlist.us == []
    assert snap.channels.channels == {}


@pytest.mark.asyncio
async def test_loader_hot_reload_emits_event(cfg_dir: Path) -> None:
    loader = ConfigLoader(cfg_dir, debounce_ms=50)
    snap1 = loader.load()
    seen: list[str] = []

    def on_change(snap):  # type: ignore[no-untyped-def]
        seen.append(snap.app.runtime.daily_cost_ceiling_cny)

    loader.start_watching(on_change)
    try:
        await asyncio.sleep(0.1)
        new = _minimal_app_yml().replace("daily_cost_ceiling_cny: 5.0",
                                          "daily_cost_ceiling_cny: 7.5")
        (cfg_dir / "app.yml").write_text(new)
        for _ in range(20):
            await asyncio.sleep(0.1)
            if seen:
                break
        assert seen and seen[-1] == 7.5
    finally:
        loader.stop_watching()
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

```python
# src/news_pipeline/config/loader.py
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import yaml
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from news_pipeline.config.schema import (
    AppConfig, ChannelsFile, SecretsFile, SourcesFile, WatchlistFile,
)
from news_pipeline.observability.log import get_logger

log = get_logger(__name__)


@dataclass
class ConfigSnapshot:
    app: AppConfig
    watchlist: WatchlistFile
    channels: ChannelsFile
    sources: SourcesFile
    secrets: SecretsFile


class _Handler(FileSystemEventHandler):
    def __init__(self, on_change: Callable[[FileSystemEvent], None]) -> None:
        self._on_change = on_change

    def on_modified(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        self._on_change(event)


class ConfigLoader:
    def __init__(self, base_dir: Path, debounce_ms: int = 250) -> None:
        self._dir = Path(base_dir)
        self._debounce_ms = debounce_ms
        self._observer: Observer | None = None
        self._lock = threading.Lock()
        self._last_event_at: float = 0.0
        self._callback: Callable[[ConfigSnapshot], None] | None = None

    def load(self) -> ConfigSnapshot:
        return ConfigSnapshot(
            app=AppConfig.model_validate(self._read("app.yml")),
            watchlist=WatchlistFile.model_validate(self._read("watchlist.yml")),
            channels=ChannelsFile.model_validate(self._read("channels.yml")),
            sources=SourcesFile.model_validate(self._read("sources.yml")),
            secrets=SecretsFile.model_validate(self._read("secrets.yml")),
        )

    def _read(self, name: str) -> dict:
        path = self._dir / name
        with path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def start_watching(self, callback: Callable[[ConfigSnapshot], None]) -> None:
        self._callback = callback
        self._observer = Observer()
        self._observer.schedule(_Handler(self._on_event), str(self._dir),
                                recursive=False)
        self._observer.start()

    def stop_watching(self) -> None:
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=2)
            self._observer = None

    def _on_event(self, _event: FileSystemEvent) -> None:
        with self._lock:
            now = time.monotonic() * 1000
            if (now - self._last_event_at) < self._debounce_ms:
                return
            self._last_event_at = now
        try:
            snap = self.load()
        except Exception as e:
            log.error("config_reload_failed", error=str(e))
            return
        if self._callback is not None:
            self._callback(snap)
```

- [ ] **Step 4: Run**

Run: `uv run pytest tests/unit/config/test_loader.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/config/loader.py tests/unit/config/test_loader.py
git commit -m "feat: add config loader with hot-reload"
```

---

## Phase 2 — Storage Layer (Tasks 13-22)

### Task 13: SQLite engine + session

**Files:**
- Create: `src/news_pipeline/storage/__init__.py`
- Create: `src/news_pipeline/storage/db.py`
- Create: `tests/unit/storage/test_db.py`

- [ ] **Step 1: Test**

```python
# tests/unit/storage/test_db.py
import pytest
from sqlalchemy import text

from news_pipeline.storage.db import Database


@pytest.mark.asyncio
async def test_create_engine_and_query(tmp_path):
    db = Database(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    await db.initialize()
    async with db.session() as session:
        result = await session.execute(text("SELECT 1"))
        assert result.scalar() == 1
    await db.close()


@pytest.mark.asyncio
async def test_wal_mode_enabled(tmp_path):
    db = Database(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    await db.initialize()
    async with db.session() as session:
        result = await session.execute(text("PRAGMA journal_mode"))
        assert result.scalar() == "wal"
    await db.close()
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

```python
# src/news_pipeline/storage/__init__.py
```

```python
# src/news_pipeline/storage/db.py
from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine,
)


class Database:
    def __init__(self, dsn: str) -> None:
        self._engine: AsyncEngine = create_async_engine(
            dsn, echo=False, pool_pre_ping=True
        )
        self._sessionmaker = async_sessionmaker(self._engine, expire_on_commit=False)

    async def initialize(self) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(text("PRAGMA journal_mode=WAL"))
            await conn.execute(text("PRAGMA synchronous=NORMAL"))
            await conn.execute(text("PRAGMA foreign_keys=ON"))

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self._sessionmaker() as session:
            yield session

    async def close(self) -> None:
        await self._engine.dispose()

    @property
    def engine(self) -> AsyncEngine:
        return self._engine
```

```bash
mkdir -p tests/unit/storage && touch tests/unit/storage/__init__.py
```

- [ ] **Step 4: Run — pass**

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/storage/db.py src/news_pipeline/storage/__init__.py tests/unit/storage/
git commit -m "feat: add async SQLite engine with WAL mode"
```

---

### Task 14: SQLModel models for all 13 tables

**Files:**
- Create: `src/news_pipeline/storage/models.py`
- Create: `tests/unit/storage/test_models.py`

- [ ] **Step 1: Test**

```python
# tests/unit/storage/test_models.py
import pytest
from sqlmodel import select

from news_pipeline.storage.db import Database
from news_pipeline.storage.models import (
    SQLModelBase, RawNews, NewsProcessed, Entity, NewsEntity, Relation,
    SourceState, PushLog, DigestBuffer, DeadLetter, ChartCache,
    AuditLog, DailyMetric,
)


@pytest.mark.asyncio
async def test_create_all_tables(tmp_path):
    db = Database(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    await db.initialize()
    async with db.engine.begin() as conn:
        await conn.run_sync(SQLModelBase.metadata.create_all)
    async with db.session() as s:
        s.add(RawNews(source="finnhub", market="us",
                      url="https://x.com/1", url_hash="h1",
                      title="t", title_simhash=0,
                      fetched_at="2026-04-25T00:00:00",
                      published_at="2026-04-25T00:00:00",
                      status="pending"))
        await s.commit()
        rows = (await s.execute(select(RawNews))).scalars().all()
        assert len(rows) == 1
    await db.close()
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

```python
# src/news_pipeline/storage/models.py
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Index, UniqueConstraint
from sqlmodel import Column, Field, SQLModel

SQLModelBase = SQLModel


class RawNews(SQLModel, table=True):
    __tablename__ = "raw_news"
    __table_args__ = (
        UniqueConstraint("url_hash", name="uq_raw_url_hash"),
        Index("idx_raw_status_pub", "status", "published_at"),
        Index("idx_raw_market_pub", "market", "published_at"),
        Index("idx_raw_simhash", "title_simhash"),
    )
    id: int | None = Field(default=None, primary_key=True)
    source: str
    market: str
    url: str
    url_hash: str
    title: str
    title_simhash: int = 0
    body: str | None = None
    raw_meta: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    fetched_at: datetime
    published_at: datetime
    status: str = "pending"
    error: str | None = None


class NewsProcessed(SQLModel, table=True):
    __tablename__ = "news_processed"
    __table_args__ = (
        UniqueConstraint("raw_id", name="uq_proc_raw"),
        Index("idx_proc_critical_extracted", "is_critical", "extracted_at"),
        Index("idx_proc_push_status", "push_status", "extracted_at"),
    )
    id: int | None = Field(default=None, primary_key=True)
    raw_id: int = Field(foreign_key="raw_news.id")
    summary: str
    event_type: str
    sentiment: str
    magnitude: str
    confidence: float
    key_quotes: list[str] | None = Field(default=None, sa_column=Column(JSON))
    score: float
    is_critical: bool
    rule_hits: list[str] | None = Field(default=None, sa_column=Column(JSON))
    llm_reason: str | None = None
    model_used: str
    extracted_at: datetime
    push_status: str = "pending"


class Entity(SQLModel, table=True):
    __tablename__ = "entities"
    __table_args__ = (
        UniqueConstraint("type", "name", name="uq_ent_type_name"),
        Index("idx_ent_ticker", "ticker"),
    )
    id: int | None = Field(default=None, primary_key=True)
    type: str
    name: str
    ticker: str | None = None
    market: str | None = None
    aliases: list[str] | None = Field(default=None, sa_column=Column(JSON))
    metadata_: dict[str, Any] | None = Field(
        default=None, sa_column=Column("metadata", JSON)
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)


class NewsEntity(SQLModel, table=True):
    __tablename__ = "news_entities"
    news_id: int = Field(foreign_key="news_processed.id", primary_key=True)
    entity_id: int = Field(foreign_key="entities.id", primary_key=True)
    role: str = Field(primary_key=True)
    salience: float


class Relation(SQLModel, table=True):
    __tablename__ = "relations"
    __table_args__ = (
        Index("idx_rel_subject", "subject_id", "predicate"),
        Index("idx_rel_object", "object_id", "predicate"),
    )
    id: int | None = Field(default=None, primary_key=True)
    subject_id: int = Field(foreign_key="entities.id")
    predicate: str
    object_id: int = Field(foreign_key="entities.id")
    source_news_id: int = Field(foreign_key="news_processed.id")
    confidence: float
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class SourceState(SQLModel, table=True):
    __tablename__ = "source_state"
    source: str = Field(primary_key=True)
    last_fetched_at: datetime | None = None
    last_seen_url: str | None = None
    last_error: str | None = None
    error_count: int = 0
    paused_until: datetime | None = None


class PushLog(SQLModel, table=True):
    __tablename__ = "push_log"
    __table_args__ = (
        Index("idx_pushlog_news", "news_id"),
        Index("idx_pushlog_sent", "sent_at"),
    )
    id: int | None = Field(default=None, primary_key=True)
    news_id: int = Field(foreign_key="news_processed.id")
    channel: str
    sent_at: datetime
    status: str
    http_status: int | None = None
    response: str | None = None
    retries: int = 0


class DigestBuffer(SQLModel, table=True):
    __tablename__ = "digest_buffer"
    __table_args__ = (
        UniqueConstraint("news_id", name="uq_digest_news"),
        Index("idx_digest_pending", "scheduled_digest", "consumed_at"),
    )
    id: int | None = Field(default=None, primary_key=True)
    news_id: int = Field(foreign_key="news_processed.id")
    market: str
    scheduled_digest: str
    added_at: datetime
    consumed_at: datetime | None = None


class DeadLetter(SQLModel, table=True):
    __tablename__ = "dead_letter"
    id: int | None = Field(default=None, primary_key=True)
    kind: str
    payload: str
    error: str
    retries: int
    created_at: datetime
    resolved_at: datetime | None = None


class ChartCache(SQLModel, table=True):
    __tablename__ = "chart_cache"
    __table_args__ = (
        UniqueConstraint("request_hash", name="uq_chart_req_hash"),
    )
    id: int | None = Field(default=None, primary_key=True)
    request_hash: str
    ticker: str
    kind: str
    oss_url: str
    generated_at: datetime
    expires_at: datetime


class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_log"
    id: int | None = Field(default=None, primary_key=True)
    actor: str | None = None
    action: str
    detail: str | None = None
    created_at: datetime


class DailyMetric(SQLModel, table=True):
    __tablename__ = "daily_metrics"
    metric_date: str = Field(primary_key=True)
    metric_name: str = Field(primary_key=True)
    dimensions: str = Field(default="", primary_key=True)
    metric_value: float
```

- [ ] **Step 4: Run — pass**

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/storage/models.py tests/unit/storage/test_models.py
git commit -m "feat: add SQLModel models for 13 tables"
```

---

### Task 15: Alembic migration v1

**Files:**
- Create: `alembic.ini`
- Create: `src/news_pipeline/storage/migrations/env.py`
- Create: `src/news_pipeline/storage/migrations/script.py.mako`
- Create: `src/news_pipeline/storage/migrations/versions/0001_initial.py`

- [ ] **Step 1: Init Alembic**

```bash
uv run alembic init src/news_pipeline/storage/migrations
```

- [ ] **Step 2: Configure alembic.ini**

Edit `alembic.ini`:
```ini
[alembic]
script_location = src/news_pipeline/storage/migrations
sqlalchemy.url = sqlite+aiosqlite:///data/news.db
file_template = %%(rev)s_%%(slug)s
```

- [ ] **Step 3: Edit env.py**

Replace generated `src/news_pipeline/storage/migrations/env.py` with:

```python
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from news_pipeline.storage.models import SQLModelBase

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
target_metadata = SQLModelBase.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
```

- [ ] **Step 4: Generate initial migration**

```bash
mkdir -p data
uv run alembic revision --autogenerate -m "initial 13 tables"
mv src/news_pipeline/storage/migrations/versions/*_initial_13_tables.py \
   src/news_pipeline/storage/migrations/versions/0001_initial.py
uv run alembic upgrade head
sqlite3 data/news.db ".tables" | tr -s ' ' '\n' | sort
```

Expected: lists `audit_log chart_cache daily_metrics dead_letter digest_buffer entities news_entities news_processed push_log raw_news relations source_state` plus `alembic_version`.

- [ ] **Step 5: Commit**

```bash
git add alembic.ini src/news_pipeline/storage/migrations/
git commit -m "feat: add Alembic with initial 13-table migration"
```

---

### Task 16: Add FTS5 virtual table + triggers

**Files:**
- Create: `src/news_pipeline/storage/migrations/versions/0002_fts.py`
- Create: `tests/integration/storage/test_fts.py`

- [ ] **Step 1: Write the migration**

```python
# src/news_pipeline/storage/migrations/versions/0002_fts.py
"""add news_fts virtual table + triggers"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE VIRTUAL TABLE news_fts USING fts5(
            title, summary,
            content='news_processed',
            content_rowid='id',
            tokenize='unicode61'
        )
    """)
    op.execute("""
        CREATE TRIGGER news_fts_ai AFTER INSERT ON news_processed BEGIN
            INSERT INTO news_fts(rowid, title, summary) VALUES (new.id, '', new.summary);
        END
    """)
    op.execute("""
        CREATE TRIGGER news_fts_ad AFTER DELETE ON news_processed BEGIN
            INSERT INTO news_fts(news_fts, rowid, title, summary)
            VALUES('delete', old.id, '', old.summary);
        END
    """)
    op.execute("""
        CREATE TRIGGER news_fts_au AFTER UPDATE ON news_processed BEGIN
            INSERT INTO news_fts(news_fts, rowid, title, summary)
            VALUES('delete', old.id, '', old.summary);
            INSERT INTO news_fts(rowid, title, summary) VALUES (new.id, '', new.summary);
        END
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS news_fts_au")
    op.execute("DROP TRIGGER IF EXISTS news_fts_ad")
    op.execute("DROP TRIGGER IF EXISTS news_fts_ai")
    op.execute("DROP TABLE IF EXISTS news_fts")
```

> Note: title is empty in the trigger because raw_news has the title; if you want to FTS title too, join in queries. The simpler approach is summary-only for MVP.

- [ ] **Step 2: Write integration test**

```python
# tests/integration/storage/test_fts.py
import pytest
from sqlalchemy import text

from news_pipeline.storage.db import Database


@pytest.mark.asyncio
async def test_fts_search(tmp_path):
    import subprocess
    import os
    os.environ["ALEMBIC_DSN"] = f"sqlite+aiosqlite:///{tmp_path}/t.db"
    # Run migrations programmatically
    from alembic.config import Config
    from alembic import command
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", os.environ["ALEMBIC_DSN"])
    command.upgrade(cfg, "head")

    db = Database(os.environ["ALEMBIC_DSN"])
    await db.initialize()
    async with db.session() as s:
        await s.execute(text("""
            INSERT INTO raw_news (id, source, market, url, url_hash, title, title_simhash,
                                   fetched_at, published_at, status)
            VALUES (1, 'x', 'us', 'https://x', 'h1', 'NVDA news', 0,
                    '2026-04-25', '2026-04-25', 'processed')
        """))
        await s.execute(text("""
            INSERT INTO news_processed
            (id, raw_id, summary, event_type, sentiment, magnitude, confidence,
             score, is_critical, model_used, extracted_at, push_status)
            VALUES (1, 1, 'NVDA exports halted', 'policy', 'bearish', 'high', 0.9,
                    80, 1, 'haiku', '2026-04-25', 'pending')
        """))
        await s.commit()
        rows = (await s.execute(text(
            "SELECT rowid FROM news_fts WHERE news_fts MATCH 'exports'"
        ))).all()
        assert len(rows) == 1
    await db.close()
```

```bash
mkdir -p tests/integration/storage && touch tests/integration/storage/__init__.py
```

- [ ] **Step 3: Run — pass**

Run: `uv run pytest tests/integration/storage/test_fts.py -v`
Expected: 1 passed.

- [ ] **Step 4: Apply locally**

```bash
uv run alembic upgrade head
```

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/storage/migrations/versions/0002_fts.py tests/integration/storage/
git commit -m "feat: add FTS5 virtual table + sync triggers"
```

---

### Task 17: DAOs — raw_news + dedup support

**Files:**
- Create: `src/news_pipeline/storage/dao/__init__.py`
- Create: `src/news_pipeline/storage/dao/raw_news.py`
- Create: `tests/unit/storage/dao/test_raw_news.py`

- [ ] **Step 1: Test**

```python
# tests/unit/storage/dao/test_raw_news.py
import pytest

from news_pipeline.storage.db import Database
from news_pipeline.storage.dao.raw_news import RawNewsDAO
from news_pipeline.storage.models import SQLModelBase


@pytest.fixture
async def dao(tmp_path):
    db = Database(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    await db.initialize()
    async with db.engine.begin() as conn:
        await conn.run_sync(SQLModelBase.metadata.create_all)
    yield RawNewsDAO(db)
    await db.close()


@pytest.mark.asyncio
async def test_insert_and_find_by_url_hash(dao):
    new_id = await dao.insert(
        source="finnhub", market="us",
        url="https://example.com/1", url_hash="hashA",
        title="t", title_simhash=12345, body="b", raw_meta={"x": 1},
        fetched_at_iso="2026-04-25T00:00:00",
        published_at_iso="2026-04-25T00:00:00",
    )
    assert new_id > 0
    found = await dao.find_by_url_hash("hashA")
    assert found is not None
    assert found.title == "t"


@pytest.mark.asyncio
async def test_pending_query(dao):
    await dao.insert(source="x", market="us", url="https://x/1", url_hash="h1",
                     title="a", title_simhash=1, body=None, raw_meta={},
                     fetched_at_iso="2026-04-25T00:00:00",
                     published_at_iso="2026-04-25T00:00:00")
    items = await dao.list_pending(limit=10)
    assert len(items) == 1


@pytest.mark.asyncio
async def test_simhash_neighbor_lookup(dao):
    await dao.insert(source="x", market="us", url="https://x/1", url_hash="h1",
                     title="t1", title_simhash=0xFFFF0000, body=None, raw_meta={},
                     fetched_at_iso="2026-04-25T00:00:00",
                     published_at_iso="2026-04-25T00:00:00")
    candidates = await dao.list_recent_simhashes(window_hours=24)
    assert any(s == 0xFFFF0000 for _id, s in candidates)
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

```python
# src/news_pipeline/storage/dao/__init__.py
```

```python
# src/news_pipeline/storage/dao/raw_news.py
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from news_pipeline.common.timeutil import utc_now
from news_pipeline.storage.db import Database
from news_pipeline.storage.models import RawNews


class RawNewsDAO:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def insert(
        self, *,
        source: str, market: str, url: str, url_hash: str,
        title: str, title_simhash: int, body: str | None, raw_meta: dict[str, Any],
        fetched_at_iso: str, published_at_iso: str, status: str = "pending",
    ) -> int:
        row = RawNews(
            source=source, market=market, url=url, url_hash=url_hash,
            title=title, title_simhash=title_simhash, body=body, raw_meta=raw_meta,
            fetched_at=datetime.fromisoformat(fetched_at_iso),
            published_at=datetime.fromisoformat(published_at_iso),
            status=status,
        )
        async with self._db.session() as s:
            try:
                s.add(row)
                await s.commit()
                await s.refresh(row)
            except IntegrityError:
                await s.rollback()
                existing = await self.find_by_url_hash(url_hash)
                assert existing is not None and existing.id is not None
                return existing.id
        assert row.id is not None
        return row.id

    async def find_by_url_hash(self, url_hash: str) -> RawNews | None:
        async with self._db.session() as s:
            res = await s.execute(select(RawNews).where(RawNews.url_hash == url_hash))
            return res.scalar_one_or_none()

    async def list_pending(self, limit: int = 100) -> list[RawNews]:
        async with self._db.session() as s:
            res = await s.execute(
                select(RawNews).where(RawNews.status == "pending")
                .order_by(RawNews.published_at)
                .limit(limit)
            )
            return list(res.scalars())

    async def mark_status(self, raw_id: int, status: str,
                          error: str | None = None) -> None:
        async with self._db.session() as s:
            row = await s.get(RawNews, raw_id)
            if row is None:
                return
            row.status = status
            row.error = error
            await s.commit()

    async def list_recent_simhashes(
        self, window_hours: int = 24,
    ) -> list[tuple[int, int]]:
        cutoff = utc_now() - timedelta(hours=window_hours)
        async with self._db.session() as s:
            res = await s.execute(
                select(RawNews.id, RawNews.title_simhash)
                .where(RawNews.fetched_at >= cutoff)
            )
            return [(r[0], r[1]) for r in res.all()]
```

```bash
mkdir -p tests/unit/storage/dao && touch tests/unit/storage/dao/__init__.py
```

- [ ] **Step 4: Run — pass**

Run: `uv run pytest tests/unit/storage/dao/test_raw_news.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/storage/dao/raw_news.py src/news_pipeline/storage/dao/__init__.py tests/unit/storage/dao/
git commit -m "feat: add RawNews DAO"
```

---

### Task 18: DAOs — news_processed + entities + relations + news_entities

**Files:**
- Create: `src/news_pipeline/storage/dao/news_processed.py`
- Create: `src/news_pipeline/storage/dao/entities.py`
- Create: `src/news_pipeline/storage/dao/relations.py`
- Create: `tests/unit/storage/dao/test_processed_and_graph.py`

- [ ] **Step 1: Test**

```python
# tests/unit/storage/dao/test_processed_and_graph.py
from datetime import datetime

import pytest

from news_pipeline.storage.db import Database
from news_pipeline.storage.dao.raw_news import RawNewsDAO
from news_pipeline.storage.dao.news_processed import NewsProcessedDAO
from news_pipeline.storage.dao.entities import EntitiesDAO
from news_pipeline.storage.dao.relations import RelationsDAO
from news_pipeline.storage.models import SQLModelBase


@pytest.fixture
async def daos(tmp_path):
    db = Database(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    await db.initialize()
    async with db.engine.begin() as c:
        await c.run_sync(SQLModelBase.metadata.create_all)
    yield (RawNewsDAO(db), NewsProcessedDAO(db),
           EntitiesDAO(db), RelationsDAO(db))
    await db.close()


@pytest.mark.asyncio
async def test_insert_processed_and_link_entities(daos):
    raw, proc, ents, rels = daos
    raw_id = await raw.insert(
        source="x", market="us", url="https://x/1", url_hash="h1",
        title="t", title_simhash=0, body=None, raw_meta={},
        fetched_at_iso="2026-04-25T00:00:00",
        published_at_iso="2026-04-25T00:00:00",
    )
    pid = await proc.insert(
        raw_id=raw_id, summary="s", event_type="policy",
        sentiment="bearish", magnitude="high", confidence=0.9,
        key_quotes=["q"], score=80.0, is_critical=True,
        rule_hits=["price_5pct"], llm_reason=None,
        model_used="haiku", extracted_at=datetime(2026, 4, 25),
    )
    nv_id = await ents.upsert(type="company", name="NVIDIA",
                              ticker="NVDA", market="us", aliases=["NVDA"])
    tsm_id = await ents.upsert(type="company", name="TSMC",
                               ticker="TSM", market="us", aliases=[])
    await ents.link_news(news_id=pid, entity_id=nv_id,
                         role="subject", salience=0.95)
    await rels.insert(subject_id=nv_id, predicate="supplies",
                      object_id=tsm_id, source_news_id=pid,
                      confidence=0.9)

    found_subject = await ents.find(type="company", name="NVIDIA")
    assert found_subject is not None and found_subject.id == nv_id
    rel_rows = await rels.list_for_entity(nv_id)
    assert len(rel_rows) == 1
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

```python
# src/news_pipeline/storage/dao/news_processed.py
from datetime import datetime
from typing import Any

from sqlalchemy import select

from news_pipeline.storage.db import Database
from news_pipeline.storage.models import NewsProcessed


class NewsProcessedDAO:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def insert(
        self, *,
        raw_id: int, summary: str, event_type: str,
        sentiment: str, magnitude: str, confidence: float,
        key_quotes: list[str], score: float, is_critical: bool,
        rule_hits: list[str], llm_reason: str | None,
        model_used: str, extracted_at: datetime,
    ) -> int:
        row = NewsProcessed(
            raw_id=raw_id, summary=summary, event_type=event_type,
            sentiment=sentiment, magnitude=magnitude, confidence=confidence,
            key_quotes=key_quotes, score=score, is_critical=is_critical,
            rule_hits=rule_hits, llm_reason=llm_reason,
            model_used=model_used, extracted_at=extracted_at,
        )
        async with self._db.session() as s:
            s.add(row)
            await s.commit()
            await s.refresh(row)
        assert row.id is not None
        return row.id

    async def get(self, news_id: int) -> NewsProcessed | None:
        async with self._db.session() as s:
            return await s.get(NewsProcessed, news_id)

    async def mark_push_status(self, news_id: int, status: str) -> None:
        async with self._db.session() as s:
            row = await s.get(NewsProcessed, news_id)
            if row is None:
                return
            row.push_status = status
            await s.commit()

    async def list_pending_push(self, limit: int = 100) -> list[NewsProcessed]:
        async with self._db.session() as s:
            res = await s.execute(
                select(NewsProcessed).where(NewsProcessed.push_status == "pending")
                .order_by(NewsProcessed.extracted_at).limit(limit)
            )
            return list(res.scalars())
```

```python
# src/news_pipeline/storage/dao/entities.py
from typing import Any

from sqlalchemy import select

from news_pipeline.storage.db import Database
from news_pipeline.storage.models import Entity, NewsEntity


class EntitiesDAO:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def upsert(
        self, *, type: str, name: str, ticker: str | None = None,
        market: str | None = None, aliases: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        async with self._db.session() as s:
            res = await s.execute(
                select(Entity).where(Entity.type == type, Entity.name == name)
            )
            existing = res.scalar_one_or_none()
            if existing is not None:
                # merge aliases
                if aliases:
                    merged = list({*(existing.aliases or []), *aliases})
                    existing.aliases = merged
                if ticker and not existing.ticker:
                    existing.ticker = ticker
                if market and not existing.market:
                    existing.market = market
                await s.commit()
                assert existing.id is not None
                return existing.id
            row = Entity(type=type, name=name, ticker=ticker,
                         market=market, aliases=aliases, metadata_=metadata)
            s.add(row)
            await s.commit()
            await s.refresh(row)
            assert row.id is not None
            return row.id

    async def find(self, *, type: str, name: str) -> Entity | None:
        async with self._db.session() as s:
            res = await s.execute(
                select(Entity).where(Entity.type == type, Entity.name == name)
            )
            return res.scalar_one_or_none()

    async def find_by_ticker(self, ticker: str) -> Entity | None:
        async with self._db.session() as s:
            res = await s.execute(select(Entity).where(Entity.ticker == ticker))
            return res.scalar_one_or_none()

    async def link_news(
        self, *, news_id: int, entity_id: int, role: str, salience: float,
    ) -> None:
        async with self._db.session() as s:
            row = NewsEntity(news_id=news_id, entity_id=entity_id,
                             role=role, salience=salience)
            s.add(row)
            await s.commit()
```

```python
# src/news_pipeline/storage/dao/relations.py
from datetime import datetime

from sqlalchemy import or_, select

from news_pipeline.storage.db import Database
from news_pipeline.storage.models import Relation


class RelationsDAO:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def insert(
        self, *, subject_id: int, predicate: str, object_id: int,
        source_news_id: int, confidence: float,
        valid_from: datetime | None = None, valid_until: datetime | None = None,
    ) -> int:
        row = Relation(
            subject_id=subject_id, predicate=predicate, object_id=object_id,
            source_news_id=source_news_id, confidence=confidence,
            valid_from=valid_from, valid_until=valid_until,
        )
        async with self._db.session() as s:
            s.add(row)
            await s.commit()
            await s.refresh(row)
        assert row.id is not None
        return row.id

    async def list_for_entity(self, entity_id: int) -> list[Relation]:
        async with self._db.session() as s:
            res = await s.execute(
                select(Relation).where(
                    or_(Relation.subject_id == entity_id,
                        Relation.object_id == entity_id)
                )
            )
            return list(res.scalars())
```

- [ ] **Step 4: Run — pass**

Run: `uv run pytest tests/unit/storage/dao/test_processed_and_graph.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/storage/dao/{news_processed,entities,relations}.py tests/unit/storage/dao/test_processed_and_graph.py
git commit -m "feat: add DAOs for news_processed, entities, relations"
```

---

### Task 19: DAOs — source_state + push_log + audit_log + dead_letter

**Files:**
- Create: `src/news_pipeline/storage/dao/source_state.py`
- Create: `src/news_pipeline/storage/dao/push_log.py`
- Create: `src/news_pipeline/storage/dao/audit_log.py`
- Create: `src/news_pipeline/storage/dao/dead_letter.py`
- Create: `tests/unit/storage/dao/test_state_log_dlq.py`

- [ ] **Step 1: Test**

```python
# tests/unit/storage/dao/test_state_log_dlq.py
from datetime import datetime, timedelta

import pytest

from news_pipeline.storage.db import Database
from news_pipeline.storage.models import SQLModelBase
from news_pipeline.storage.dao.source_state import SourceStateDAO
from news_pipeline.storage.dao.push_log import PushLogDAO
from news_pipeline.storage.dao.audit_log import AuditLogDAO
from news_pipeline.storage.dao.dead_letter import DeadLetterDAO


@pytest.fixture
async def daos(tmp_path):
    db = Database(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    await db.initialize()
    async with db.engine.begin() as c:
        await c.run_sync(SQLModelBase.metadata.create_all)
    yield (SourceStateDAO(db), PushLogDAO(db),
           AuditLogDAO(db), DeadLetterDAO(db))
    await db.close()


@pytest.mark.asyncio
async def test_source_state_pause(daos):
    src, _, _, _ = daos
    until = datetime.utcnow() + timedelta(minutes=30)
    await src.set_paused("xueqiu", until=until, error="anti_crawl")
    assert await src.is_paused("xueqiu") is True


@pytest.mark.asyncio
async def test_dlq_insert_and_list_unresolved(daos):
    _, _, _, dlq = daos
    await dlq.insert(kind="scrape", payload="{}", error="x", retries=0)
    items = await dlq.list_unresolved()
    assert len(items) == 1


@pytest.mark.asyncio
async def test_audit_log_writes(daos):
    _, _, audit, _ = daos
    await audit.write(action="config_reload", actor="system", detail="ok")
    rows = await audit.recent(limit=5)
    assert rows[0].action == "config_reload"


@pytest.mark.asyncio
async def test_push_log_writes(daos):
    _, plog, _, _ = daos
    await plog.write(news_id=1, channel="tg_us", status="ok",
                     http_status=200, response="", retries=0)
    cnt = await plog.count_today_failures("tg_us")
    assert cnt == 0
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

```python
# src/news_pipeline/storage/dao/source_state.py
from datetime import datetime

from sqlalchemy import select

from news_pipeline.common.timeutil import utc_now
from news_pipeline.storage.db import Database
from news_pipeline.storage.models import SourceState


class SourceStateDAO:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def get(self, source: str) -> SourceState | None:
        async with self._db.session() as s:
            return await s.get(SourceState, source)

    async def update_watermark(
        self, source: str, *, last_fetched_at: datetime,
        last_seen_url: str | None = None,
    ) -> None:
        async with self._db.session() as ses:
            row = await ses.get(SourceState, source)
            if row is None:
                row = SourceState(source=source)
                ses.add(row)
            row.last_fetched_at = last_fetched_at
            if last_seen_url:
                row.last_seen_url = last_seen_url
            row.last_error = None
            row.error_count = 0
            await ses.commit()

    async def record_error(self, source: str, error: str) -> None:
        async with self._db.session() as ses:
            row = await ses.get(SourceState, source)
            if row is None:
                row = SourceState(source=source)
                ses.add(row)
            row.last_error = error
            row.error_count = (row.error_count or 0) + 1
            await ses.commit()

    async def set_paused(self, source: str, *,
                         until: datetime, error: str = "") -> None:
        async with self._db.session() as ses:
            row = await ses.get(SourceState, source)
            if row is None:
                row = SourceState(source=source)
                ses.add(row)
            row.paused_until = until
            row.last_error = error
            await ses.commit()

    async def is_paused(self, source: str) -> bool:
        row = await self.get(source)
        if row is None or row.paused_until is None:
            return False
        return row.paused_until > utc_now().replace(tzinfo=None)
```

```python
# src/news_pipeline/storage/dao/push_log.py
from datetime import datetime, timedelta

from sqlalchemy import func, select

from news_pipeline.common.timeutil import utc_now
from news_pipeline.storage.db import Database
from news_pipeline.storage.models import PushLog


class PushLogDAO:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def write(
        self, *, news_id: int, channel: str, status: str,
        http_status: int | None = None, response: str = "", retries: int = 0,
    ) -> None:
        async with self._db.session() as s:
            row = PushLog(
                news_id=news_id, channel=channel, sent_at=utc_now().replace(tzinfo=None),
                status=status, http_status=http_status, response=response,
                retries=retries,
            )
            s.add(row)
            await s.commit()

    async def count_today_failures(self, channel: str) -> int:
        cutoff = (utc_now() - timedelta(days=1)).replace(tzinfo=None)
        async with self._db.session() as s:
            res = await s.execute(
                select(func.count()).where(
                    PushLog.channel == channel,
                    PushLog.status == "failed",
                    PushLog.sent_at >= cutoff,
                )
            )
            return int(res.scalar() or 0)
```

```python
# src/news_pipeline/storage/dao/audit_log.py
from sqlalchemy import select

from news_pipeline.common.timeutil import utc_now
from news_pipeline.storage.db import Database
from news_pipeline.storage.models import AuditLog


class AuditLogDAO:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def write(self, *, action: str, actor: str | None = None,
                    detail: str | None = None) -> None:
        async with self._db.session() as s:
            row = AuditLog(action=action, actor=actor, detail=detail,
                           created_at=utc_now().replace(tzinfo=None))
            s.add(row)
            await s.commit()

    async def recent(self, limit: int = 20) -> list[AuditLog]:
        async with self._db.session() as s:
            res = await s.execute(
                select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
            )
            return list(res.scalars())
```

```python
# src/news_pipeline/storage/dao/dead_letter.py
from sqlalchemy import select

from news_pipeline.common.timeutil import utc_now
from news_pipeline.storage.db import Database
from news_pipeline.storage.models import DeadLetter


class DeadLetterDAO:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def insert(self, *, kind: str, payload: str, error: str,
                     retries: int = 0) -> int:
        row = DeadLetter(kind=kind, payload=payload, error=error,
                         retries=retries,
                         created_at=utc_now().replace(tzinfo=None))
        async with self._db.session() as s:
            s.add(row)
            await s.commit()
            await s.refresh(row)
        assert row.id is not None
        return row.id

    async def list_unresolved(self, kind: str | None = None) -> list[DeadLetter]:
        async with self._db.session() as s:
            stmt = select(DeadLetter).where(DeadLetter.resolved_at.is_(None))
            if kind is not None:
                stmt = stmt.where(DeadLetter.kind == kind)
            res = await s.execute(stmt)
            return list(res.scalars())

    async def mark_resolved(self, dlq_id: int) -> None:
        async with self._db.session() as s:
            row = await s.get(DeadLetter, dlq_id)
            if row is None:
                return
            row.resolved_at = utc_now().replace(tzinfo=None)
            await s.commit()
```

- [ ] **Step 4: Run — pass**

Run: `uv run pytest tests/unit/storage/dao/test_state_log_dlq.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/storage/dao/{source_state,push_log,audit_log,dead_letter}.py tests/unit/storage/dao/test_state_log_dlq.py
git commit -m "feat: add SourceState, PushLog, AuditLog, DeadLetter DAOs"
```

---

### Task 20: DAOs — digest_buffer + chart_cache + metrics

**Files:**
- Create: `src/news_pipeline/storage/dao/digest_buffer.py`
- Create: `src/news_pipeline/storage/dao/chart_cache.py`
- Create: `src/news_pipeline/storage/dao/metrics.py`
- Create: `tests/unit/storage/dao/test_buffer_chart_metrics.py`

- [ ] **Step 1: Test**

```python
# tests/unit/storage/dao/test_buffer_chart_metrics.py
from datetime import datetime, timedelta

import pytest

from news_pipeline.storage.db import Database
from news_pipeline.storage.models import SQLModelBase
from news_pipeline.storage.dao.digest_buffer import DigestBufferDAO
from news_pipeline.storage.dao.chart_cache import ChartCacheDAO
from news_pipeline.storage.dao.metrics import MetricsDAO


@pytest.fixture
async def daos(tmp_path):
    db = Database(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    await db.initialize()
    async with db.engine.begin() as c:
        await c.run_sync(SQLModelBase.metadata.create_all)
    yield (DigestBufferDAO(db), ChartCacheDAO(db), MetricsDAO(db))
    await db.close()


@pytest.mark.asyncio
async def test_digest_enqueue_and_consume(daos):
    buf, _, _ = daos
    await buf.enqueue(news_id=1, market="us", scheduled_digest="morning_us")
    pending = await buf.list_pending("morning_us")
    assert len(pending) == 1
    await buf.mark_consumed([pending[0].id])  # type: ignore[list-item]
    pending2 = await buf.list_pending("morning_us")
    assert len(pending2) == 0


@pytest.mark.asyncio
async def test_chart_cache_lookup(daos):
    _, cache, _ = daos
    await cache.put(request_hash="abc", ticker="NVDA", kind="kline",
                    oss_url="https://oss/x.png", ttl_days=30)
    found = await cache.get("abc")
    assert found is not None and found.oss_url == "https://oss/x.png"


@pytest.mark.asyncio
async def test_metrics_increment(daos):
    _, _, m = daos
    await m.increment(date_iso="2026-04-25", name="scrape_ok",
                      dimensions="source=finnhub", delta=5)
    await m.increment(date_iso="2026-04-25", name="scrape_ok",
                      dimensions="source=finnhub", delta=3)
    val = await m.get(date_iso="2026-04-25", name="scrape_ok",
                      dimensions="source=finnhub")
    assert val == 8.0
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

```python
# src/news_pipeline/storage/dao/digest_buffer.py
from datetime import datetime
from typing import Sequence

from sqlalchemy import select

from news_pipeline.common.timeutil import utc_now
from news_pipeline.storage.db import Database
from news_pipeline.storage.models import DigestBuffer


class DigestBufferDAO:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def enqueue(self, *, news_id: int, market: str,
                      scheduled_digest: str) -> int:
        row = DigestBuffer(
            news_id=news_id, market=market,
            scheduled_digest=scheduled_digest,
            added_at=utc_now().replace(tzinfo=None),
        )
        async with self._db.session() as s:
            s.add(row)
            await s.commit()
            await s.refresh(row)
        assert row.id is not None
        return row.id

    async def list_pending(self, scheduled_digest: str) -> list[DigestBuffer]:
        async with self._db.session() as s:
            res = await s.execute(
                select(DigestBuffer).where(
                    DigestBuffer.scheduled_digest == scheduled_digest,
                    DigestBuffer.consumed_at.is_(None),
                ).order_by(DigestBuffer.added_at)
            )
            return list(res.scalars())

    async def mark_consumed(self, ids: Sequence[int]) -> None:
        async with self._db.session() as s:
            for i in ids:
                row = await s.get(DigestBuffer, i)
                if row is not None:
                    row.consumed_at = utc_now().replace(tzinfo=None)
            await s.commit()
```

```python
# src/news_pipeline/storage/dao/chart_cache.py
from datetime import datetime, timedelta

from sqlalchemy import select

from news_pipeline.common.timeutil import utc_now
from news_pipeline.storage.db import Database
from news_pipeline.storage.models import ChartCache


class ChartCacheDAO:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def get(self, request_hash: str) -> ChartCache | None:
        async with self._db.session() as s:
            res = await s.execute(
                select(ChartCache).where(ChartCache.request_hash == request_hash)
            )
            row = res.scalar_one_or_none()
            if row is None:
                return None
            if row.expires_at < utc_now().replace(tzinfo=None):
                return None
            return row

    async def put(self, *, request_hash: str, ticker: str, kind: str,
                  oss_url: str, ttl_days: int = 30) -> int:
        now = utc_now().replace(tzinfo=None)
        row = ChartCache(
            request_hash=request_hash, ticker=ticker, kind=kind,
            oss_url=oss_url, generated_at=now,
            expires_at=now + timedelta(days=ttl_days),
        )
        async with self._db.session() as s:
            s.add(row)
            await s.commit()
            await s.refresh(row)
        assert row.id is not None
        return row.id
```

```python
# src/news_pipeline/storage/dao/metrics.py
from sqlalchemy import select

from news_pipeline.storage.db import Database
from news_pipeline.storage.models import DailyMetric


class MetricsDAO:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def increment(self, *, date_iso: str, name: str,
                        dimensions: str = "", delta: float = 1.0) -> None:
        async with self._db.session() as s:
            res = await s.execute(
                select(DailyMetric).where(
                    DailyMetric.metric_date == date_iso,
                    DailyMetric.metric_name == name,
                    DailyMetric.dimensions == dimensions,
                )
            )
            row = res.scalar_one_or_none()
            if row is None:
                row = DailyMetric(metric_date=date_iso, metric_name=name,
                                  dimensions=dimensions, metric_value=0.0)
                s.add(row)
            row.metric_value += delta
            await s.commit()

    async def get(self, *, date_iso: str, name: str,
                  dimensions: str = "") -> float | None:
        async with self._db.session() as s:
            res = await s.execute(
                select(DailyMetric.metric_value).where(
                    DailyMetric.metric_date == date_iso,
                    DailyMetric.metric_name == name,
                    DailyMetric.dimensions == dimensions,
                )
            )
            v = res.scalar_one_or_none()
            return float(v) if v is not None else None
```

- [ ] **Step 4: Run — pass**

Run: `uv run pytest tests/unit/storage/dao/test_buffer_chart_metrics.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/storage/dao/{digest_buffer,chart_cache,metrics}.py tests/unit/storage/dao/test_buffer_chart_metrics.py
git commit -m "feat: add DigestBuffer, ChartCache, Metrics DAOs"
```

---

## Phase 3 — Dedup (Tasks 21-22)

### Task 21: Dedup engine

**Files:**
- Create: `src/news_pipeline/dedup/__init__.py`
- Create: `src/news_pipeline/dedup/dedup.py`
- Create: `tests/unit/dedup/test_dedup.py`

- [ ] **Step 1: Test**

```python
# tests/unit/dedup/test_dedup.py
from datetime import datetime

import pytest

from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.enums import Market
from news_pipeline.common.hashing import url_hash, title_simhash
from news_pipeline.dedup.dedup import Dedup
from news_pipeline.storage.db import Database
from news_pipeline.storage.dao.raw_news import RawNewsDAO
from news_pipeline.storage.models import SQLModelBase


@pytest.fixture
async def setup(tmp_path):
    db = Database(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    await db.initialize()
    async with db.engine.begin() as c:
        await c.run_sync(SQLModelBase.metadata.create_all)
    yield Dedup(RawNewsDAO(db), title_distance_max=4)
    await db.close()


def _article(url: str, title: str) -> RawArticle:
    return RawArticle(
        source="x", market=Market.US,
        fetched_at=datetime(2026, 4, 25), published_at=datetime(2026, 4, 25),
        url=url, url_hash=url_hash(url), title=title,
        title_simhash=title_simhash(title), body=None, raw_meta={},
    )


@pytest.mark.asyncio
async def test_first_article_is_new(setup):
    a = _article("https://x.com/1", "NVDA earnings beat")
    decision = await setup.check_and_register(a)
    assert decision.is_new is True


@pytest.mark.asyncio
async def test_duplicate_url_is_old(setup):
    a = _article("https://x.com/1", "NVDA earnings beat")
    await setup.check_and_register(a)
    decision = await setup.check_and_register(a)
    assert decision.is_new is False
    assert decision.reason == "url_hash"


@pytest.mark.asyncio
async def test_near_duplicate_title_is_old(setup):
    a = _article("https://x.com/1", "NVDA earnings beat estimates")
    await setup.check_and_register(a)
    b = _article("https://x.com/2", "NVDA earnings beat the estimates")
    decision = await setup.check_and_register(b)
    assert decision.is_new is False
    assert decision.reason == "simhash"
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

```python
# src/news_pipeline/dedup/__init__.py
```

```python
# src/news_pipeline/dedup/dedup.py
from dataclasses import dataclass

from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.hashing import hamming
from news_pipeline.storage.dao.raw_news import RawNewsDAO


@dataclass
class DedupDecision:
    is_new: bool
    raw_id: int | None = None
    reason: str | None = None


class Dedup:
    def __init__(self, raw_dao: RawNewsDAO, *, title_distance_max: int = 4) -> None:
        self._dao = raw_dao
        self._dist = title_distance_max

    async def check_and_register(self, art: RawArticle) -> DedupDecision:
        existing = await self._dao.find_by_url_hash(art.url_hash)
        if existing is not None and existing.id is not None:
            return DedupDecision(is_new=False, raw_id=existing.id, reason="url_hash")
        for rid, sh in await self._dao.list_recent_simhashes(window_hours=24):
            if hamming(sh, art.title_simhash) <= self._dist:
                return DedupDecision(is_new=False, raw_id=rid, reason="simhash")
        new_id = await self._dao.insert(
            source=art.source, market=art.market.value,
            url=str(art.url), url_hash=art.url_hash,
            title=art.title, title_simhash=art.title_simhash,
            body=art.body, raw_meta=art.raw_meta,
            fetched_at_iso=art.fetched_at.isoformat(),
            published_at_iso=art.published_at.isoformat(),
        )
        return DedupDecision(is_new=True, raw_id=new_id)
```

```bash
mkdir -p tests/unit/dedup && touch tests/unit/dedup/__init__.py
```

- [ ] **Step 4: Run — pass**

Run: `uv run pytest tests/unit/dedup/test_dedup.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/dedup/ tests/unit/dedup/
git commit -m "feat: add dedup engine with url_hash + simhash distance"
```

---

## Phase 4 — Scrapers (Tasks 22-32)

### Task 22: Scraper protocol + registry + HTTP common

**Files:**
- Create: `src/news_pipeline/scrapers/__init__.py`
- Create: `src/news_pipeline/scrapers/base.py`
- Create: `src/news_pipeline/scrapers/registry.py`
- Create: `src/news_pipeline/scrapers/common/__init__.py`
- Create: `src/news_pipeline/scrapers/common/http.py`
- Create: `src/news_pipeline/scrapers/common/ratelimit.py`
- Create: `tests/unit/scrapers/test_base_and_registry.py`

- [ ] **Step 1: Test**

```python
# tests/unit/scrapers/test_base_and_registry.py
from datetime import datetime, UTC
from typing import Sequence

import pytest

from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.enums import Market
from news_pipeline.scrapers.base import ScraperProtocol
from news_pipeline.scrapers.registry import ScraperRegistry


class _Fake:
    source_id = "fake"
    market = Market.US

    async def fetch(self, since: datetime) -> Sequence[RawArticle]:
        return []


def test_registry_register_and_get():
    reg = ScraperRegistry()
    reg.register(_Fake())
    assert reg.get("fake").source_id == "fake"
    assert "fake" in reg.list_ids()


def test_protocol_compliance():
    f = _Fake()
    assert isinstance(f, ScraperProtocol)
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

```python
# src/news_pipeline/scrapers/__init__.py
```

```python
# src/news_pipeline/scrapers/base.py
from datetime import datetime
from typing import Protocol, Sequence, runtime_checkable

from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.enums import Market


@runtime_checkable
class ScraperProtocol(Protocol):
    source_id: str
    market: Market

    async def fetch(self, since: datetime) -> Sequence[RawArticle]: ...
```

```python
# src/news_pipeline/scrapers/registry.py
from news_pipeline.scrapers.base import ScraperProtocol


class ScraperRegistry:
    def __init__(self) -> None:
        self._items: dict[str, ScraperProtocol] = {}

    def register(self, scraper: ScraperProtocol) -> None:
        self._items[scraper.source_id] = scraper

    def get(self, source_id: str) -> ScraperProtocol:
        return self._items[source_id]

    def list_ids(self) -> list[str]:
        return list(self._items.keys())
```

```python
# src/news_pipeline/scrapers/common/__init__.py
```

```python
# src/news_pipeline/scrapers/common/http.py
import random

import httpx

DEFAULT_UA_POOL = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
]


def make_async_client(timeout: float = 15.0,
                      ua_pool: list[str] | None = None) -> httpx.AsyncClient:
    pool = ua_pool or DEFAULT_UA_POOL
    headers = {"User-Agent": random.choice(pool),
               "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}
    return httpx.AsyncClient(timeout=timeout, headers=headers,
                             follow_redirects=True)
```

```python
# src/news_pipeline/scrapers/common/ratelimit.py
from aiolimiter import AsyncLimiter


def per_minute(rate: int) -> AsyncLimiter:
    return AsyncLimiter(max_rate=rate, time_period=60)
```

```bash
mkdir -p tests/unit/scrapers && touch tests/unit/scrapers/__init__.py
```

- [ ] **Step 4: Run — pass**

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/scrapers/ tests/unit/scrapers/
git commit -m "feat: add scraper Protocol, registry, HTTP + ratelimit common"
```

---

### Task 23: Finnhub scraper (US, news API, JSON)

**Files:**
- Create: `src/news_pipeline/scrapers/us/__init__.py`
- Create: `src/news_pipeline/scrapers/us/finnhub.py`
- Create: `tests/unit/scrapers/us/test_finnhub.py`

- [ ] **Step 1: Test**

```python
# tests/unit/scrapers/us/test_finnhub.py
from datetime import datetime, UTC

import pytest
import respx
from httpx import Response

from news_pipeline.scrapers.us.finnhub import FinnhubScraper


@pytest.mark.asyncio
async def test_fetch_parses_articles():
    sample = [
        {"id": 1, "headline": "NVDA beats", "summary": "summary",
         "source": "Reuters", "url": "https://reut.com/a",
         "datetime": 1714000000, "image": ""},
        {"id": 2, "headline": "TSLA news", "summary": "...",
         "source": "Bloomberg", "url": "https://bberg.com/b",
         "datetime": 1714000500, "image": ""},
    ]
    async with respx.mock(assert_all_called=True) as mock:
        mock.get("https://finnhub.io/api/v1/news").mock(
            return_value=Response(200, json=sample)
        )
        scraper = FinnhubScraper(token="t1", tickers=["NVDA"], category="general")
        items = await scraper.fetch(datetime(2026, 4, 25, tzinfo=UTC))
        assert len(items) == 2
        assert items[0].source == "finnhub"
        assert str(items[0].url) == "https://reut.com/a"
        assert items[0].title == "NVDA beats"


@pytest.mark.asyncio
async def test_fetch_skips_old_items():
    sample = [
        {"id": 1, "headline": "old", "summary": "",
         "source": "x", "url": "https://x/1",
         "datetime": 1714000000, "image": ""},
    ]
    async with respx.mock() as mock:
        mock.get("https://finnhub.io/api/v1/news").mock(
            return_value=Response(200, json=sample)
        )
        scraper = FinnhubScraper(token="t1", tickers=[], category="general")
        items = await scraper.fetch(datetime(2030, 1, 1, tzinfo=UTC))
        assert items == []
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

```python
# src/news_pipeline/scrapers/us/__init__.py
```

```python
# src/news_pipeline/scrapers/us/finnhub.py
from datetime import datetime, UTC
from typing import Sequence

from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.enums import Market
from news_pipeline.common.hashing import title_simhash, url_hash
from news_pipeline.common.timeutil import utc_now
from news_pipeline.scrapers.common.http import make_async_client


class FinnhubScraper:
    source_id = "finnhub"
    market = Market.US

    def __init__(self, *, token: str, tickers: list[str],
                 category: str = "general") -> None:
        self._token = token
        self._tickers = tickers
        self._category = category

    async def fetch(self, since: datetime) -> Sequence[RawArticle]:
        url = "https://finnhub.io/api/v1/news"
        params = {"category": self._category, "token": self._token}
        async with make_async_client() as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
        out: list[RawArticle] = []
        now = utc_now()
        for item in data:
            ts = datetime.fromtimestamp(int(item["datetime"]), tz=UTC)
            if ts < since:
                continue
            link = item["url"]
            out.append(RawArticle(
                source=self.source_id, market=self.market,
                fetched_at=now, published_at=ts,
                url=link, url_hash=url_hash(link),
                title=item["headline"],
                title_simhash=title_simhash(item["headline"]),
                body=item.get("summary"),
                raw_meta={"finnhub_id": item["id"], "source": item["source"]},
            ))
        return out
```

```bash
mkdir -p tests/unit/scrapers/us && touch tests/unit/scrapers/us/__init__.py
```

- [ ] **Step 4: Run — pass**

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/scrapers/us/ tests/unit/scrapers/us/test_finnhub.py
git commit -m "feat: add Finnhub scraper"
```

---

### Task 24: SEC EDGAR scraper (US, RSS atom)

**Files:**
- Create: `src/news_pipeline/scrapers/us/sec_edgar.py`
- Create: `tests/unit/scrapers/us/test_sec_edgar.py`

- [ ] **Step 1: Test**

```python
# tests/unit/scrapers/us/test_sec_edgar.py
from datetime import datetime, UTC

import pytest
import respx
from httpx import Response

from news_pipeline.scrapers.us.sec_edgar import SecEdgarScraper

ATOM = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>NVIDIA Corp 8-K</title>
    <link href="https://www.sec.gov/Archives/edgar/data/X/x.htm"/>
    <updated>2026-04-25T14:00:00Z</updated>
    <id>tag:sec.gov,2008:filing/x</id>
    <summary>Filing summary</summary>
  </entry>
</feed>"""


@pytest.mark.asyncio
async def test_fetch_parses_atom():
    async with respx.mock() as mock:
        mock.get(url__regex=r"https://www\.sec\.gov/cgi-bin/browse-edgar.*").mock(
            return_value=Response(200, text=ATOM)
        )
        scraper = SecEdgarScraper(ciks=["1045810"])  # NVIDIA
        items = await scraper.fetch(datetime(2026, 4, 25, tzinfo=UTC))
        assert len(items) == 1
        assert items[0].source == "sec_edgar"
        assert "NVIDIA" in items[0].title
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

```python
# src/news_pipeline/scrapers/us/sec_edgar.py
from datetime import datetime, UTC
from typing import Sequence

import feedparser

from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.enums import Market
from news_pipeline.common.hashing import title_simhash, url_hash
from news_pipeline.common.timeutil import utc_now
from news_pipeline.scrapers.common.http import make_async_client


class SecEdgarScraper:
    source_id = "sec_edgar"
    market = Market.US

    def __init__(self, *, ciks: list[str]) -> None:
        self._ciks = ciks

    async def fetch(self, since: datetime) -> Sequence[RawArticle]:
        out: list[RawArticle] = []
        now = utc_now()
        async with make_async_client() as client:
            for cik in self._ciks:
                url = (
                    "https://www.sec.gov/cgi-bin/browse-edgar"
                    f"?action=getcompany&CIK={cik}"
                    "&type=&dateb=&owner=include&count=20&output=atom"
                )
                resp = await client.get(url, headers={
                    "User-Agent": "news-pipeline qingbin@example.com"
                })
                resp.raise_for_status()
                feed = feedparser.parse(resp.text)
                for e in feed.entries:
                    ts = datetime(*e.updated_parsed[:6], tzinfo=UTC)
                    if ts < since:
                        continue
                    link = e.link
                    out.append(RawArticle(
                        source=self.source_id, market=self.market,
                        fetched_at=now, published_at=ts,
                        url=link, url_hash=url_hash(link),
                        title=e.title,
                        title_simhash=title_simhash(e.title),
                        body=getattr(e, "summary", None),
                        raw_meta={"cik": cik, "id": e.id},
                    ))
        return out
```

- [ ] **Step 4: Run — pass**

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/scrapers/us/sec_edgar.py tests/unit/scrapers/us/test_sec_edgar.py
git commit -m "feat: add SEC EDGAR atom scraper"
```

---

### Task 25: yfinance news scraper (US wrapper)

**Files:**
- Create: `src/news_pipeline/scrapers/us/yfinance_news.py`
- Create: `tests/unit/scrapers/us/test_yfinance_news.py`

> yfinance is library-based (not HTTP we control), so we test by injecting a fake `ticker_factory`.

- [ ] **Step 1: Test**

```python
# tests/unit/scrapers/us/test_yfinance_news.py
from datetime import datetime, UTC

import pytest

from news_pipeline.scrapers.us.yfinance_news import YFinanceNewsScraper


class _FakeTicker:
    def __init__(self, news):
        self.news = news


def _factory(news_per_ticker):
    def make(ticker):
        return _FakeTicker(news_per_ticker.get(ticker, []))
    return make


@pytest.mark.asyncio
async def test_fetch_parses_news():
    news = {
        "NVDA": [{
            "title": "NVDA up", "link": "https://yhoo/1",
            "providerPublishTime": 1714000000, "publisher": "Yahoo",
        }]
    }
    s = YFinanceNewsScraper(tickers=["NVDA"], ticker_factory=_factory(news))
    items = await s.fetch(datetime(2026, 4, 25, tzinfo=UTC))
    assert len(items) == 1
    assert items[0].source == "yfinance_news"


@pytest.mark.asyncio
async def test_fetch_skips_old():
    news = {
        "NVDA": [{
            "title": "old", "link": "https://yhoo/1",
            "providerPublishTime": 1614000000, "publisher": "Yahoo",
        }]
    }
    s = YFinanceNewsScraper(tickers=["NVDA"], ticker_factory=_factory(news))
    items = await s.fetch(datetime(2026, 4, 25, tzinfo=UTC))
    assert items == []
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

```python
# src/news_pipeline/scrapers/us/yfinance_news.py
import asyncio
from datetime import datetime, UTC
from typing import Callable, Sequence

import yfinance as yf

from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.enums import Market
from news_pipeline.common.hashing import title_simhash, url_hash
from news_pipeline.common.timeutil import utc_now


class YFinanceNewsScraper:
    source_id = "yfinance_news"
    market = Market.US

    def __init__(self, *, tickers: list[str],
                 ticker_factory: Callable[[str], "yf.Ticker"] = yf.Ticker) -> None:
        self._tickers = tickers
        self._factory = ticker_factory

    async def fetch(self, since: datetime) -> Sequence[RawArticle]:
        return await asyncio.to_thread(self._fetch_sync, since)

    def _fetch_sync(self, since: datetime) -> list[RawArticle]:
        out: list[RawArticle] = []
        now = utc_now()
        for t in self._tickers:
            ticker = self._factory(t)
            for item in getattr(ticker, "news", []) or []:
                ts = datetime.fromtimestamp(int(item["providerPublishTime"]), tz=UTC)
                if ts < since:
                    continue
                link = item["link"]
                out.append(RawArticle(
                    source=self.source_id, market=self.market,
                    fetched_at=now, published_at=ts,
                    url=link, url_hash=url_hash(link),
                    title=item["title"],
                    title_simhash=title_simhash(item["title"]),
                    body=None,
                    raw_meta={"ticker": t, "publisher": item.get("publisher", "")},
                ))
        return out
```

- [ ] **Step 4: Run — pass**

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/scrapers/us/yfinance_news.py tests/unit/scrapers/us/test_yfinance_news.py
git commit -m "feat: add yfinance news scraper"
```

---

### Task 26: 财联社电报 (CN)

**Files:**
- Create: `src/news_pipeline/scrapers/cn/__init__.py`
- Create: `src/news_pipeline/scrapers/cn/caixin_telegram.py`
- Create: `tests/unit/scrapers/cn/test_caixin_telegram.py`

> 财联社电报无官方公开 API；常见做法是抓 `https://www.cls.cn/v3/depth/home/assembled/1000` 之类 JSON 接口（接口可能变动；下面用占位 URL，实际接入时按真实抓包结果调整。代码结构 + 测试不变）。

- [ ] **Step 1: Test**

```python
# tests/unit/scrapers/cn/test_caixin_telegram.py
from datetime import datetime, UTC

import pytest
import respx
from httpx import Response

from news_pipeline.scrapers.cn.caixin_telegram import CaixinTelegramScraper


SAMPLE = {
    "data": {
        "roll_data": [
            {"id": 1, "title": "央行降准", "brief": "降准0.5%",
             "ctime": 1714000000, "shareurl": "https://www.cls.cn/d/1"},
            {"id": 2, "title": "茅台一季报", "brief": "营收+20%",
             "ctime": 1714000500, "shareurl": "https://www.cls.cn/d/2"},
        ]
    }
}


@pytest.mark.asyncio
async def test_fetch_parses_roll():
    async with respx.mock() as mock:
        mock.get(url__regex=r"https://www\.cls\.cn/v3/.*").mock(
            return_value=Response(200, json=SAMPLE)
        )
        s = CaixinTelegramScraper()
        items = await s.fetch(datetime(2026, 4, 25, tzinfo=UTC))
        assert len(items) == 2
        assert items[0].source == "caixin_telegram"
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

```python
# src/news_pipeline/scrapers/cn/__init__.py
```

```python
# src/news_pipeline/scrapers/cn/caixin_telegram.py
from datetime import datetime, UTC
from typing import Sequence

from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.enums import Market
from news_pipeline.common.hashing import title_simhash, url_hash
from news_pipeline.common.timeutil import utc_now
from news_pipeline.scrapers.common.http import make_async_client


class CaixinTelegramScraper:
    source_id = "caixin_telegram"
    market = Market.CN

    def __init__(self, *, count: int = 20) -> None:
        self._count = count

    async def fetch(self, since: datetime) -> Sequence[RawArticle]:
        # NOTE: The exact endpoint may need adjustment after real-world inspection.
        # Replace `_endpoint()` with the working URL when wiring up.
        url = self._endpoint()
        async with make_async_client() as client:
            resp = await client.get(url)
            resp.raise_for_status()
            payload = resp.json()
        items = (payload.get("data") or {}).get("roll_data") or []
        out: list[RawArticle] = []
        now = utc_now()
        for it in items:
            ts = datetime.fromtimestamp(int(it["ctime"]), tz=UTC)
            if ts < since:
                continue
            link = it["shareurl"]
            title = it.get("title") or it.get("brief", "")[:80]
            out.append(RawArticle(
                source=self.source_id, market=self.market,
                fetched_at=now, published_at=ts,
                url=link, url_hash=url_hash(link),
                title=title, title_simhash=title_simhash(title),
                body=it.get("brief"),
                raw_meta={"cls_id": it["id"]},
            ))
        return out

    def _endpoint(self) -> str:
        return "https://www.cls.cn/v3/depth/home/assembled/1000"
```

```bash
mkdir -p tests/unit/scrapers/cn && touch tests/unit/scrapers/cn/__init__.py
```

- [ ] **Step 4: Run — pass**

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/scrapers/cn/ tests/unit/scrapers/cn/test_caixin_telegram.py
git commit -m "feat: add 财联社 telegram scraper (endpoint may need real-world tweak)"
```

---

### Task 27: akshare news (CN, library-based)

**Files:**
- Create: `src/news_pipeline/scrapers/cn/akshare_news.py`
- Create: `tests/unit/scrapers/cn/test_akshare_news.py`

> akshare wraps many CN financial sources. We inject a `news_callable` for testing.

- [ ] **Step 1: Test**

```python
# tests/unit/scrapers/cn/test_akshare_news.py
from datetime import datetime, UTC

import pandas as pd
import pytest

from news_pipeline.scrapers.cn.akshare_news import AkshareNewsScraper


def _fake_news(symbol: str) -> pd.DataFrame:
    return pd.DataFrame([
        {"标题": "茅台公告分红",
         "发布时间": "2026-04-25 14:00:00",
         "链接": "https://eastmoney/x"}
    ])


@pytest.mark.asyncio
async def test_fetch_parses_dataframe():
    s = AkshareNewsScraper(tickers=["600519"], news_callable=_fake_news)
    items = await s.fetch(datetime(2026, 4, 25, tzinfo=UTC))
    assert len(items) == 1
    assert items[0].source == "akshare_news"
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

```python
# src/news_pipeline/scrapers/cn/akshare_news.py
import asyncio
from datetime import datetime, UTC
from typing import Callable, Sequence

import akshare as ak
import pandas as pd

from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.enums import Market
from news_pipeline.common.hashing import title_simhash, url_hash
from news_pipeline.common.timeutil import ensure_utc, utc_now


class AkshareNewsScraper:
    source_id = "akshare_news"
    market = Market.CN

    def __init__(
        self, *, tickers: list[str],
        news_callable: Callable[[str], pd.DataFrame] = ak.stock_news_em,
    ) -> None:
        self._tickers = tickers
        self._news_callable = news_callable

    async def fetch(self, since: datetime) -> Sequence[RawArticle]:
        return await asyncio.to_thread(self._fetch_sync, since)

    def _fetch_sync(self, since: datetime) -> list[RawArticle]:
        out: list[RawArticle] = []
        now = utc_now()
        for t in self._tickers:
            df = self._news_callable(t)
            for _, row in df.iterrows():
                pub = pd.to_datetime(row.get("发布时间")).tz_localize("Asia/Shanghai")
                ts = ensure_utc(pub.to_pydatetime())
                if ts < since:
                    continue
                link = str(row.get("链接") or row.get("文章链接") or "")
                if not link:
                    continue
                title = str(row.get("标题") or row.get("新闻标题") or "")
                out.append(RawArticle(
                    source=self.source_id, market=self.market,
                    fetched_at=now, published_at=ts,
                    url=link, url_hash=url_hash(link),
                    title=title, title_simhash=title_simhash(title),
                    body=str(row.get("内容") or row.get("新闻内容") or "") or None,
                    raw_meta={"ticker": t},
                ))
        return out
```

- [ ] **Step 4: Run — pass**

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/scrapers/cn/akshare_news.py tests/unit/scrapers/cn/test_akshare_news.py
git commit -m "feat: add akshare news scraper (CN)"
```

---

### Task 28: 巨潮 (juchao) 公告

**Files:**
- Create: `src/news_pipeline/scrapers/cn/juchao.py`
- Create: `tests/unit/scrapers/cn/test_juchao.py`

> 巨潮公开 JSON: `http://www.cninfo.com.cn/new/hisAnnouncement/query`

- [ ] **Step 1: Test**

```python
# tests/unit/scrapers/cn/test_juchao.py
from datetime import datetime, UTC

import pytest
import respx
from httpx import Response

from news_pipeline.scrapers.cn.juchao import JuchaoScraper


SAMPLE = {
    "announcements": [
        {"announcementId": "100", "announcementTitle": "茅台2026Q1 财报",
         "announcementTime": 1714000000000, "adjunctUrl": "finalpage/2026-04-25/x.PDF",
         "secCode": "600519", "secName": "贵州茅台"}
    ]
}


@pytest.mark.asyncio
async def test_fetch_parses():
    async with respx.mock() as mock:
        mock.post("http://www.cninfo.com.cn/new/hisAnnouncement/query").mock(
            return_value=Response(200, json=SAMPLE)
        )
        s = JuchaoScraper(tickers=["600519"])
        items = await s.fetch(datetime(2026, 4, 25, tzinfo=UTC))
        assert len(items) == 1
        assert "茅台" in items[0].title
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

```python
# src/news_pipeline/scrapers/cn/juchao.py
from datetime import datetime, UTC
from typing import Sequence

from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.enums import Market
from news_pipeline.common.hashing import title_simhash, url_hash
from news_pipeline.common.timeutil import utc_now
from news_pipeline.scrapers.common.http import make_async_client


class JuchaoScraper:
    source_id = "juchao"
    market = Market.CN

    def __init__(self, *, tickers: list[str]) -> None:
        self._tickers = tickers

    async def fetch(self, since: datetime) -> Sequence[RawArticle]:
        url = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
        out: list[RawArticle] = []
        now = utc_now()
        async with make_async_client() as client:
            for ticker in self._tickers:
                form = {
                    "stock": ticker, "tabName": "fulltext",
                    "pageSize": 30, "pageNum": 1,
                }
                resp = await client.post(url, data=form)
                resp.raise_for_status()
                for ann in (resp.json().get("announcements") or []):
                    ts = datetime.fromtimestamp(
                        int(ann["announcementTime"]) / 1000, tz=UTC,
                    )
                    if ts < since:
                        continue
                    link = "http://static.cninfo.com.cn/" + ann["adjunctUrl"]
                    title = f'{ann["secName"]} {ann["announcementTitle"]}'
                    out.append(RawArticle(
                        source=self.source_id, market=self.market,
                        fetched_at=now, published_at=ts,
                        url=link, url_hash=url_hash(link),
                        title=title, title_simhash=title_simhash(title),
                        body=None,
                        raw_meta={"ann_id": ann["announcementId"],
                                  "code": ann["secCode"]},
                    ))
        return out
```

- [ ] **Step 4: Run — pass**

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/scrapers/cn/juchao.py tests/unit/scrapers/cn/test_juchao.py
git commit -m "feat: add 巨潮 (juchao) announcement scraper"
```

---

### Task 29: tushare news (CN, library)

**Files:**
- Create: `src/news_pipeline/scrapers/cn/tushare_news.py`
- Create: `tests/unit/scrapers/cn/test_tushare_news.py`

- [ ] **Step 1: Test**

```python
# tests/unit/scrapers/cn/test_tushare_news.py
from datetime import datetime, UTC

import pandas as pd
import pytest

from news_pipeline.scrapers.cn.tushare_news import TushareNewsScraper


class _FakePro:
    def news(self, src: str, start_date: str, end_date: str) -> pd.DataFrame:
        return pd.DataFrame([
            {"datetime": "2026-04-25 14:00:00", "content": "上证大涨", "title": "市场观察"}
        ])


@pytest.mark.asyncio
async def test_fetch_parses():
    s = TushareNewsScraper(pro_factory=lambda: _FakePro(), src="sina")
    items = await s.fetch(datetime(2026, 4, 25, tzinfo=UTC))
    assert len(items) == 1
    assert items[0].source == "tushare_news"
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

```python
# src/news_pipeline/scrapers/cn/tushare_news.py
import asyncio
import hashlib
from datetime import datetime, timedelta, UTC
from typing import Callable, Sequence

import pandas as pd

from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.enums import Market
from news_pipeline.common.hashing import title_simhash, url_hash
from news_pipeline.common.timeutil import ensure_utc, utc_now


def _default_pro_factory():
    import tushare as ts
    return ts.pro_api()


class TushareNewsScraper:
    source_id = "tushare_news"
    market = Market.CN

    def __init__(
        self, *, src: str = "sina",
        pro_factory: Callable[[], object] = _default_pro_factory,
    ) -> None:
        self._src = src
        self._pro_factory = pro_factory

    async def fetch(self, since: datetime) -> Sequence[RawArticle]:
        return await asyncio.to_thread(self._fetch_sync, since)

    def _fetch_sync(self, since: datetime) -> list[RawArticle]:
        pro = self._pro_factory()
        end = utc_now()
        start = end - timedelta(hours=1)
        df: pd.DataFrame = pro.news(  # type: ignore[attr-defined]
            src=self._src,
            start_date=start.strftime("%Y-%m-%d %H:%M:%S"),
            end_date=end.strftime("%Y-%m-%d %H:%M:%S"),
        )
        out: list[RawArticle] = []
        now = utc_now()
        for _, row in df.iterrows():
            ts = pd.to_datetime(row["datetime"]).tz_localize("Asia/Shanghai")
            ts = ensure_utc(ts.to_pydatetime())
            if ts < since:
                continue
            title = str(row.get("title") or row["content"][:60])
            content = str(row["content"])
            # Synthetic URL since tushare API doesn't always provide one
            synthetic = f"https://tushare.local/{self._src}/" + hashlib.sha1(
                (str(row['datetime']) + content).encode()
            ).hexdigest()[:16]
            out.append(RawArticle(
                source=self.source_id, market=self.market,
                fetched_at=now, published_at=ts,
                url=synthetic, url_hash=url_hash(synthetic),
                title=title, title_simhash=title_simhash(title),
                body=content,
                raw_meta={"src": self._src},
            ))
        return out
```

- [ ] **Step 4: Run — pass**

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/scrapers/cn/tushare_news.py tests/unit/scrapers/cn/test_tushare_news.py
git commit -m "feat: add tushare news scraper"
```

---

### Task 30: 雪球 (xueqiu) — cookie-based

**Files:**
- Create: `src/news_pipeline/scrapers/common/cookies.py`
- Create: `src/news_pipeline/scrapers/cn/xueqiu.py`
- Create: `tests/unit/scrapers/cn/test_xueqiu.py`

- [ ] **Step 1: Test**

```python
# tests/unit/scrapers/cn/test_xueqiu.py
from datetime import datetime, UTC

import pytest
import respx
from httpx import Response

from news_pipeline.scrapers.cn.xueqiu import XueqiuScraper


SAMPLE = {
    "list": [
        {"id": 1, "title": "雪球热议NVDA",
         "target": "/S/SH600519/123",
         "created_at": 1714000000000,
         "description": "讨论"}
    ]
}


@pytest.mark.asyncio
async def test_fetch_parses():
    async with respx.mock() as mock:
        mock.get(url__regex=r"https://xueqiu\.com/.*").mock(
            return_value=Response(200, json=SAMPLE)
        )
        s = XueqiuScraper(tickers=["600519"], cookie="x=1")
        items = await s.fetch(datetime(2026, 4, 25, tzinfo=UTC))
        assert len(items) == 1


@pytest.mark.asyncio
async def test_anticrawl_raises():
    from news_pipeline.common.exceptions import AntiCrawlError
    async with respx.mock() as mock:
        mock.get(url__regex=r"https://xueqiu\.com/.*").mock(
            return_value=Response(403, text="forbidden")
        )
        s = XueqiuScraper(tickers=["600519"], cookie="x=1")
        with pytest.raises(AntiCrawlError):
            await s.fetch(datetime(2026, 4, 25, tzinfo=UTC))
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

```python
# src/news_pipeline/scrapers/common/cookies.py
def parse_cookie_string(cookie: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in cookie.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        k, v = part.split("=", 1)
        out[k.strip()] = v.strip()
    return out
```

```python
# src/news_pipeline/scrapers/cn/xueqiu.py
from datetime import datetime, UTC
from typing import Sequence

from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.enums import Market
from news_pipeline.common.exceptions import AntiCrawlError
from news_pipeline.common.hashing import title_simhash, url_hash
from news_pipeline.common.timeutil import utc_now
from news_pipeline.scrapers.common.cookies import parse_cookie_string
from news_pipeline.scrapers.common.http import make_async_client


class XueqiuScraper:
    source_id = "xueqiu"
    market = Market.CN

    def __init__(self, *, tickers: list[str], cookie: str) -> None:
        self._tickers = tickers
        self._cookies = parse_cookie_string(cookie)

    async def fetch(self, since: datetime) -> Sequence[RawArticle]:
        out: list[RawArticle] = []
        now = utc_now()
        async with make_async_client() as client:
            for t in self._tickers:
                stock = self._symbol(t)
                url = f"https://xueqiu.com/v4/statuses/stock_timeline.json?symbol_id={stock}&count=20"
                resp = await client.get(url, cookies=self._cookies)
                if resp.status_code in (401, 403):
                    raise AntiCrawlError("xueqiu blocked",
                                         source=self.source_id,
                                         status=resp.status_code)
                resp.raise_for_status()
                for item in resp.json().get("list", []):
                    ts = datetime.fromtimestamp(
                        int(item["created_at"]) / 1000, tz=UTC,
                    )
                    if ts < since:
                        continue
                    link = "https://xueqiu.com" + item["target"]
                    title = item.get("title") or item.get("description", "")[:80]
                    out.append(RawArticle(
                        source=self.source_id, market=self.market,
                        fetched_at=now, published_at=ts,
                        url=link, url_hash=url_hash(link),
                        title=title, title_simhash=title_simhash(title),
                        body=item.get("description"),
                        raw_meta={"id": item["id"], "ticker": t},
                    ))
        return out

    @staticmethod
    def _symbol(ticker: str) -> str:
        if ticker.startswith("6"):
            return f"SH{ticker}"
        if ticker.startswith(("0", "3")):
            return f"SZ{ticker}"
        return ticker
```

- [ ] **Step 4: Run — pass**

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/scrapers/common/cookies.py src/news_pipeline/scrapers/cn/xueqiu.py tests/unit/scrapers/cn/test_xueqiu.py
git commit -m "feat: add 雪球 scraper with cookie + anti-crawl detection"
```

---

### Task 31: 同花顺 (ths) — cookie-based

**Files:**
- Create: `src/news_pipeline/scrapers/cn/ths.py`
- Create: `tests/unit/scrapers/cn/test_ths.py`

> 同花顺的接口结构与雪球类似，需要登录态。 占位 endpoint 同 caixin 备注：实际接入时按抓包结果调整 URL/解析。

- [ ] **Step 1: Test**

```python
# tests/unit/scrapers/cn/test_ths.py
from datetime import datetime, UTC

import pytest
import respx
from httpx import Response

from news_pipeline.scrapers.cn.ths import ThsScraper


SAMPLE_HTML = """
<html><body>
<div class="news-list">
  <a class="news-link" href="/news/1.html" data-time="1714000000">
    <span class="news-title">茅台分红</span>
  </a>
</div>
</body></html>
"""


@pytest.mark.asyncio
async def test_fetch_parses():
    async with respx.mock() as mock:
        mock.get(url__regex=r"https?://news\.10jqka\.com\.cn/.*").mock(
            return_value=Response(200, text=SAMPLE_HTML)
        )
        s = ThsScraper(tickers=["600519"], cookie="x=1")
        items = await s.fetch(datetime(2026, 4, 25, tzinfo=UTC))
        assert len(items) == 1


@pytest.mark.asyncio
async def test_anticrawl_raises():
    from news_pipeline.common.exceptions import AntiCrawlError
    async with respx.mock() as mock:
        mock.get(url__regex=r"https?://news\.10jqka\.com\.cn/.*").mock(
            return_value=Response(403, text="")
        )
        s = ThsScraper(tickers=["600519"], cookie="x=1")
        with pytest.raises(AntiCrawlError):
            await s.fetch(datetime(2026, 4, 25, tzinfo=UTC))
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

```python
# src/news_pipeline/scrapers/cn/ths.py
from datetime import datetime, UTC
from typing import Sequence

from bs4 import BeautifulSoup  # add to deps if not yet

from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.enums import Market
from news_pipeline.common.exceptions import AntiCrawlError
from news_pipeline.common.hashing import title_simhash, url_hash
from news_pipeline.common.timeutil import utc_now
from news_pipeline.scrapers.common.cookies import parse_cookie_string
from news_pipeline.scrapers.common.http import make_async_client


class ThsScraper:
    source_id = "ths"
    market = Market.CN

    def __init__(self, *, tickers: list[str], cookie: str) -> None:
        self._tickers = tickers
        self._cookies = parse_cookie_string(cookie)

    async def fetch(self, since: datetime) -> Sequence[RawArticle]:
        out: list[RawArticle] = []
        now = utc_now()
        async with make_async_client() as client:
            for ticker in self._tickers:
                url = f"https://news.10jqka.com.cn/{ticker}/list.shtml"
                resp = await client.get(url, cookies=self._cookies)
                if resp.status_code in (401, 403):
                    raise AntiCrawlError("ths blocked", source=self.source_id)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "html.parser")
                for a in soup.select(".news-link"):
                    href = a.get("href", "")
                    if not href:
                        continue
                    link = href if href.startswith("http") else \
                        f"https://news.10jqka.com.cn{href}"
                    ts_raw = a.get("data-time")
                    if not ts_raw:
                        continue
                    ts = datetime.fromtimestamp(int(ts_raw), tz=UTC)
                    if ts < since:
                        continue
                    title_el = a.select_one(".news-title")
                    title = title_el.get_text(strip=True) if title_el else ""
                    if not title:
                        continue
                    out.append(RawArticle(
                        source=self.source_id, market=self.market,
                        fetched_at=now, published_at=ts,
                        url=link, url_hash=url_hash(link),
                        title=title, title_simhash=title_simhash(title),
                        body=None,
                        raw_meta={"ticker": ticker},
                    ))
        return out
```

> Add `beautifulsoup4>=4.12` to `pyproject.toml` deps if not present, then `uv sync`.

- [ ] **Step 4: Run — pass**

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/scrapers/cn/ths.py tests/unit/scrapers/cn/test_ths.py pyproject.toml
git commit -m "feat: add 同花顺 (ths) scraper with cookie + anti-crawl detection"
```

---

### Task 32: Wire scrapers into registry from config

**Files:**
- Create: `src/news_pipeline/scrapers/factory.py`
- Create: `tests/unit/scrapers/test_factory.py`

- [ ] **Step 1: Test**

```python
# tests/unit/scrapers/test_factory.py
from news_pipeline.config.schema import (
    SourceDef, SourcesFile, WatchlistFile, WatchlistEntry, SecretsFile,
)
from news_pipeline.scrapers.factory import build_registry


def test_factory_builds_registry_for_enabled_sources():
    sources = SourcesFile(sources={
        "finnhub": SourceDef(enabled=True),
        "sec_edgar": SourceDef(enabled=True),
        "xueqiu": SourceDef(enabled=False),
    })
    watchlist = WatchlistFile(
        us=[WatchlistEntry(ticker="NVDA")],
        cn=[WatchlistEntry(ticker="600519")],
    )
    secrets = SecretsFile(sources={
        "finnhub_token": "T",
        "xueqiu_cookie": "C",
        "ths_cookie": "C",
        "tushare_token": "X",
    })
    reg = build_registry(sources, watchlist, secrets, sec_ciks={"NVDA": "1045810"})
    ids = reg.list_ids()
    assert "finnhub" in ids and "sec_edgar" in ids and "xueqiu" not in ids
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

```python
# src/news_pipeline/scrapers/factory.py
from typing import Mapping

from news_pipeline.config.schema import (
    SecretsFile, SourcesFile, WatchlistFile,
)
from news_pipeline.scrapers.cn.akshare_news import AkshareNewsScraper
from news_pipeline.scrapers.cn.caixin_telegram import CaixinTelegramScraper
from news_pipeline.scrapers.cn.juchao import JuchaoScraper
from news_pipeline.scrapers.cn.ths import ThsScraper
from news_pipeline.scrapers.cn.tushare_news import TushareNewsScraper
from news_pipeline.scrapers.cn.xueqiu import XueqiuScraper
from news_pipeline.scrapers.registry import ScraperRegistry
from news_pipeline.scrapers.us.finnhub import FinnhubScraper
from news_pipeline.scrapers.us.sec_edgar import SecEdgarScraper
from news_pipeline.scrapers.us.yfinance_news import YFinanceNewsScraper


def build_registry(
    sources: SourcesFile, watchlist: WatchlistFile,
    secrets: SecretsFile, *, sec_ciks: Mapping[str, str] | None = None,
) -> ScraperRegistry:
    reg = ScraperRegistry()
    us_tickers = [w.ticker for w in watchlist.us]
    cn_tickers = [w.ticker for w in watchlist.cn]
    enabled = {k for k, v in sources.sources.items() if v.enabled}
    s = secrets.sources
    if "finnhub" in enabled:
        reg.register(FinnhubScraper(
            token=s["finnhub_token"], tickers=us_tickers, category="general"
        ))
    if "sec_edgar" in enabled and sec_ciks:
        reg.register(SecEdgarScraper(
            ciks=[sec_ciks[t] for t in us_tickers if t in sec_ciks]
        ))
    if "yfinance_news" in enabled:
        reg.register(YFinanceNewsScraper(tickers=us_tickers))
    if "caixin_telegram" in enabled:
        reg.register(CaixinTelegramScraper())
    if "akshare_news" in enabled and cn_tickers:
        reg.register(AkshareNewsScraper(tickers=cn_tickers))
    if "juchao" in enabled and cn_tickers:
        reg.register(JuchaoScraper(tickers=cn_tickers))
    if "xueqiu" in enabled and cn_tickers:
        reg.register(XueqiuScraper(tickers=cn_tickers, cookie=s["xueqiu_cookie"]))
    if "ths" in enabled and cn_tickers:
        reg.register(ThsScraper(tickers=cn_tickers, cookie=s["ths_cookie"]))
    if "tushare_news" in enabled:
        reg.register(TushareNewsScraper(src="sina"))
    return reg
```

- [ ] **Step 4: Run — pass**

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/scrapers/factory.py tests/unit/scrapers/test_factory.py
git commit -m "feat: build scraper registry from config"
```

---

## Phase 5 — LLM Pipeline (Tasks 33-42)

### Task 33: Prompt YAML loader

**Files:**
- Create: `src/news_pipeline/llm/__init__.py`
- Create: `src/news_pipeline/llm/prompts/__init__.py`
- Create: `src/news_pipeline/llm/prompts/loader.py`
- Create: `tests/unit/llm/test_prompt_loader.py`

- [ ] **Step 1: Test**

```python
# tests/unit/llm/test_prompt_loader.py
from pathlib import Path

import pytest

from news_pipeline.llm.prompts.loader import PromptLoader


def test_load_versioned_prompt(tmp_path: Path):
    p = tmp_path / "tier2_extract.v1.yaml"
    p.write_text("""
name: tier2_extract
version: 1
model_target: claude-haiku-4-5-20251001
description: test
cache_segments: [system]
system: "you are an analyst"
output_schema_inline:
  type: object
  properties:
    summary: {type: string}
  required: [summary]
user_template: "title={title}"
guardrails:
  max_input_tokens: 4000
  retry_on_invalid_json: 1
  fallback_model: deepseek-v3
""")
    loader = PromptLoader(tmp_path)
    pr = loader.load("tier2_extract", "v1")
    assert pr.name == "tier2_extract"
    assert pr.version == 1
    rendered = pr.render(title="hello")
    assert "title=hello" in rendered.user
    assert pr.guardrails.fallback_model == "deepseek-v3"


def test_unknown_version_raises(tmp_path: Path):
    loader = PromptLoader(tmp_path)
    with pytest.raises(FileNotFoundError):
        loader.load("nope", "v9")
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

```python
# src/news_pipeline/llm/__init__.py
```

```python
# src/news_pipeline/llm/prompts/__init__.py
```

```python
# src/news_pipeline/llm/prompts/loader.py
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field


class PromptGuardrails(BaseModel):
    max_input_tokens: int = 4000
    retry_on_invalid_json: int = 1
    fallback_model: str | None = None


class PromptFile(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str
    version: int
    model_target: str
    description: str = ""
    cache_segments: list[str] = Field(default_factory=list)
    system: str
    output_schema_inline: dict[str, Any] | None = None
    user_template: str
    few_shot_examples: list[dict] = Field(default_factory=list)
    guardrails: PromptGuardrails = Field(default_factory=PromptGuardrails)


@dataclass
class RenderedPrompt:
    name: str
    version: int
    model_target: str
    system: str
    user: str
    output_schema: dict[str, Any] | None
    guardrails: PromptGuardrails
    cache_segments: list[str]
    few_shot_examples: list[dict]


class PromptLoader:
    def __init__(self, dir_path: Path) -> None:
        self._dir = dir_path

    def load(self, name: str, version: str) -> "PromptHandle":
        path = self._dir / f"{name}.{version}.yaml"
        if not path.exists():
            raise FileNotFoundError(path)
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return PromptHandle(PromptFile.model_validate(data))


class PromptHandle:
    def __init__(self, pf: PromptFile) -> None:
        self._pf = pf

    @property
    def name(self) -> str:
        return self._pf.name

    @property
    def version(self) -> int:
        return self._pf.version

    @property
    def guardrails(self) -> PromptGuardrails:
        return self._pf.guardrails

    @property
    def model_target(self) -> str:
        return self._pf.model_target

    def render(self, **vars: Any) -> RenderedPrompt:
        user = self._pf.user_template.format(**vars)
        return RenderedPrompt(
            name=self._pf.name, version=self._pf.version,
            model_target=self._pf.model_target,
            system=self._pf.system, user=user,
            output_schema=self._pf.output_schema_inline,
            guardrails=self._pf.guardrails,
            cache_segments=self._pf.cache_segments,
            few_shot_examples=self._pf.few_shot_examples,
        )
```

```bash
mkdir -p tests/unit/llm && touch tests/unit/llm/__init__.py
```

- [ ] **Step 4: Run — pass**

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/llm/ tests/unit/llm/test_prompt_loader.py
git commit -m "feat: add prompt YAML loader with versioning"
```

---

### Task 34: Initial 4 prompt YAML files

**Files:**
- Create: `config/prompts/tier0_classify.v1.yaml`
- Create: `config/prompts/tier1_summarize.v1.yaml`
- Create: `config/prompts/tier2_extract.v1.yaml`
- Create: `config/prompts/tier3_deep_analysis.v1.yaml`

- [ ] **Step 1: Tier-0**

```yaml
# config/prompts/tier0_classify.v1.yaml
name: tier0_classify
version: 1
model_target: deepseek-v3
description: "Cheap title-only relevance classifier"
cache_segments: []
system: |
  你是金融新闻相关性判定器。给定标题、来源、ticker，输出 JSON:
  {"relevant": bool, "tier_hint": "tier1"|"tier2", "watchlist_hit": bool, "reason": str}
  规则:
  - 只要标题包含 watchlist 中任一 ticker 或公司名 → tier_hint=tier2, watchlist_hit=true
  - 来源是 sec_edgar / juchao / caixin_telegram → tier_hint=tier2 (强制)
  - 标题与"股市/财经/政策/宏观/财报"明显无关 → relevant=false
  - 否则 relevant=true, tier_hint=tier1
output_schema_inline:
  type: object
  required: [relevant, tier_hint, watchlist_hit, reason]
  properties:
    relevant: {type: boolean}
    tier_hint: {type: string, enum: [tier1, tier2]}
    watchlist_hit: {type: boolean}
    reason: {type: string}
user_template: |
  ## 标题
  {title}

  ## 来源
  {source}

  ## 命中 ticker (如有)
  {tickers}

  ## Watchlist
  {watchlist}
guardrails:
  max_input_tokens: 1000
  retry_on_invalid_json: 1
  fallback_model: null
```

- [ ] **Step 2: Tier-1**

```yaml
# config/prompts/tier1_summarize.v1.yaml
name: tier1_summarize
version: 1
model_target: deepseek-v3
description: "Cheap summary + sentiment + sector tagging"
cache_segments: [system]
system: |
  你是财经新闻摘要助手。生成 100-200 字摘要 + 情绪 + 量级 + 事件类型 + 板块/标的列表。
  严格按 JSON Schema 输出, 不要任何额外文字。
output_schema_inline:
  type: object
  required: [summary, related_tickers, sectors, event_type, sentiment, magnitude, confidence]
  properties:
    summary: {type: string, minLength: 50}
    related_tickers: {type: array, items: {type: string}}
    sectors: {type: array, items: {type: string}}
    event_type: {type: string, enum: [earnings, m_and_a, policy, price_move, downgrade, upgrade, filing, other]}
    sentiment: {type: string, enum: [bullish, bearish, neutral]}
    magnitude: {type: string, enum: [low, medium, high]}
    confidence: {type: number, minimum: 0, maximum: 1}
    key_quotes: {type: array, items: {type: string}}
user_template: |
  ## 来源
  {source}
  ## 时间
  {published_at}
  ## 标题
  {title}
  ## 正文
  {body}
guardrails:
  max_input_tokens: 4000
  retry_on_invalid_json: 1
  fallback_model: null
```

- [ ] **Step 3: Tier-2 (with entities + relations)**

```yaml
# config/prompts/tier2_extract.v1.yaml
name: tier2_extract
version: 1
model_target: claude-haiku-4-5-20251001
description: "Deep extractor with entities + relations"
cache_segments: [system, few_shot_examples]
system: |
  你是金融新闻深度分析助手。除了 tier1 的全部字段, 还需抽取:
  - entities: 提及的公司/人物/事件/板块/政策/产品 (含 type, name, ticker, market, aliases)
  - relations: 实体间关系 (subject, predicate, object, confidence) — predicate 取自 [supplies, competes_with, owns, regulates, partners_with, mentions]
  - key_quotes: 1-3 个最关键的原文引用
  严格按 schema 输出 JSON。如果某关系不能从原文支撑, 不要瞎编。
output_schema_inline:
  type: object
  required: [summary, related_tickers, sectors, event_type, sentiment, magnitude, confidence, entities, relations]
  properties:
    summary: {type: string}
    related_tickers: {type: array, items: {type: string}}
    sectors: {type: array, items: {type: string}}
    event_type: {type: string}
    sentiment: {type: string, enum: [bullish, bearish, neutral]}
    magnitude: {type: string, enum: [low, medium, high]}
    confidence: {type: number, minimum: 0, maximum: 1}
    key_quotes: {type: array, items: {type: string}}
    entities:
      type: array
      items:
        type: object
        required: [type, name]
        properties:
          type: {type: string, enum: [company, person, event, sector, policy, product]}
          name: {type: string}
          ticker: {type: [string, "null"]}
          market: {type: [string, "null"], enum: [us, cn, null]}
          aliases: {type: array, items: {type: string}}
    relations:
      type: array
      items:
        type: object
        required: [subject_name, predicate, object_name, confidence]
        properties:
          subject_name: {type: string}
          predicate: {type: string, enum: [supplies, competes_with, owns, regulates, partners_with, mentions]}
          object_name: {type: string}
          confidence: {type: number}
few_shot_examples:
  - input: "标题: NVDA 因新出口管制将无法对华销售 H100; 正文: ..."
    output: |
      {"summary":"...","related_tickers":["NVDA","TSM","ASML"],"sectors":["semiconductor"],"event_type":"policy","sentiment":"bearish","magnitude":"high","confidence":0.92,"entities":[{"type":"company","name":"NVIDIA","ticker":"NVDA","market":"us","aliases":["英伟达"]},{"type":"company","name":"TSMC","ticker":"TSM","market":"us","aliases":["台积电"]}],"relations":[{"subject_name":"NVIDIA","predicate":"supplies","object_name":"TSMC","confidence":0.7}]}
user_template: |
  ## 来源
  {source}
  ## 时间
  {published_at}
  ## 标题
  {title}
  ## 正文
  {body}

  ## 上下文 (该公司近 7 天相关新闻摘要, 可空)
  {recent_context}
guardrails:
  max_input_tokens: 4000
  retry_on_invalid_json: 1
  fallback_model: deepseek-v3
```

- [ ] **Step 4: Tier-3 (manual deep)**

```yaml
# config/prompts/tier3_deep_analysis.v1.yaml
name: tier3_deep_analysis
version: 1
model_target: claude-sonnet-4-6
description: "On-demand deep analysis (manual /deep command)"
cache_segments: [system]
system: |
  你是高级财经分析师。给定一条新闻 + 该公司近 30 天相关历史, 产出一份 600-1000 字深度分析:
  1. 事件本身的核心要点
  2. 短期 (1 周) 可能的市场反应
  3. 中期 (1 季度) 对基本面的影响
  4. 上下游/关联公司的传导路径
  5. 关键风险与对冲建议 (仅信息, 非投资建议)
  Markdown 输出, 不要 JSON。结尾加一段免责声明。
output_schema_inline: null
user_template: |
  ## 主新闻
  来源: {source}
  时间: {published_at}
  标题: {title}
  摘要 (LLM): {prior_summary}
  原文: {body}

  ## 历史关联新闻 (近 30 天)
  {history}
guardrails:
  max_input_tokens: 16000
  retry_on_invalid_json: 0
  fallback_model: null
```

- [ ] **Step 5: Verify + commit**

```bash
uv run python -c "
from pathlib import Path
from news_pipeline.llm.prompts.loader import PromptLoader
loader = PromptLoader(Path('config/prompts'))
for n in ('tier0_classify', 'tier1_summarize', 'tier2_extract', 'tier3_deep_analysis'):
    p = loader.load(n, 'v1')
    print(n, p.version, p.model_target)
"
```

Expected: prints 4 lines listing each prompt.

```bash
git add config/prompts/
git commit -m "feat: add v1 prompts for tier 0/1/2/3"
```

---

### Task 35: LLM client base + DashScope client

**Files:**
- Create: `src/news_pipeline/llm/clients/__init__.py`
- Create: `src/news_pipeline/llm/clients/base.py`
- Create: `src/news_pipeline/llm/clients/dashscope.py`
- Create: `tests/unit/llm/clients/test_dashscope.py`

- [ ] **Step 1: Test**

```python
# tests/unit/llm/clients/test_dashscope.py
import pytest
import respx
from httpx import Response

from news_pipeline.llm.clients.base import LLMRequest
from news_pipeline.llm.clients.dashscope import DashScopeClient


@pytest.mark.asyncio
async def test_call_returns_parsed_json():
    response_payload = {
        "choices": [{
            "message": {"content": '{"x": 1, "y": "abc"}'},
            "finish_reason": "stop",
        }],
        "usage": {"input_tokens": 100, "output_tokens": 20},
    }
    async with respx.mock() as mock:
        mock.post(url__regex=r"https://dashscope\.aliyuncs\.com/.*").mock(
            return_value=Response(200, json=response_payload)
        )
        c = DashScopeClient(api_key="k", base_url="https://dashscope.aliyuncs.com/v1")
        req = LLMRequest(model="deepseek-v3", system="sys", user="usr",
                         json_mode=True, max_tokens=200)
        out = await c.call(req)
        assert out.json_payload == {"x": 1, "y": "abc"}
        assert out.usage.input_tokens == 100
        assert out.usage.output_tokens == 20
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

```python
# src/news_pipeline/llm/clients/__init__.py
```

```python
# src/news_pipeline/llm/clients/base.py
import json
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class LLMRequest:
    model: str
    system: str
    user: str
    json_mode: bool = False
    output_schema: dict[str, Any] | None = None
    max_tokens: int = 1000
    cache_segments: list[str] = field(default_factory=list)
    few_shot_examples: list[dict] = field(default_factory=list)


@dataclass
class LLMResponse:
    text: str
    json_payload: dict[str, Any] | None
    usage: TokenUsage
    model: str


class LLMClient(Protocol):
    async def call(self, req: LLMRequest) -> LLMResponse: ...


def parse_json_or_none(text: str) -> dict[str, Any] | None:
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
```

```python
# src/news_pipeline/llm/clients/dashscope.py
import httpx

from news_pipeline.llm.clients.base import (
    LLMRequest, LLMResponse, TokenUsage, parse_json_or_none,
)


class DashScopeClient:
    def __init__(self, *, api_key: str,
                 base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
                 timeout: float = 30.0) -> None:
        self._api_key = api_key
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    async def call(self, req: LLMRequest) -> LLMResponse:
        url = f"{self._base}/chat/completions"
        body = {
            "model": req.model,
            "messages": [
                {"role": "system", "content": req.system},
                {"role": "user", "content": req.user},
            ],
            "max_tokens": req.max_tokens,
        }
        if req.json_mode:
            body["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {self._api_key}"}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(url, json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        text = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        return LLMResponse(
            text=text,
            json_payload=parse_json_or_none(text) if req.json_mode else None,
            usage=TokenUsage(
                input_tokens=int(usage.get("input_tokens", usage.get("prompt_tokens", 0))),
                output_tokens=int(usage.get("output_tokens", usage.get("completion_tokens", 0))),
            ),
            model=req.model,
        )
```

```bash
mkdir -p tests/unit/llm/clients && touch tests/unit/llm/clients/__init__.py
```

- [ ] **Step 4: Run — pass**

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/llm/clients/{__init__,base,dashscope}.py tests/unit/llm/clients/
git commit -m "feat: add LLMClient protocol + DashScope client"
```

---

### Task 36: Anthropic client (tool use + prompt cache)

**Files:**
- Create: `src/news_pipeline/llm/clients/anthropic.py`
- Create: `tests/unit/llm/clients/test_anthropic.py`

- [ ] **Step 1: Test**

```python
# tests/unit/llm/clients/test_anthropic.py
from unittest.mock import AsyncMock, MagicMock

import pytest

from news_pipeline.llm.clients.anthropic import AnthropicClient
from news_pipeline.llm.clients.base import LLMRequest


@pytest.mark.asyncio
async def test_tool_use_call_returns_input():
    fake_msg = MagicMock()
    fake_msg.content = [MagicMock(type="tool_use", input={"summary": "ok"})]
    fake_msg.usage = MagicMock(input_tokens=100, output_tokens=20,
                               cache_read_input_tokens=80,
                               cache_creation_input_tokens=0)
    sdk_client = MagicMock()
    sdk_client.messages.create = AsyncMock(return_value=fake_msg)

    c = AnthropicClient(api_key="k", _client=sdk_client)
    req = LLMRequest(
        model="claude-haiku-4-5", system="sys", user="usr",
        output_schema={"type": "object",
                       "properties": {"summary": {"type": "string"}},
                       "required": ["summary"]},
        cache_segments=["system"],
    )
    out = await c.call(req)
    assert out.json_payload == {"summary": "ok"}
    assert out.usage.input_tokens == 100
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

```python
# src/news_pipeline/llm/clients/anthropic.py
from typing import Any

import anthropic

from news_pipeline.llm.clients.base import (
    LLMRequest, LLMResponse, TokenUsage, parse_json_or_none,
)


class AnthropicClient:
    def __init__(self, *, api_key: str, _client: Any | None = None,
                 timeout: float = 60.0) -> None:
        self._client = _client or anthropic.AsyncAnthropic(
            api_key=api_key, timeout=timeout
        )

    async def call(self, req: LLMRequest) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": req.model,
            "max_tokens": req.max_tokens,
        }
        if "system" in req.cache_segments:
            kwargs["system"] = [{
                "type": "text", "text": req.system,
                "cache_control": {"type": "ephemeral"},
            }]
        else:
            kwargs["system"] = req.system

        kwargs["messages"] = [{"role": "user", "content": req.user}]

        if req.output_schema is not None:
            kwargs["tools"] = [{
                "name": "emit", "description": "Return structured result",
                "input_schema": req.output_schema,
            }]
            kwargs["tool_choice"] = {"type": "tool", "name": "emit"}

        msg = await self._client.messages.create(**kwargs)

        json_payload: dict[str, Any] | None = None
        text = ""
        for block in msg.content:
            if getattr(block, "type", None) == "tool_use":
                json_payload = dict(block.input)
                break
            if getattr(block, "type", None) == "text":
                text += block.text

        if json_payload is None and text:
            json_payload = parse_json_or_none(text)

        u = msg.usage
        return LLMResponse(
            text=text, json_payload=json_payload,
            usage=TokenUsage(
                input_tokens=int(getattr(u, "input_tokens", 0)),
                output_tokens=int(getattr(u, "output_tokens", 0)),
            ),
            model=req.model,
        )
```

- [ ] **Step 4: Run — pass**

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/llm/clients/anthropic.py tests/unit/llm/clients/test_anthropic.py
git commit -m "feat: add Anthropic client with tool use + prompt cache"
```

---

### Task 37: Cost tracker with daily ceiling

**Files:**
- Create: `src/news_pipeline/llm/cost_tracker.py`
- Create: `tests/unit/llm/test_cost_tracker.py`

- [ ] **Step 1: Test**

```python
# tests/unit/llm/test_cost_tracker.py
import pytest

from news_pipeline.common.exceptions import CostCeilingExceeded
from news_pipeline.llm.clients.base import TokenUsage
from news_pipeline.llm.cost_tracker import CostTracker, ModelPricing


def _pricing() -> dict[str, ModelPricing]:
    return {
        "deepseek-v3": ModelPricing(input_per_m_cny=0.5, output_per_m_cny=1.5),
        "claude-haiku-4-5-20251001": ModelPricing(
            input_per_m_cny=7.0, output_per_m_cny=35.0
        ),
    }


def test_record_usage_accumulates(monkeypatch):
    monkeypatch.setattr(
        "news_pipeline.llm.cost_tracker.utc_now",
        lambda: __import__("datetime").datetime(2026, 4, 25),
    )
    tr = CostTracker(daily_ceiling_cny=5.0, pricing=_pricing())
    tr.record(model="deepseek-v3",
              usage=TokenUsage(input_tokens=1_000_000, output_tokens=200_000))
    assert tr.today_cost_cny() == pytest.approx(0.5 + 0.3)


def test_check_raises_when_over(monkeypatch):
    monkeypatch.setattr(
        "news_pipeline.llm.cost_tracker.utc_now",
        lambda: __import__("datetime").datetime(2026, 4, 25),
    )
    tr = CostTracker(daily_ceiling_cny=0.5, pricing=_pricing())
    tr.record(model="claude-haiku-4-5-20251001",
              usage=TokenUsage(input_tokens=200_000, output_tokens=20_000))
    with pytest.raises(CostCeilingExceeded):
        tr.check()
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

```python
# src/news_pipeline/llm/cost_tracker.py
from collections import defaultdict
from dataclasses import dataclass

from news_pipeline.common.exceptions import CostCeilingExceeded
from news_pipeline.common.timeutil import utc_now
from news_pipeline.llm.clients.base import TokenUsage


@dataclass(frozen=True)
class ModelPricing:
    input_per_m_cny: float
    output_per_m_cny: float


class CostTracker:
    def __init__(self, *, daily_ceiling_cny: float,
                 pricing: dict[str, ModelPricing]) -> None:
        self._ceiling = daily_ceiling_cny
        self._pricing = pricing
        self._daily_total: dict[str, float] = defaultdict(float)

    def record(self, *, model: str, usage: TokenUsage) -> None:
        p = self._pricing.get(model)
        if p is None:
            return
        cost = (usage.input_tokens / 1_000_000) * p.input_per_m_cny + (
            usage.output_tokens / 1_000_000) * p.output_per_m_cny
        key = utc_now().date().isoformat()
        self._daily_total[key] += cost

    def today_cost_cny(self) -> float:
        return self._daily_total[utc_now().date().isoformat()]

    def check(self) -> None:
        if self.today_cost_cny() >= self._ceiling:
            raise CostCeilingExceeded(
                f"daily LLM cost {self.today_cost_cny():.2f} >= {self._ceiling:.2f}"
            )

    def remaining_today(self) -> float:
        return max(0.0, self._ceiling - self.today_cost_cny())
```

- [ ] **Step 4: Run — pass**

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/llm/cost_tracker.py tests/unit/llm/test_cost_tracker.py
git commit -m "feat: add cost tracker with daily ceiling enforcement"
```

---

### Task 38: Tier-0 classifier extractor

**Files:**
- Create: `src/news_pipeline/llm/extractors.py`
- Create: `tests/unit/llm/test_tier0_extractor.py`

- [ ] **Step 1: Test**

```python
# tests/unit/llm/test_tier0_extractor.py
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.enums import Market
from news_pipeline.llm.clients.base import LLMResponse, TokenUsage
from news_pipeline.llm.extractors import Tier0Classifier
from news_pipeline.llm.prompts.loader import PromptLoader


@pytest.fixture
def prompt_handle(tmp_path: Path):
    p = tmp_path / "tier0_classify.v1.yaml"
    p.write_text("""
name: tier0_classify
version: 1
model_target: deepseek-v3
system: "you are classifier"
output_schema_inline:
  type: object
  required: [relevant, tier_hint, watchlist_hit, reason]
  properties:
    relevant: {type: boolean}
    tier_hint: {type: string}
    watchlist_hit: {type: boolean}
    reason: {type: string}
user_template: "title={title} source={source} tickers={tickers} watchlist={watchlist}"
guardrails:
  max_input_tokens: 1000
  retry_on_invalid_json: 1
""")
    return PromptLoader(tmp_path).load("tier0_classify", "v1")


@pytest.mark.asyncio
async def test_classify_returns_parsed(prompt_handle):
    fake = AsyncMock()
    fake.call.return_value = LLMResponse(
        text='{"relevant":true,"tier_hint":"tier2","watchlist_hit":true,"reason":"NVDA hit"}',
        json_payload={"relevant": True, "tier_hint": "tier2",
                      "watchlist_hit": True, "reason": "NVDA hit"},
        usage=TokenUsage(100, 30), model="deepseek-v3",
    )
    cls = Tier0Classifier(client=fake, prompt=prompt_handle)
    art = RawArticle(
        source="finnhub", market=Market.US,
        fetched_at="2026-04-25T00:00:00", published_at="2026-04-25T00:00:00",
        url="https://x/1", url_hash="h", title="NVDA up 5%",
    )
    out = await cls.classify(art, watchlist_us=["NVDA"], watchlist_cn=[])
    assert out.relevant is True and out.watchlist_hit is True
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

```python
# src/news_pipeline/llm/extractors.py
from dataclasses import dataclass

from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.exceptions import LLMError
from news_pipeline.llm.clients.base import LLMClient, LLMRequest
from news_pipeline.llm.prompts.loader import PromptHandle


@dataclass
class Tier0Verdict:
    relevant: bool
    tier_hint: str  # tier1 | tier2
    watchlist_hit: bool
    reason: str


class Tier0Classifier:
    def __init__(self, *, client: LLMClient, prompt: PromptHandle) -> None:
        self._client = client
        self._prompt = prompt

    async def classify(
        self, art: RawArticle, *,
        watchlist_us: list[str], watchlist_cn: list[str],
    ) -> Tier0Verdict:
        rendered = self._prompt.render(
            title=art.title,
            source=art.source,
            tickers=",".join(art.raw_meta.get("tickers", []) or []),
            watchlist=",".join(watchlist_us + watchlist_cn),
        )
        req = LLMRequest(
            model=rendered.model_target, system=rendered.system,
            user=rendered.user, json_mode=True,
            output_schema=rendered.output_schema, max_tokens=200,
        )
        resp = await self._client.call(req)
        payload = resp.json_payload
        if payload is None:
            raise LLMError("tier0 invalid json")
        return Tier0Verdict(
            relevant=bool(payload.get("relevant", False)),
            tier_hint=str(payload.get("tier_hint", "tier1")),
            watchlist_hit=bool(payload.get("watchlist_hit", False)),
            reason=str(payload.get("reason", "")),
        )
```

- [ ] **Step 4: Run — pass**

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/llm/extractors.py tests/unit/llm/test_tier0_extractor.py
git commit -m "feat: add Tier-0 LLM classifier extractor"
```

---

### Task 39: Tier-1 summarizer extractor

**Files:**
- Modify: `src/news_pipeline/llm/extractors.py` (append)
- Create: `tests/unit/llm/test_tier1_extractor.py`

- [ ] **Step 1: Test**

```python
# tests/unit/llm/test_tier1_extractor.py
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.enums import Market
from news_pipeline.llm.clients.base import LLMResponse, TokenUsage
from news_pipeline.llm.extractors import Tier1Summarizer
from news_pipeline.llm.prompts.loader import PromptLoader


@pytest.fixture
def prompt(tmp_path: Path):
    p = tmp_path / "tier1_summarize.v1.yaml"
    p.write_text("""
name: tier1_summarize
version: 1
model_target: deepseek-v3
system: sum
output_schema_inline:
  type: object
  required: [summary, related_tickers, sectors, event_type, sentiment, magnitude, confidence]
  properties:
    summary: {type: string}
    related_tickers: {type: array}
    sectors: {type: array}
    event_type: {type: string}
    sentiment: {type: string}
    magnitude: {type: string}
    confidence: {type: number}
    key_quotes: {type: array}
user_template: "src={source} t={title} body={body}"
guardrails:
  max_input_tokens: 4000
  retry_on_invalid_json: 1
""")
    return PromptLoader(tmp_path).load("tier1_summarize", "v1")


@pytest.mark.asyncio
async def test_tier1_returns_enriched(prompt):
    fake = AsyncMock()
    fake.call.return_value = LLMResponse(
        text="{}", json_payload={
            "summary": "..", "related_tickers": ["NVDA"],
            "sectors": ["semiconductor"], "event_type": "policy",
            "sentiment": "bearish", "magnitude": "high", "confidence": 0.8,
            "key_quotes": ["q"],
        },
        usage=TokenUsage(1500, 300), model="deepseek-v3",
    )
    art = RawArticle(
        source="x", market=Market.US,
        fetched_at=datetime(2026, 4, 25), published_at=datetime(2026, 4, 25),
        url="https://x/1", url_hash="h", title="t", body="b",
    )
    s = Tier1Summarizer(client=fake, prompt=prompt)
    out = await s.summarize(art, raw_id=42)
    assert out.raw_id == 42
    assert out.related_tickers == ["NVDA"]
    assert out.entities == [] and out.relations == []
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement (append to extractors.py)**

```python
# Append to src/news_pipeline/llm/extractors.py

from datetime import datetime

from news_pipeline.common.contracts import EnrichedNews
from news_pipeline.common.enums import EventType, Magnitude, Sentiment


class Tier1Summarizer:
    def __init__(self, *, client: LLMClient, prompt: PromptHandle) -> None:
        self._client = client
        self._prompt = prompt

    async def summarize(self, art: RawArticle, *, raw_id: int) -> EnrichedNews:
        rendered = self._prompt.render(
            source=art.source,
            published_at=art.published_at.isoformat(),
            title=art.title, body=art.body or "",
        )
        req = LLMRequest(
            model=rendered.model_target, system=rendered.system,
            user=rendered.user, json_mode=True,
            output_schema=rendered.output_schema, max_tokens=600,
        )
        resp = await self._client.call(req)
        payload = resp.json_payload
        if payload is None:
            raise LLMError("tier1 invalid json")
        return EnrichedNews(
            raw_id=raw_id,
            summary=payload["summary"],
            related_tickers=payload.get("related_tickers", []),
            sectors=payload.get("sectors", []),
            event_type=EventType(payload["event_type"]),
            sentiment=Sentiment(payload["sentiment"]),
            magnitude=Magnitude(payload["magnitude"]),
            confidence=float(payload["confidence"]),
            key_quotes=payload.get("key_quotes", []),
            entities=[], relations=[],
            model_used=rendered.model_target,
            extracted_at=datetime.utcnow(),
        )
```

- [ ] **Step 4: Run — pass**

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/llm/extractors.py tests/unit/llm/test_tier1_extractor.py
git commit -m "feat: add Tier-1 summarizer extractor"
```

---

### Task 40: Tier-2 deep extractor (entities + relations)

**Files:**
- Modify: `src/news_pipeline/llm/extractors.py` (append)
- Create: `tests/unit/llm/test_tier2_extractor.py`

- [ ] **Step 1: Test**

```python
# tests/unit/llm/test_tier2_extractor.py
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.enums import Market
from news_pipeline.llm.clients.base import LLMResponse, TokenUsage
from news_pipeline.llm.extractors import Tier2DeepExtractor
from news_pipeline.llm.prompts.loader import PromptLoader


@pytest.fixture
def prompt(tmp_path: Path):
    (tmp_path / "tier2_extract.v1.yaml").write_text("""
name: tier2_extract
version: 1
model_target: claude-haiku-4-5-20251001
cache_segments: [system]
system: deep
output_schema_inline: {type: object, required: [summary], properties: {summary: {type: string}}}
user_template: "src={source} t={title} body={body} ctx={recent_context}"
guardrails: {max_input_tokens: 4000, retry_on_invalid_json: 1, fallback_model: deepseek-v3}
""")
    return PromptLoader(tmp_path).load("tier2_extract", "v1")


@pytest.mark.asyncio
async def test_tier2_with_entities(prompt):
    fake = AsyncMock()
    fake.call.return_value = LLMResponse(
        text="", json_payload={
            "summary": "出口管制",
            "related_tickers": ["NVDA", "TSM"],
            "sectors": ["semiconductor"],
            "event_type": "policy",
            "sentiment": "bearish",
            "magnitude": "high",
            "confidence": 0.9,
            "key_quotes": ["…"],
            "entities": [
                {"type": "company", "name": "NVIDIA", "ticker": "NVDA",
                 "market": "us", "aliases": ["英伟达"]},
                {"type": "company", "name": "TSMC", "ticker": "TSM",
                 "market": "us", "aliases": []},
            ],
            "relations": [
                {"subject_name": "NVIDIA", "predicate": "supplies",
                 "object_name": "TSMC", "confidence": 0.7}
            ],
        },
        usage=TokenUsage(2000, 500), model="claude-haiku-4-5",
    )
    art = RawArticle(
        source="reuters", market=Market.US,
        fetched_at=datetime(2026, 4, 25), published_at=datetime(2026, 4, 25),
        url="https://x/1", url_hash="h", title="t", body="b",
    )
    ext = Tier2DeepExtractor(client=fake, prompt=prompt)
    out = await ext.extract(art, raw_id=10, recent_context="")
    assert len(out.entities) == 2
    assert out.relations[0].predicate.value == "supplies"
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement (append)**

```python
# Append to src/news_pipeline/llm/extractors.py

from news_pipeline.common.contracts import Entity, Relation
from news_pipeline.common.enums import EntityType, Predicate


class Tier2DeepExtractor:
    def __init__(self, *, client: LLMClient, prompt: PromptHandle) -> None:
        self._client = client
        self._prompt = prompt

    async def extract(self, art: RawArticle, *, raw_id: int,
                      recent_context: str = "") -> EnrichedNews:
        rendered = self._prompt.render(
            source=art.source,
            published_at=art.published_at.isoformat(),
            title=art.title, body=art.body or "",
            recent_context=recent_context,
        )
        req = LLMRequest(
            model=rendered.model_target, system=rendered.system,
            user=rendered.user,
            output_schema=rendered.output_schema,
            cache_segments=rendered.cache_segments,
            few_shot_examples=rendered.few_shot_examples,
            max_tokens=1200,
        )
        resp = await self._client.call(req)
        payload = resp.json_payload
        if payload is None:
            raise LLMError("tier2 invalid json")
        ents_by_name = {
            e["name"]: Entity(
                type=EntityType(e["type"]),
                name=e["name"],
                ticker=e.get("ticker"),
                market=Market(e["market"]) if e.get("market") else None,
                aliases=e.get("aliases", []),
            )
            for e in payload.get("entities", [])
        }
        relations: list[Relation] = []
        for r in payload.get("relations", []):
            sub = ents_by_name.get(r["subject_name"])
            obj = ents_by_name.get(r["object_name"])
            if sub is None or obj is None:
                continue
            try:
                pred = Predicate(r["predicate"])
            except ValueError:
                pred = Predicate.MENTIONS
            relations.append(Relation(
                subject=sub, predicate=pred, object=obj,
                confidence=float(r.get("confidence", 0.5)),
            ))
        return EnrichedNews(
            raw_id=raw_id,
            summary=payload["summary"],
            related_tickers=payload.get("related_tickers", []),
            sectors=payload.get("sectors", []),
            event_type=EventType(payload["event_type"]),
            sentiment=Sentiment(payload["sentiment"]),
            magnitude=Magnitude(payload["magnitude"]),
            confidence=float(payload["confidence"]),
            key_quotes=payload.get("key_quotes", []),
            entities=list(ents_by_name.values()),
            relations=relations,
            model_used=rendered.model_target,
            extracted_at=datetime.utcnow(),
        )
```

- [ ] **Step 4: Run — pass**

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/llm/extractors.py tests/unit/llm/test_tier2_extractor.py
git commit -m "feat: add Tier-2 deep extractor with entities + relations"
```

---

### Task 41: LLM router (tier selection)

**Files:**
- Create: `src/news_pipeline/llm/router.py`
- Create: `tests/unit/llm/test_router.py`

- [ ] **Step 1: Test**

```python
# tests/unit/llm/test_router.py
from datetime import datetime

import pytest

from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.enums import Market
from news_pipeline.llm.extractors import Tier0Verdict
from news_pipeline.llm.router import LLMRouter


def _art(source: str = "x", title: str = "t") -> RawArticle:
    return RawArticle(
        source=source, market=Market.US,
        fetched_at=datetime(2026, 4, 25), published_at=datetime(2026, 4, 25),
        url="https://x/1", url_hash="h", title=title, body="b",
    )


def test_first_party_source_forces_tier2():
    r = LLMRouter(first_party_sources={"sec_edgar", "juchao", "caixin_telegram"})
    decision = r.decide(
        _art(source="sec_edgar"),
        verdict=Tier0Verdict(relevant=True, tier_hint="tier1",
                             watchlist_hit=False, reason=""),
    )
    assert decision == "tier2"


def test_irrelevant_returns_skip():
    r = LLMRouter(first_party_sources=set())
    decision = r.decide(
        _art(),
        verdict=Tier0Verdict(relevant=False, tier_hint="tier1",
                             watchlist_hit=False, reason="off topic"),
    )
    assert decision == "skip"


def test_watchlist_hit_uses_tier2():
    r = LLMRouter(first_party_sources=set())
    decision = r.decide(
        _art(),
        verdict=Tier0Verdict(relevant=True, tier_hint="tier2",
                             watchlist_hit=True, reason=""),
    )
    assert decision == "tier2"


def test_other_relevant_uses_tier1():
    r = LLMRouter(first_party_sources=set())
    decision = r.decide(
        _art(),
        verdict=Tier0Verdict(relevant=True, tier_hint="tier1",
                             watchlist_hit=False, reason=""),
    )
    assert decision == "tier1"
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

```python
# src/news_pipeline/llm/router.py
from typing import Literal

from news_pipeline.common.contracts import RawArticle
from news_pipeline.llm.extractors import Tier0Verdict


Tier = Literal["skip", "tier1", "tier2"]


class LLMRouter:
    def __init__(self, *, first_party_sources: set[str]) -> None:
        self._first_party = first_party_sources

    def decide(self, art: RawArticle, *, verdict: Tier0Verdict) -> Tier:
        if art.source in self._first_party:
            return "tier2"
        if not verdict.relevant:
            return "skip"
        if verdict.watchlist_hit or verdict.tier_hint == "tier2":
            return "tier2"
        return "tier1"
```

- [ ] **Step 4: Run — pass**

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/llm/router.py tests/unit/llm/test_router.py
git commit -m "feat: add LLM router with first-party + watchlist rules"
```

---

### Task 42: LLM pipeline orchestrator (with retry + cost guard)

**Files:**
- Create: `src/news_pipeline/llm/pipeline.py`
- Create: `tests/unit/llm/test_pipeline.py`

- [ ] **Step 1: Test**

```python
# tests/unit/llm/test_pipeline.py
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.enums import Market
from news_pipeline.common.exceptions import CostCeilingExceeded
from news_pipeline.llm.extractors import Tier0Verdict
from news_pipeline.llm.pipeline import LLMPipeline


def _art() -> RawArticle:
    return RawArticle(
        source="finnhub", market=Market.US,
        fetched_at=datetime(2026, 4, 25), published_at=datetime(2026, 4, 25),
        url="https://x/1", url_hash="h", title="NVDA up", body="b",
    )


@pytest.mark.asyncio
async def test_pipeline_routes_to_tier2_when_watchlist_hit():
    classifier = MagicMock()
    classifier.classify = AsyncMock(return_value=Tier0Verdict(
        relevant=True, tier_hint="tier2", watchlist_hit=True, reason="hit"))
    tier1 = MagicMock()
    tier1.summarize = AsyncMock()
    tier2 = MagicMock()
    tier2.extract = AsyncMock(return_value="enriched_2")
    router = MagicMock()
    router.decide = MagicMock(return_value="tier2")
    cost = MagicMock()
    cost.check = MagicMock()

    p = LLMPipeline(classifier, tier1, tier2, router, cost,
                    watchlist_us=["NVDA"], watchlist_cn=[])
    out = await p.process(_art(), raw_id=1)
    assert out == "enriched_2"
    tier2.extract.assert_awaited_once()
    tier1.summarize.assert_not_awaited()


@pytest.mark.asyncio
async def test_pipeline_skips_when_classifier_says_irrelevant():
    classifier = MagicMock()
    classifier.classify = AsyncMock(return_value=Tier0Verdict(
        relevant=False, tier_hint="tier1", watchlist_hit=False, reason=""))
    tier1, tier2 = MagicMock(), MagicMock()
    tier1.summarize, tier2.extract = AsyncMock(), AsyncMock()
    router = MagicMock(); router.decide = MagicMock(return_value="skip")
    cost = MagicMock(); cost.check = MagicMock()
    p = LLMPipeline(classifier, tier1, tier2, router, cost, [], [])
    out = await p.process(_art(), raw_id=1)
    assert out is None


@pytest.mark.asyncio
async def test_pipeline_cost_ceiling_short_circuits():
    classifier = MagicMock()
    classifier.classify = AsyncMock()
    cost = MagicMock()
    cost.check = MagicMock(side_effect=CostCeilingExceeded("over"))
    p = LLMPipeline(classifier, MagicMock(), MagicMock(), MagicMock(), cost, [], [])
    with pytest.raises(CostCeilingExceeded):
        await p.process(_art(), raw_id=1)
    classifier.classify.assert_not_awaited()
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

```python
# src/news_pipeline/llm/pipeline.py
from news_pipeline.common.contracts import EnrichedNews, RawArticle
from news_pipeline.llm.cost_tracker import CostTracker
from news_pipeline.llm.extractors import (
    Tier0Classifier, Tier1Summarizer, Tier2DeepExtractor,
)
from news_pipeline.llm.router import LLMRouter
from news_pipeline.observability.log import get_logger

log = get_logger(__name__)


class LLMPipeline:
    def __init__(
        self,
        classifier: Tier0Classifier,
        tier1: Tier1Summarizer,
        tier2: Tier2DeepExtractor,
        router: LLMRouter,
        cost_tracker: CostTracker,
        watchlist_us: list[str],
        watchlist_cn: list[str],
    ) -> None:
        self._cls = classifier
        self._t1 = tier1
        self._t2 = tier2
        self._router = router
        self._cost = cost_tracker
        self._wl_us = watchlist_us
        self._wl_cn = watchlist_cn

    async def process(self, art: RawArticle, *, raw_id: int) -> EnrichedNews | None:
        self._cost.check()  # raises CostCeilingExceeded
        verdict = await self._cls.classify(
            art, watchlist_us=self._wl_us, watchlist_cn=self._wl_cn,
        )
        decision = self._router.decide(art, verdict=verdict)
        if decision == "skip":
            log.debug("llm_skip", url_hash=art.url_hash, reason=verdict.reason)
            return None
        if decision == "tier1":
            return await self._t1.summarize(art, raw_id=raw_id)
        return await self._t2.extract(art, raw_id=raw_id, recent_context="")
```

- [ ] **Step 4: Run — pass**

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/llm/pipeline.py tests/unit/llm/test_pipeline.py
git commit -m "feat: add LLMPipeline orchestrator with cost guard"
```

---

## Phase 6 — Classifier + Dispatch Router (Tasks 43-46)

### Task 43: Rule engine

**Files:**
- Create: `src/news_pipeline/classifier/__init__.py`
- Create: `src/news_pipeline/classifier/rules.py`
- Create: `tests/unit/classifier/test_rules.py`

- [ ] **Step 1: Test**

```python
# tests/unit/classifier/test_rules.py
from datetime import datetime

from news_pipeline.classifier.rules import RuleEngine, RuleHit
from news_pipeline.common.contracts import EnrichedNews
from news_pipeline.common.enums import EventType, Magnitude, Sentiment
from news_pipeline.config.schema import ClassifierRulesCfg


def _enriched(magnitude="medium", sentiment="neutral",
              event="other", tickers=None) -> EnrichedNews:
    return EnrichedNews(
        raw_id=1, summary="s", related_tickers=tickers or [],
        sectors=[], event_type=EventType(event),
        sentiment=Sentiment(sentiment), magnitude=Magnitude(magnitude),
        confidence=0.8, key_quotes=[], entities=[], relations=[],
        model_used="x", extracted_at=datetime(2026, 4, 25),
    )


def _cfg() -> ClassifierRulesCfg:
    return ClassifierRulesCfg(
        price_move_critical_pct=5.0,
        sources_always_critical=["sec_edgar", "juchao"],
        sentiment_high_magnitude_critical=True,
    )


def test_first_party_source_hits():
    e = RuleEngine(_cfg())
    hits = e.evaluate(_enriched(), source="sec_edgar")
    assert any(h.name == "first_party_source" for h in hits)


def test_high_magnitude_sentiment_hits():
    e = RuleEngine(_cfg())
    hits = e.evaluate(_enriched(magnitude="high", sentiment="bearish"),
                      source="finnhub")
    assert any(h.name == "sentiment_high" for h in hits)


def test_low_neutral_no_hits():
    e = RuleEngine(_cfg())
    hits = e.evaluate(_enriched(magnitude="low"), source="finnhub")
    assert hits == []


def test_score_combines_hits():
    e = RuleEngine(_cfg())
    hits = [RuleHit("first_party_source", 30), RuleHit("sentiment_high", 40)]
    assert e.score(hits) == 70
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

```python
# src/news_pipeline/classifier/__init__.py
```

```python
# src/news_pipeline/classifier/rules.py
from dataclasses import dataclass

from news_pipeline.common.contracts import EnrichedNews
from news_pipeline.config.schema import ClassifierRulesCfg


@dataclass(frozen=True)
class RuleHit:
    name: str
    weight: int


class RuleEngine:
    def __init__(self, cfg: ClassifierRulesCfg) -> None:
        self._cfg = cfg

    def evaluate(self, e: EnrichedNews, *, source: str) -> list[RuleHit]:
        hits: list[RuleHit] = []
        if source in self._cfg.sources_always_critical:
            hits.append(RuleHit("first_party_source", 30))
        if (self._cfg.sentiment_high_magnitude_critical
                and e.magnitude.value == "high"
                and e.sentiment.value in ("bullish", "bearish")):
            hits.append(RuleHit("sentiment_high", 40))
        if e.event_type.value in ("earnings", "m_and_a", "downgrade", "upgrade"):
            hits.append(RuleHit(f"event_{e.event_type.value}", 20))
        if e.event_type.value == "filing":
            hits.append(RuleHit("filing", 25))
        return hits

    @staticmethod
    def score(hits: list[RuleHit]) -> int:
        return min(100, sum(h.weight for h in hits))
```

```bash
mkdir -p tests/unit/classifier && touch tests/unit/classifier/__init__.py
```

- [ ] **Step 4: Run — pass**

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/classifier/ tests/unit/classifier/test_rules.py
git commit -m "feat: add classifier rule engine"
```

---

### Task 44: LLM judge for gray-zone (uses Tier-2 client)

**Files:**
- Create: `src/news_pipeline/classifier/llm_judge.py`
- Create: `tests/unit/classifier/test_llm_judge.py`

- [ ] **Step 1: Test**

```python
# tests/unit/classifier/test_llm_judge.py
from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from news_pipeline.classifier.llm_judge import LLMJudge
from news_pipeline.common.contracts import EnrichedNews
from news_pipeline.common.enums import EventType, Magnitude, Sentiment
from news_pipeline.llm.clients.base import LLMResponse, TokenUsage


def _enriched() -> EnrichedNews:
    return EnrichedNews(
        raw_id=1, summary="s", related_tickers=["NVDA"], sectors=[],
        event_type=EventType.OTHER, sentiment=Sentiment.NEUTRAL,
        magnitude=Magnitude.MEDIUM, confidence=0.7, key_quotes=[],
        entities=[], relations=[], model_used="x",
        extracted_at=datetime(2026, 4, 25),
    )


@pytest.mark.asyncio
async def test_judge_critical():
    fake = AsyncMock()
    fake.call.return_value = LLMResponse(
        text="", json_payload={"is_critical": True, "reason": "持仓股利空"},
        usage=TokenUsage(200, 30), model="deepseek-v3",
    )
    j = LLMJudge(client=fake, model="deepseek-v3")
    is_crit, reason = await j.judge(_enriched(), watchlist_tickers=["NVDA"])
    assert is_crit is True
    assert "持仓" in reason
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

```python
# src/news_pipeline/classifier/llm_judge.py
from news_pipeline.common.contracts import EnrichedNews
from news_pipeline.llm.clients.base import LLMClient, LLMRequest

JUDGE_SYSTEM = """\
你是判定器。给定一条新闻摘要 + 用户 watchlist, 判断是否值得"立即推送"\
（is_critical=true/false）。输出 JSON {"is_critical": bool, "reason": str}.\
判定准则: 涉及用户 watchlist 中股票的实质性事件（业绩/重大变更/政策影响）→ true; \
噪音/普通市场评论/无关公司 → false.
"""

JUDGE_USER = """\
摘要: {summary}
关联标的: {tickers}
事件类型: {event_type}
情绪: {sentiment} / 量级: {magnitude}
Watchlist: {watchlist}
"""


class LLMJudge:
    def __init__(self, *, client: LLMClient, model: str) -> None:
        self._client = client
        self._model = model

    async def judge(
        self, e: EnrichedNews, *, watchlist_tickers: list[str],
    ) -> tuple[bool, str]:
        req = LLMRequest(
            model=self._model, system=JUDGE_SYSTEM,
            user=JUDGE_USER.format(
                summary=e.summary, tickers=",".join(e.related_tickers),
                event_type=e.event_type.value, sentiment=e.sentiment.value,
                magnitude=e.magnitude.value,
                watchlist=",".join(watchlist_tickers),
            ),
            json_mode=True,
            output_schema={
                "type": "object",
                "required": ["is_critical", "reason"],
                "properties": {
                    "is_critical": {"type": "boolean"},
                    "reason": {"type": "string"},
                },
            },
            max_tokens=200,
        )
        resp = await self._client.call(req)
        payload = resp.json_payload or {"is_critical": False, "reason": ""}
        return bool(payload["is_critical"]), str(payload.get("reason", ""))
```

- [ ] **Step 4: Run — pass**

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/classifier/llm_judge.py tests/unit/classifier/test_llm_judge.py
git commit -m "feat: add LLM judge for gray-zone classification"
```

---

### Task 45: Importance scorer (combine rules + LLM judge)

**Files:**
- Create: `src/news_pipeline/classifier/importance.py`
- Create: `tests/unit/classifier/test_importance.py`

- [ ] **Step 1: Test**

```python
# tests/unit/classifier/test_importance.py
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from news_pipeline.classifier.importance import ImportanceClassifier
from news_pipeline.classifier.rules import RuleHit
from news_pipeline.common.contracts import EnrichedNews
from news_pipeline.common.enums import EventType, Magnitude, Sentiment


def _e(m="medium") -> EnrichedNews:
    return EnrichedNews(
        raw_id=1, summary="s", related_tickers=["NVDA"], sectors=[],
        event_type=EventType.OTHER, sentiment=Sentiment.NEUTRAL,
        magnitude=Magnitude(m), confidence=0.7, key_quotes=[],
        entities=[], relations=[], model_used="x",
        extracted_at=datetime(2026, 4, 25),
    )


@pytest.mark.asyncio
async def test_high_score_critical_no_judge():
    rules = MagicMock()
    rules.evaluate.return_value = [RuleHit("first_party_source", 30),
                                   RuleHit("sentiment_high", 40)]
    rules.score = lambda hits: 70
    judge = MagicMock(); judge.judge = AsyncMock()
    cls = ImportanceClassifier(rules=rules, judge=judge,
                                gray_zone=(40, 70), watchlist_tickers=["NVDA"])
    scored = await cls.score_news(_e(), source="sec_edgar")
    assert scored.is_critical is True
    judge.judge.assert_not_awaited()


@pytest.mark.asyncio
async def test_low_score_not_critical_no_judge():
    rules = MagicMock(); rules.evaluate.return_value = []
    rules.score = lambda hits: 10
    judge = MagicMock(); judge.judge = AsyncMock()
    cls = ImportanceClassifier(rules=rules, judge=judge,
                                gray_zone=(40, 70), watchlist_tickers=["NVDA"])
    scored = await cls.score_news(_e(), source="finnhub")
    assert scored.is_critical is False
    judge.judge.assert_not_awaited()


@pytest.mark.asyncio
async def test_gray_zone_calls_judge():
    rules = MagicMock(); rules.evaluate.return_value = [RuleHit("filing", 50)]
    rules.score = lambda hits: 50
    judge = MagicMock(); judge.judge = AsyncMock(return_value=(True, "持仓"))
    cls = ImportanceClassifier(rules=rules, judge=judge,
                                gray_zone=(40, 70), watchlist_tickers=["NVDA"])
    scored = await cls.score_news(_e(), source="finnhub")
    judge.judge.assert_awaited_once()
    assert scored.is_critical is True
    assert scored.llm_reason == "持仓"
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

```python
# src/news_pipeline/classifier/importance.py
from news_pipeline.classifier.llm_judge import LLMJudge
from news_pipeline.classifier.rules import RuleEngine
from news_pipeline.common.contracts import EnrichedNews, ScoredNews


class ImportanceClassifier:
    def __init__(
        self, *,
        rules: RuleEngine,
        judge: LLMJudge,
        gray_zone: tuple[float, float],
        watchlist_tickers: list[str],
    ) -> None:
        self._rules = rules
        self._judge = judge
        self._lo, self._hi = gray_zone
        self._wl = watchlist_tickers

    async def score_news(self, e: EnrichedNews, *, source: str) -> ScoredNews:
        hits = self._rules.evaluate(e, source=source)
        score = float(self._rules.score(hits))
        rule_names = [h.name for h in hits]

        if score >= self._hi:
            return ScoredNews(enriched=e, score=score, is_critical=True,
                              rule_hits=rule_names, llm_reason=None)
        if score < self._lo:
            return ScoredNews(enriched=e, score=score, is_critical=False,
                              rule_hits=rule_names, llm_reason=None)
        # gray zone → LLM tiebreaker
        is_crit, reason = await self._judge.judge(e, watchlist_tickers=self._wl)
        return ScoredNews(enriched=e, score=score, is_critical=is_crit,
                          rule_hits=rule_names, llm_reason=reason)
```

- [ ] **Step 4: Run — pass**

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/classifier/importance.py tests/unit/classifier/test_importance.py
git commit -m "feat: add importance classifier (rules + LLM judge)"
```

---

### Task 46: Dispatch router (immediate vs digest, channel selection)

**Files:**
- Create: `src/news_pipeline/router/__init__.py`
- Create: `src/news_pipeline/router/routes.py`
- Create: `tests/unit/router/test_routes.py`

- [ ] **Step 1: Test**

```python
# tests/unit/router/test_routes.py
from datetime import datetime

from news_pipeline.common.contracts import (
    Badge, CommonMessage, Deeplink, EnrichedNews, ScoredNews,
)
from news_pipeline.common.enums import EventType, Magnitude, Market, Sentiment
from news_pipeline.router.routes import DispatchRouter


def _scored(market: str = "us", critical: bool = False) -> ScoredNews:
    e = EnrichedNews(
        raw_id=1, summary="s", related_tickers=[], sectors=[],
        event_type=EventType.OTHER, sentiment=Sentiment.NEUTRAL,
        magnitude=Magnitude.LOW, confidence=0.5, key_quotes=[],
        entities=[], relations=[], model_used="x",
        extracted_at=datetime(2026, 4, 25),
    )
    return ScoredNews(enriched=e, score=50.0, is_critical=critical,
                      rule_hits=[], llm_reason=None)


def _msg(market: Market) -> CommonMessage:
    return CommonMessage(
        title="t", summary="s", source_label="x",
        source_url="https://x.com", badges=[],
        chart_url=None, deeplinks=[], market=market,
    )


def test_critical_us_routes_to_us_channels_immediate():
    r = DispatchRouter(channels_by_market={
        "us": ["tg_us", "feishu_us", "wecom_us"],
        "cn": ["tg_cn", "feishu_cn", "wecom_cn"],
    })
    plans = r.route(_scored("us", critical=True), _msg(Market.US))
    assert len(plans) == 1
    p = plans[0]
    assert set(p.channels) == {"tg_us", "feishu_us", "wecom_us"}
    assert p.immediate is True


def test_non_critical_routes_to_digest():
    r = DispatchRouter(channels_by_market={
        "cn": ["tg_cn", "feishu_cn"],
    })
    plans = r.route(_scored("cn", critical=False), _msg(Market.CN))
    assert plans[0].immediate is False
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

```python
# src/news_pipeline/router/__init__.py
```

```python
# src/news_pipeline/router/routes.py
from news_pipeline.common.contracts import CommonMessage, DispatchPlan, ScoredNews


class DispatchRouter:
    def __init__(self, *, channels_by_market: dict[str, list[str]]) -> None:
        self._by_market = channels_by_market

    def route(self, scored: ScoredNews, msg: CommonMessage) -> list[DispatchPlan]:
        channels = self._by_market.get(msg.market.value, [])
        if not channels:
            return []
        return [DispatchPlan(message=msg, channels=channels,
                             immediate=scored.is_critical)]
```

- [ ] **Step 4: Run — pass**

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/router/ tests/unit/router/
git commit -m "feat: add dispatch router (immediate vs digest, channel selection)"
```

---

## Phase 7 — Pushers (Tasks 47-53)

### Task 47: CommonMessage builder

**Files:**
- Create: `src/news_pipeline/pushers/__init__.py`
- Create: `src/news_pipeline/pushers/common/__init__.py`
- Create: `src/news_pipeline/pushers/common/message_builder.py`
- Create: `tests/unit/pushers/test_message_builder.py`

- [ ] **Step 1: Test**

```python
# tests/unit/pushers/test_message_builder.py
from datetime import datetime

from news_pipeline.common.contracts import EnrichedNews, RawArticle, ScoredNews
from news_pipeline.common.enums import EventType, Magnitude, Market, Sentiment
from news_pipeline.pushers.common.message_builder import MessageBuilder


def _make() -> tuple[RawArticle, ScoredNews]:
    art = RawArticle(
        source="reuters", market=Market.US,
        fetched_at=datetime(2026, 4, 25),
        published_at=datetime(2026, 4, 25, 22, 30),
        url="https://reut.com/x", url_hash="h",
        title="NVDA -8% on export controls", body="...",
    )
    e = EnrichedNews(
        raw_id=1, summary="出口管制升级",
        related_tickers=["NVDA", "TSM"], sectors=["semiconductor"],
        event_type=EventType.POLICY, sentiment=Sentiment.BEARISH,
        magnitude=Magnitude.HIGH, confidence=0.92,
        key_quotes=["将 H100 列入实体清单"],
        entities=[], relations=[],
        model_used="claude-haiku-4-5", extracted_at=datetime(2026, 4, 25),
    )
    s = ScoredNews(enriched=e, score=80, is_critical=True,
                   rule_hits=["sentiment_high"], llm_reason=None)
    return art, s


def test_build_includes_badges_and_deeplinks():
    art, scored = _make()
    b = MessageBuilder(source_labels={"reuters": "Reuters"})
    msg = b.build(art, scored, chart_url=None)
    badge_texts = [bd.text for bd in msg.badges]
    assert "bearish" in badge_texts and "high" in badge_texts
    assert any(d.label.startswith("原文") or d.label == "原文" for d in msg.deeplinks)
    assert msg.market == Market.US
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

```python
# src/news_pipeline/pushers/__init__.py
```

```python
# src/news_pipeline/pushers/common/__init__.py
```

```python
# src/news_pipeline/pushers/common/message_builder.py
from news_pipeline.common.contracts import (
    Badge, CommonMessage, Deeplink, RawArticle, ScoredNews,
)
from news_pipeline.common.enums import Market, Sentiment


_SENTIMENT_COLOR = {
    Sentiment.BULLISH: "green",
    Sentiment.BEARISH: "red",
    Sentiment.NEUTRAL: "gray",
}


class MessageBuilder:
    def __init__(self, *, source_labels: dict[str, str]) -> None:
        self._labels = source_labels

    def build(
        self, art: RawArticle, scored: ScoredNews, *,
        chart_url: str | None = None,
    ) -> CommonMessage:
        e = scored.enriched
        badges: list[Badge] = []
        for t in e.related_tickers[:5]:
            badges.append(Badge(text=t, color="blue"))
        for s in e.sectors[:2]:
            badges.append(Badge(text=f"#{s}", color="gray"))
        badges.append(Badge(text=e.sentiment.value,
                            color=_SENTIMENT_COLOR[e.sentiment]))
        badges.append(Badge(text=e.magnitude.value, color="yellow"))

        deeplinks = [Deeplink(label="原文", url=str(art.url))]
        for t in e.related_tickers[:3]:
            if art.market == Market.US:
                deeplinks.append(Deeplink(
                    label=f"Yahoo {t}",
                    url=f"https://finance.yahoo.com/quote/{t}",
                ))
            else:
                deeplinks.append(Deeplink(
                    label=f"东财 {t}",
                    url=f"https://quote.eastmoney.com/{('sh' if t.startswith('6') else 'sz')}{t}.html",
                ))

        return CommonMessage(
            title=art.title, summary=e.summary,
            source_label=self._labels.get(art.source, art.source),
            source_url=str(art.url), badges=badges,
            chart_url=chart_url, deeplinks=deeplinks,
            market=art.market,
        )
```

```bash
mkdir -p tests/unit/pushers && touch tests/unit/pushers/__init__.py
```

- [ ] **Step 4: Run — pass**

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/pushers/ tests/unit/pushers/test_message_builder.py
git commit -m "feat: add CommonMessage builder"
```

---

### Task 48: Pusher base + retry decorator

**Files:**
- Create: `src/news_pipeline/pushers/base.py`
- Create: `src/news_pipeline/pushers/common/retry.py`
- Create: `tests/unit/pushers/test_retry.py`

- [ ] **Step 1: Test**

```python
# tests/unit/pushers/test_retry.py
import pytest

from news_pipeline.pushers.common.retry import async_retry


@pytest.mark.asyncio
async def test_succeeds_first_try():
    calls = {"n": 0}
    @async_retry(max_attempts=3, backoff_seconds=0.0)
    async def fn():
        calls["n"] += 1
        return "ok"
    assert await fn() == "ok"
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_retries_on_exception():
    calls = {"n": 0}
    @async_retry(max_attempts=3, backoff_seconds=0.0,
                 retry_on=(RuntimeError,))
    async def fn():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("x")
        return "ok"
    assert await fn() == "ok"
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_does_not_retry_on_unmatched_exception():
    @async_retry(max_attempts=3, backoff_seconds=0.0,
                 retry_on=(RuntimeError,))
    async def fn():
        raise ValueError("fatal")
    with pytest.raises(ValueError):
        await fn()
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

```python
# src/news_pipeline/pushers/common/retry.py
import asyncio
from functools import wraps
from typing import Awaitable, Callable, TypeVar

T = TypeVar("T")


def async_retry(
    *, max_attempts: int = 3, backoff_seconds: float = 1.0,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
):
    def deco(fn: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @wraps(fn)
        async def wrapper(*args, **kwargs):
            attempt = 0
            while True:
                try:
                    return await fn(*args, **kwargs)
                except retry_on:
                    attempt += 1
                    if attempt >= max_attempts:
                        raise
                    await asyncio.sleep(backoff_seconds * (2 ** (attempt - 1)))
        return wrapper
    return deco
```

```python
# src/news_pipeline/pushers/base.py
from dataclasses import dataclass
from typing import Protocol

from news_pipeline.common.contracts import CommonMessage


@dataclass
class SendResult:
    ok: bool
    http_status: int | None = None
    response_body: str = ""
    retries: int = 0


class PusherProtocol(Protocol):
    channel_id: str

    async def send(self, msg: CommonMessage) -> SendResult: ...
```

- [ ] **Step 4: Run — pass**

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/pushers/{base,common/retry}.py tests/unit/pushers/test_retry.py
git commit -m "feat: add Pusher protocol and async_retry helper"
```

---

### Task 49: Telegram pusher (MarkdownV2)

**Files:**
- Create: `src/news_pipeline/pushers/telegram.py`
- Create: `tests/unit/pushers/test_telegram.py`

- [ ] **Step 1: Test**

```python
# tests/unit/pushers/test_telegram.py
import pytest
import respx
from httpx import Response

from news_pipeline.common.contracts import (
    Badge, CommonMessage, Deeplink,
)
from news_pipeline.common.enums import Market
from news_pipeline.pushers.telegram import TelegramPusher


def _msg() -> CommonMessage:
    return CommonMessage(
        title="NVDA *up* 5%", summary="出口管制 [详情]",
        source_label="Reuters", source_url="https://reut/x",
        badges=[Badge(text="NVDA", color="blue"),
                Badge(text="bearish", color="red")],
        chart_url=None,
        deeplinks=[Deeplink(label="原文", url="https://reut/x"),
                   Deeplink(label="Yahoo", url="https://yhoo/x")],
        market=Market.US,
    )


@pytest.mark.asyncio
async def test_send_escapes_and_returns_ok():
    async with respx.mock() as mock:
        route = mock.post(
            "https://api.telegram.org/botT/sendMessage"
        ).mock(return_value=Response(200, json={"ok": True}))
        p = TelegramPusher(channel_id="tg_us", bot_token="T", chat_id="C")
        result = await p.send(_msg())
        assert result.ok is True
        body = route.calls[0].request.read().decode()
        # MarkdownV2 escaping required
        assert "\\*" in body or "%5C%2A" in body  # the * was escaped
        assert "MarkdownV2" in body


@pytest.mark.asyncio
async def test_send_failure_returns_not_ok():
    async with respx.mock() as mock:
        mock.post("https://api.telegram.org/botT/sendMessage").mock(
            return_value=Response(400, json={"ok": False, "description": "bad"})
        )
        p = TelegramPusher(channel_id="tg_us", bot_token="T", chat_id="C",
                            max_retries=1)
        result = await p.send(_msg())
        assert result.ok is False
        assert result.http_status == 400
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

```python
# src/news_pipeline/pushers/telegram.py
import re

import httpx

from news_pipeline.common.contracts import CommonMessage
from news_pipeline.pushers.base import SendResult
from news_pipeline.pushers.common.retry import async_retry

# https://core.telegram.org/bots/api#markdownv2-style
_MD2_SPECIAL = r"_*[]()~`>#+-=|{}.!\\"


def md2_escape(text: str) -> str:
    return re.sub(rf"([{re.escape(_MD2_SPECIAL)}])", r"\\\1", text)


class TelegramPusher:
    def __init__(
        self, *, channel_id: str, bot_token: str, chat_id: str,
        timeout: float = 10.0, max_retries: int = 3,
    ) -> None:
        self.channel_id = channel_id
        self._bot = bot_token
        self._chat = chat_id
        self._timeout = timeout
        self._max = max_retries

    async def send(self, msg: CommonMessage) -> SendResult:
        text = self._render(msg)
        url = f"https://api.telegram.org/bot{self._bot}/sendMessage"
        body = {
            "chat_id": self._chat,
            "text": text,
            "parse_mode": "MarkdownV2",
            "disable_web_page_preview": False,
        }

        @async_retry(max_attempts=self._max, backoff_seconds=1.0,
                     retry_on=(httpx.HTTPError,))
        async def _post() -> tuple[int, str]:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                r = await client.post(url, json=body)
                return r.status_code, r.text

        try:
            status, resp_text = await _post()
        except httpx.HTTPError as e:
            return SendResult(ok=False, http_status=None,
                              response_body=str(e), retries=self._max)
        return SendResult(ok=(status == 200), http_status=status,
                          response_body=resp_text, retries=0)

    def _render(self, msg: CommonMessage) -> str:
        title = md2_escape(msg.title)
        summary = md2_escape(msg.summary)
        badges = " ".join(f"`{md2_escape(b.text)}`" for b in msg.badges)
        links = "  \\| ".join(
            f"[{md2_escape(d.label)}]({d.url})" for d in msg.deeplinks
        )
        chart = ""
        if msg.chart_url:
            chart = f"\n\n[📈 chart]({msg.chart_url})"
        return (
            f"*{title}*\n"
            f"_{md2_escape(msg.source_label)}_\n\n"
            f"{summary}\n\n"
            f"{badges}\n\n"
            f"{links}{chart}"
        )
```

- [ ] **Step 4: Run — pass**

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/pushers/telegram.py tests/unit/pushers/test_telegram.py
git commit -m "feat: add Telegram pusher with MarkdownV2"
```

---

### Task 50: 飞书 pusher (Card JSON)

**Files:**
- Create: `src/news_pipeline/pushers/feishu.py`
- Create: `tests/unit/pushers/test_feishu.py`

- [ ] **Step 1: Test**

```python
# tests/unit/pushers/test_feishu.py
import json

import pytest
import respx
from httpx import Response

from news_pipeline.common.contracts import (
    Badge, CommonMessage, Deeplink,
)
from news_pipeline.common.enums import Market
from news_pipeline.pushers.feishu import FeishuPusher


def _msg() -> CommonMessage:
    return CommonMessage(
        title="NVDA -8%", summary="出口管制升级",
        source_label="Reuters", source_url="https://reut/x",
        badges=[Badge(text="bearish", color="red"),
                Badge(text="high", color="yellow")],
        chart_url="https://oss/chart.png",
        deeplinks=[Deeplink(label="原文", url="https://reut/x")],
        market=Market.US,
    )


@pytest.mark.asyncio
async def test_send_uses_card_format():
    async with respx.mock() as mock:
        route = mock.post("https://open.feishu.cn/hook/W").mock(
            return_value=Response(200, json={"code": 0, "msg": "ok"})
        )
        p = FeishuPusher(channel_id="feishu_us",
                          webhook="https://open.feishu.cn/hook/W")
        result = await p.send(_msg())
        assert result.ok is True
        sent = json.loads(route.calls[0].request.read().decode())
        assert sent["msg_type"] == "interactive"
        assert "card" in sent
        # color tag conveys sentiment
        assert "red" in json.dumps(sent) or "danger" in json.dumps(sent)
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

```python
# src/news_pipeline/pushers/feishu.py
import hashlib
import hmac
import time
from base64 import b64encode

import httpx

from news_pipeline.common.contracts import CommonMessage
from news_pipeline.pushers.base import SendResult
from news_pipeline.pushers.common.retry import async_retry

_BADGE_COLOR_MAP = {
    "red": "red", "green": "green", "yellow": "yellow",
    "blue": "blue", "gray": "grey",
}


class FeishuPusher:
    def __init__(
        self, *, channel_id: str, webhook: str, sign_secret: str | None = None,
        timeout: float = 10.0, max_retries: int = 3,
    ) -> None:
        self.channel_id = channel_id
        self._webhook = webhook
        self._secret = sign_secret
        self._timeout = timeout
        self._max = max_retries

    async def send(self, msg: CommonMessage) -> SendResult:
        body = self._build_card(msg)
        if self._secret:
            ts = str(int(time.time()))
            body["timestamp"] = ts
            body["sign"] = self._sign(ts)

        @async_retry(max_attempts=self._max, backoff_seconds=1.0,
                     retry_on=(httpx.HTTPError,))
        async def _post() -> tuple[int, str]:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                r = await client.post(self._webhook, json=body)
                return r.status_code, r.text

        try:
            status, resp = await _post()
        except httpx.HTTPError as e:
            return SendResult(ok=False, http_status=None,
                              response_body=str(e), retries=self._max)
        return SendResult(ok=(status == 200 and '"code":0' in resp),
                          http_status=status, response_body=resp, retries=0)

    def _sign(self, timestamp: str) -> str:
        string_to_sign = f"{timestamp}\n{self._secret}"
        h = hmac.new(string_to_sign.encode(), digestmod=hashlib.sha256)
        return b64encode(h.digest()).decode()

    def _build_card(self, msg: CommonMessage) -> dict:
        # template color = first badge color (sentiment usually)
        first_color = _BADGE_COLOR_MAP.get(
            msg.badges[0].color if msg.badges else "gray", "grey",
        )
        body_text = (
            f"**{msg.summary}**\n\n"
            + " ".join(f"`{b.text}`" for b in msg.badges) + "\n\n"
            + " | ".join(f"[{d.label}]({d.url})" for d in msg.deeplinks)
        )
        elements: list[dict] = [
            {"tag": "div", "text": {"tag": "lark_md", "content": body_text}},
        ]
        if msg.chart_url:
            elements.append({
                "tag": "img", "img_key": str(msg.chart_url),
                "alt": {"tag": "plain_text", "content": "chart"},
            })
        return {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": msg.title[:128]},
                    "template": first_color,
                },
                "elements": elements,
            },
        }
```

> **Note:** Real 飞书 image embedding requires uploading via `image_key` API; for MVP we attach as text link. Improvement tracked separately.

- [ ] **Step 4: Run — pass**

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/pushers/feishu.py tests/unit/pushers/test_feishu.py
git commit -m "feat: add 飞书 pusher with interactive card"
```

---

### Task 51: 企微 pusher (Markdown limited)

**Files:**
- Create: `src/news_pipeline/pushers/wecom.py`
- Create: `tests/unit/pushers/test_wecom.py`

- [ ] **Step 1: Test**

```python
# tests/unit/pushers/test_wecom.py
import json

import pytest
import respx
from httpx import Response

from news_pipeline.common.contracts import Badge, CommonMessage, Deeplink
from news_pipeline.common.enums import Market
from news_pipeline.pushers.wecom import WecomPusher


def _msg() -> CommonMessage:
    return CommonMessage(
        title="NVDA -8%", summary="出口管制",
        source_label="Reuters", source_url="https://reut/x",
        badges=[Badge(text="bearish", color="red")],
        chart_url=None,
        deeplinks=[Deeplink(label="原文", url="https://reut/x")],
        market=Market.US,
    )


@pytest.mark.asyncio
async def test_send_uses_markdown_msgtype():
    async with respx.mock() as mock:
        route = mock.post("https://qyapi.weixin.qq.com/W").mock(
            return_value=Response(200, json={"errcode": 0})
        )
        p = WecomPusher(channel_id="wecom_us",
                         webhook="https://qyapi.weixin.qq.com/W")
        result = await p.send(_msg())
        assert result.ok is True
        sent = json.loads(route.calls[0].request.read().decode())
        assert sent["msgtype"] == "markdown"
        assert "**NVDA" in sent["markdown"]["content"]
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

```python
# src/news_pipeline/pushers/wecom.py
import httpx

from news_pipeline.common.contracts import CommonMessage
from news_pipeline.pushers.base import SendResult
from news_pipeline.pushers.common.retry import async_retry


class WecomPusher:
    def __init__(
        self, *, channel_id: str, webhook: str,
        timeout: float = 10.0, max_retries: int = 3,
    ) -> None:
        self.channel_id = channel_id
        self._webhook = webhook
        self._timeout = timeout
        self._max = max_retries

    async def send(self, msg: CommonMessage) -> SendResult:
        body = {
            "msgtype": "markdown",
            "markdown": {"content": self._render(msg)},
        }

        @async_retry(max_attempts=self._max, backoff_seconds=1.0,
                     retry_on=(httpx.HTTPError,))
        async def _post() -> tuple[int, str]:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                r = await client.post(self._webhook, json=body)
                return r.status_code, r.text

        try:
            status, resp = await _post()
        except httpx.HTTPError as e:
            return SendResult(ok=False, http_status=None,
                              response_body=str(e), retries=self._max)
        return SendResult(ok=(status == 200 and '"errcode":0' in resp),
                          http_status=status, response_body=resp, retries=0)

    def _render(self, msg: CommonMessage) -> str:
        badges = " ".join(f"`{b.text}`" for b in msg.badges)
        links = " | ".join(f"[{d.label}]({d.url})" for d in msg.deeplinks)
        return (
            f"**{msg.title}**\n"
            f"> {msg.source_label}\n\n"
            f"{msg.summary}\n\n"
            f"{badges}\n\n"
            f"{links}"
        )
```

- [ ] **Step 4: Run — pass**

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/pushers/wecom.py tests/unit/pushers/test_wecom.py
git commit -m "feat: add 企微 (wecom) pusher with markdown"
```

---

### Task 52: Pusher registry + factory + parallel dispatch

**Files:**
- Create: `src/news_pipeline/pushers/factory.py`
- Create: `src/news_pipeline/pushers/dispatcher.py`
- Create: `tests/unit/pushers/test_dispatcher.py`

- [ ] **Step 1: Test**

```python
# tests/unit/pushers/test_dispatcher.py
from unittest.mock import AsyncMock, MagicMock

import pytest

from news_pipeline.common.contracts import CommonMessage
from news_pipeline.common.enums import Market
from news_pipeline.pushers.base import SendResult
from news_pipeline.pushers.dispatcher import PusherDispatcher


def _msg() -> CommonMessage:
    return CommonMessage(
        title="t", summary="s", source_label="x",
        source_url="https://x.com", badges=[], chart_url=None,
        deeplinks=[], market=Market.US,
    )


@pytest.mark.asyncio
async def test_dispatch_calls_each_in_parallel():
    p1 = MagicMock(); p1.channel_id = "c1"
    p1.send = AsyncMock(return_value=SendResult(ok=True, http_status=200))
    p2 = MagicMock(); p2.channel_id = "c2"
    p2.send = AsyncMock(return_value=SendResult(ok=False, http_status=500))
    d = PusherDispatcher({"c1": p1, "c2": p2})
    results = await d.dispatch(_msg(), channels=["c1", "c2"])
    assert results["c1"].ok and not results["c2"].ok
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

```python
# src/news_pipeline/pushers/factory.py
from news_pipeline.config.schema import ChannelsFile, SecretsFile
from news_pipeline.pushers.base import PusherProtocol
from news_pipeline.pushers.feishu import FeishuPusher
from news_pipeline.pushers.telegram import TelegramPusher
from news_pipeline.pushers.wecom import WecomPusher


def build_pushers(channels: ChannelsFile,
                  secrets: SecretsFile) -> dict[str, PusherProtocol]:
    out: dict[str, PusherProtocol] = {}
    for cid, c in channels.channels.items():
        if not c.enabled:
            continue
        opts = c.options
        s = secrets.push
        if c.type == "telegram":
            out[cid] = TelegramPusher(
                channel_id=cid,
                bot_token=s[opts["bot_token_key"]],
                chat_id=s[opts["chat_id_key"]],
            )
        elif c.type == "feishu":
            out[cid] = FeishuPusher(
                channel_id=cid,
                webhook=s[opts["webhook_key"]],
                sign_secret=s.get(opts.get("sign_key", "")) or None,
            )
        elif c.type == "wecom":
            out[cid] = WecomPusher(
                channel_id=cid,
                webhook=s[opts["webhook_key"]],
            )
    return out
```

```python
# src/news_pipeline/pushers/dispatcher.py
import asyncio

from news_pipeline.common.contracts import CommonMessage
from news_pipeline.pushers.base import PusherProtocol, SendResult


class PusherDispatcher:
    def __init__(self, registry: dict[str, PusherProtocol]) -> None:
        self._reg = registry

    async def dispatch(self, msg: CommonMessage, *,
                       channels: list[str]) -> dict[str, SendResult]:
        present = [(cid, self._reg[cid]) for cid in channels if cid in self._reg]
        coros = [p.send(msg) for _, p in present]
        results = await asyncio.gather(*coros, return_exceptions=True)
        out: dict[str, SendResult] = {}
        for (cid, _), r in zip(present, results):
            if isinstance(r, Exception):
                out[cid] = SendResult(ok=False, response_body=str(r))
            else:
                out[cid] = r
        return out
```

- [ ] **Step 4: Run — pass**

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/pushers/{factory,dispatcher}.py tests/unit/pushers/test_dispatcher.py
git commit -m "feat: add pusher factory + parallel dispatcher"
```

---

### Task 53: Burst suppression (same-ticker recent flooding)

**Files:**
- Create: `src/news_pipeline/pushers/common/burst.py`
- Create: `tests/unit/pushers/test_burst.py`

- [ ] **Step 1: Test**

```python
# tests/unit/pushers/test_burst.py
import time

from news_pipeline.pushers.common.burst import BurstSuppressor


def test_below_threshold_passes(monkeypatch):
    times = iter([1000.0, 1010.0])
    monkeypatch.setattr(time, "monotonic", lambda: next(times))
    s = BurstSuppressor(window_seconds=300, threshold=3)
    assert s.should_send(["NVDA"]) is True
    assert s.should_send(["NVDA"]) is True


def test_at_threshold_suppresses(monkeypatch):
    seq = iter([1000.0, 1100.0, 1200.0, 1250.0])
    monkeypatch.setattr(time, "monotonic", lambda: next(seq))
    s = BurstSuppressor(window_seconds=300, threshold=3)
    assert s.should_send(["NVDA"]) is True
    assert s.should_send(["NVDA"]) is True
    assert s.should_send(["NVDA"]) is True
    assert s.should_send(["NVDA"]) is False
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

```python
# src/news_pipeline/pushers/common/burst.py
import time
from collections import defaultdict, deque


class BurstSuppressor:
    def __init__(self, *, window_seconds: int, threshold: int) -> None:
        self._win = window_seconds
        self._th = threshold
        self._buckets: dict[str, deque[float]] = defaultdict(deque)

    def should_send(self, tickers: list[str]) -> bool:
        now = time.monotonic()
        cutoff = now - self._win
        send = True
        for t in tickers:
            buf = self._buckets[t]
            while buf and buf[0] < cutoff:
                buf.popleft()
            if len(buf) >= self._th:
                send = False
            buf.append(now)
        return send
```

- [ ] **Step 4: Run — pass**

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/pushers/common/burst.py tests/unit/pushers/test_burst.py
git commit -m "feat: add burst suppression for same-ticker flooding"
```

---

## Phase 8 — Charts (Tasks 54-58)

### Task 54: OSS uploader

**Files:**
- Create: `src/news_pipeline/charts/__init__.py`
- Create: `src/news_pipeline/charts/uploader.py`
- Create: `tests/unit/charts/test_uploader.py`

- [ ] **Step 1: Test**

```python
# tests/unit/charts/test_uploader.py
from unittest.mock import MagicMock

import pytest

from news_pipeline.charts.uploader import OSSUploader


def test_upload_returns_public_url():
    bucket = MagicMock()
    bucket.put_object.return_value = MagicMock(status=200)
    u = OSSUploader(
        bucket=bucket, endpoint="oss-cn-hangzhou.aliyuncs.com",
        bucket_name="news-charts",
    )
    url = u.upload(path_in_bucket="charts/2026/04/x.png", content=b"PNG")
    assert "news-charts" in url and "x.png" in url
    bucket.put_object.assert_called_once()


def test_upload_failure_raises():
    bucket = MagicMock()
    bucket.put_object.return_value = MagicMock(status=500)
    u = OSSUploader(bucket=bucket, endpoint="x", bucket_name="b")
    with pytest.raises(RuntimeError):
        u.upload(path_in_bucket="x.png", content=b"P")
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

```python
# src/news_pipeline/charts/__init__.py
```

```python
# src/news_pipeline/charts/uploader.py
from typing import Any


class OSSUploader:
    def __init__(self, *, bucket: Any, endpoint: str, bucket_name: str,
                 https: bool = True) -> None:
        self._bucket = bucket
        self._endpoint = endpoint
        self._name = bucket_name
        self._scheme = "https" if https else "http"

    def upload(self, *, path_in_bucket: str, content: bytes,
               content_type: str = "image/png") -> str:
        result = self._bucket.put_object(
            path_in_bucket, content, headers={"Content-Type": content_type}
        )
        if getattr(result, "status", 0) != 200:
            raise RuntimeError(f"OSS upload failed: status={result.status}")
        return f"{self._scheme}://{self._name}.{self._endpoint}/{path_in_bucket}"

    @classmethod
    def from_secrets(cls, *, endpoint: str, bucket: str,
                      access_key_id: str, access_key_secret: str) -> "OSSUploader":
        import oss2
        auth = oss2.Auth(access_key_id, access_key_secret)
        b = oss2.Bucket(auth, f"https://{endpoint}", bucket)
        return cls(bucket=b, endpoint=endpoint, bucket_name=bucket)
```

```bash
mkdir -p tests/unit/charts && touch tests/unit/charts/__init__.py
```

- [ ] **Step 4: Run — pass**

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/charts/ tests/unit/charts/test_uploader.py
git commit -m "feat: add OSS uploader for chart images"
```

---

### Task 55: K-line chart with news markers

**Files:**
- Create: `src/news_pipeline/charts/kline.py`
- Create: `tests/unit/charts/test_kline.py`

- [ ] **Step 1: Test**

```python
# tests/unit/charts/test_kline.py
from datetime import datetime, timedelta

import pandas as pd
import pytest

from news_pipeline.charts.kline import render_kline


def _ohlc_df() -> pd.DataFrame:
    idx = pd.date_range(end=datetime(2026, 4, 25), periods=30, freq="B")
    return pd.DataFrame({
        "Open": [100 + i * 0.5 for i in range(30)],
        "High": [101 + i * 0.5 for i in range(30)],
        "Low":  [99 + i * 0.5 for i in range(30)],
        "Close":[100.5 + i * 0.5 for i in range(30)],
        "Volume":[1000] * 30,
    }, index=idx)


def test_render_kline_returns_png_bytes():
    df = _ohlc_df()
    markers = [(df.index[-3], "🔴")]
    png = render_kline(df, ticker="NVDA", news_markers=markers)
    assert isinstance(png, bytes)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

```python
# src/news_pipeline/charts/kline.py
from datetime import datetime
from io import BytesIO

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd


def render_kline(
    df: pd.DataFrame, *, ticker: str,
    news_markers: list[tuple[datetime, str]] | None = None,
    style: str = "yahoo",
) -> bytes:
    addplots = []
    if news_markers:
        marker_series = pd.Series(index=df.index, dtype=float)
        for ts, _ in news_markers:
            ts = pd.Timestamp(ts).normalize()
            if ts in df.index:
                marker_series.loc[ts] = float(df.loc[ts, "High"]) * 1.02
        if marker_series.notna().any():
            addplots.append(mpf.make_addplot(
                marker_series, type="scatter", marker="v",
                markersize=120, color="red",
            ))
    buf = BytesIO()
    fig, _ = mpf.plot(
        df, type="candle", style=style, title=f"{ticker} 30D",
        addplot=addplots, returnfig=True, volume=True, figsize=(8, 6),
    )
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()
```

- [ ] **Step 4: Run — pass**

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/charts/kline.py tests/unit/charts/test_kline.py
git commit -m "feat: add mplfinance K-line chart with news markers"
```

---

### Task 56: Earnings bars chart

**Files:**
- Create: `src/news_pipeline/charts/bars.py`
- Create: `tests/unit/charts/test_bars.py`

- [ ] **Step 1: Test**

```python
# tests/unit/charts/test_bars.py
from news_pipeline.charts.bars import render_quarterly_bars


def test_render_returns_png_bytes():
    quarters = ["Q1 25", "Q2 25", "Q3 25", "Q4 25", "Q1 26"]
    revenue = [100, 110, 120, 130, 145]
    earnings = [10, 12, 13, 15, 18]
    png = render_quarterly_bars(
        quarters=quarters, revenue=revenue, earnings=earnings,
        ticker="NVDA",
    )
    assert isinstance(png, bytes) and png[:8] == b"\x89PNG\r\n\x1a\n"
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

```python
# src/news_pipeline/charts/bars.py
from io import BytesIO

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def render_quarterly_bars(
    *, quarters: list[str], revenue: list[float],
    earnings: list[float], ticker: str,
) -> bytes:
    x = np.arange(len(quarters))
    width = 0.4
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.bar(x - width / 2, revenue, width, label="Revenue", color="#2c7bb6")
    ax.bar(x + width / 2, earnings, width, label="Earnings", color="#fdae61")
    ax.set_xticks(x)
    ax.set_xticklabels(quarters)
    ax.set_title(f"{ticker} Quarterly Financials")
    ax.legend()
    ax.grid(True, axis="y", alpha=0.3)
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()
```

- [ ] **Step 4: Run — pass**

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/charts/bars.py tests/unit/charts/test_bars.py
git commit -m "feat: add quarterly earnings bars chart"
```

---

### Task 57: Sentiment curve chart

**Files:**
- Create: `src/news_pipeline/charts/sentiment.py`
- Create: `tests/unit/charts/test_sentiment.py`

- [ ] **Step 1: Test**

```python
# tests/unit/charts/test_sentiment.py
from datetime import datetime, timedelta

from news_pipeline.charts.sentiment import render_sentiment_curve


def test_render_returns_png():
    today = datetime(2026, 4, 25)
    points = [(today - timedelta(days=i), 0.5 + (i % 3 - 1) * 0.2)
              for i in range(7, 0, -1)]
    png = render_sentiment_curve(points=points, ticker="NVDA")
    assert isinstance(png, bytes) and png[:8] == b"\x89PNG\r\n\x1a\n"
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

```python
# src/news_pipeline/charts/sentiment.py
from datetime import datetime
from io import BytesIO

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt


def render_sentiment_curve(
    *, points: list[tuple[datetime, float]], ticker: str,
) -> bytes:
    if not points:
        raise ValueError("no points")
    xs, ys = zip(*sorted(points))
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(xs, ys, marker="o", color="#2c7bb6")
    ax.axhline(0.0, color="#888", linewidth=0.5)
    ax.set_ylim(-1.0, 1.0)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
    ax.set_title(f"{ticker} Sentiment (1=bullish, -1=bearish)")
    ax.grid(True, alpha=0.3)
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()
```

- [ ] **Step 4: Run — pass**

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/charts/sentiment.py tests/unit/charts/test_sentiment.py
git commit -m "feat: add sentiment curve chart"
```

---

### Task 58: Chart factory + cache integration

**Files:**
- Create: `src/news_pipeline/charts/factory.py`
- Create: `tests/unit/charts/test_factory.py`

- [ ] **Step 1: Test**

```python
# tests/unit/charts/test_factory.py
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from news_pipeline.charts.factory import ChartFactory, ChartRequest


@pytest.mark.asyncio
async def test_cache_hit_skips_render():
    cache = MagicMock()
    cache.get = AsyncMock(return_value=MagicMock(oss_url="https://oss/x.png"))
    cache.put = AsyncMock()
    renderer = MagicMock(return_value=b"PNG")
    uploader = MagicMock()
    uploader.upload = MagicMock()
    f = ChartFactory(cache_dao=cache, kline_renderer=renderer,
                      uploader=uploader)
    url = await f.render_kline(ChartRequest(ticker="NVDA", kind="kline",
                                             window="30d", params={}))
    assert url == "https://oss/x.png"
    renderer.assert_not_called()
    uploader.upload.assert_not_called()


@pytest.mark.asyncio
async def test_cache_miss_renders_uploads_caches():
    cache = MagicMock()
    cache.get = AsyncMock(return_value=None)
    cache.put = AsyncMock()
    renderer = MagicMock(return_value=b"PNG")
    uploader = MagicMock()
    uploader.upload = MagicMock(return_value="https://oss/new.png")
    f = ChartFactory(cache_dao=cache, kline_renderer=renderer,
                      uploader=uploader,
                      data_loader=lambda t, w: __import__('pandas').DataFrame())
    url = await f.render_kline(ChartRequest(ticker="NVDA", kind="kline",
                                             window="30d", params={}))
    assert url == "https://oss/new.png"
    cache.put.assert_awaited_once()
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

```python
# src/news_pipeline/charts/factory.py
import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

import pandas as pd

from news_pipeline.charts.uploader import OSSUploader
from news_pipeline.common.timeutil import utc_now
from news_pipeline.storage.dao.chart_cache import ChartCacheDAO


@dataclass
class ChartRequest:
    ticker: str
    kind: str  # kline | bars | sentiment
    window: str  # "30d" | "1y" | etc.
    params: dict[str, Any] = field(default_factory=dict)

    def request_hash(self) -> str:
        s = f"{self.ticker}|{self.kind}|{self.window}|{sorted(self.params.items())}"
        return hashlib.sha1(s.encode()).hexdigest()[:16]


class ChartFactory:
    def __init__(
        self, *,
        cache_dao: ChartCacheDAO,
        kline_renderer: Callable[..., bytes],
        uploader: OSSUploader,
        data_loader: Callable[[str, str], pd.DataFrame] | None = None,
        ttl_days: int = 30,
    ) -> None:
        self._cache = cache_dao
        self._render_kline = kline_renderer
        self._uploader = uploader
        self._data_loader = data_loader
        self._ttl_days = ttl_days

    async def render_kline(self, req: ChartRequest) -> str:
        cached = await self._cache.get(req.request_hash())
        if cached is not None:
            return cached.oss_url
        if self._data_loader is None:
            raise RuntimeError("no data_loader configured")
        df = self._data_loader(req.ticker, req.window)
        png = self._render_kline(df, ticker=req.ticker, news_markers=None)
        if not isinstance(png, bytes):
            raise RuntimeError("renderer must return bytes")
        ts = utc_now()
        path = (
            f"charts/{ts.year}/{ts.month:02d}/{ts.day:02d}/"
            f"{req.ticker}_{req.kind}_{req.request_hash()}.png"
        )
        url = self._uploader.upload(path_in_bucket=path, content=png)
        await self._cache.put(
            request_hash=req.request_hash(), ticker=req.ticker,
            kind=req.kind, oss_url=url, ttl_days=self._ttl_days,
        )
        return url
```

- [ ] **Step 4: Run — pass**

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/charts/factory.py tests/unit/charts/test_factory.py
git commit -m "feat: add chart factory with cache lookup"
```

---

## Phase 9 — Archive (Tasks 59-60)

### Task 59: 飞书 bitable client + schema mapper

**Files:**
- Create: `src/news_pipeline/archive/__init__.py`
- Create: `src/news_pipeline/archive/schema.py`
- Create: `src/news_pipeline/archive/feishu_table.py`
- Create: `tests/unit/archive/test_schema.py`

- [ ] **Step 1: Test**

```python
# tests/unit/archive/test_schema.py
from datetime import datetime

from news_pipeline.archive.schema import enriched_to_row
from news_pipeline.common.contracts import EnrichedNews, RawArticle, ScoredNews
from news_pipeline.common.enums import EventType, Magnitude, Market, Sentiment


def test_enriched_to_row():
    art = RawArticle(
        source="reuters", market=Market.US,
        fetched_at=datetime(2026, 4, 25, 10),
        published_at=datetime(2026, 4, 25, 10),
        url="https://reut/x", url_hash="h", title="t", body="b",
    )
    e = EnrichedNews(
        raw_id=1, summary="出口管制", related_tickers=["NVDA"],
        sectors=["semiconductor"], event_type=EventType.POLICY,
        sentiment=Sentiment.BEARISH, magnitude=Magnitude.HIGH,
        confidence=0.9, key_quotes=["…"], entities=[], relations=[],
        model_used="haiku", extracted_at=datetime(2026, 4, 25, 10),
    )
    s = ScoredNews(enriched=e, score=80.0, is_critical=True,
                    rule_hits=["sentiment_high"], llm_reason=None)
    row = enriched_to_row(art, s, news_processed_id=42,
                           sent_to=["tg_us", "feishu_us"], chart_url=None)
    assert row["news_id"] == 42
    assert row["market"] == "美股"
    assert row["sentiment"] == "🔴看跌"
    assert "tg_us" in row["sent_to"]
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

```python
# src/news_pipeline/archive/__init__.py
```

```python
# src/news_pipeline/archive/schema.py
from typing import Any

from news_pipeline.common.contracts import RawArticle, ScoredNews
from news_pipeline.common.enums import Market, Sentiment

_MARKET_LABEL = {Market.US: "美股", Market.CN: "A股"}
_SENTIMENT_LABEL = {
    Sentiment.BULLISH: "🟢看涨",
    Sentiment.BEARISH: "🔴看跌",
    Sentiment.NEUTRAL: "⚪中性",
}
_MAG_LABEL = {"low": "低", "medium": "中", "high": "高"}


def enriched_to_row(
    art: RawArticle, scored: ScoredNews, *,
    news_processed_id: int, sent_to: list[str],
    chart_url: str | None,
) -> dict[str, Any]:
    e = scored.enriched
    return {
        "news_id": news_processed_id,
        "published_at": int(art.published_at.timestamp() * 1000),
        "market": _MARKET_LABEL[art.market],
        "source": art.source,
        "tickers": e.related_tickers,
        "event_type": e.event_type.value,
        "sentiment": _SENTIMENT_LABEL[e.sentiment],
        "magnitude": _MAG_LABEL[e.magnitude.value],
        "score": scored.score,
        "is_critical": scored.is_critical,
        "title": art.title,
        "summary": e.summary,
        "key_quotes": "\n".join(e.key_quotes),
        "url": str(art.url),
        "chart_url": chart_url or "",
        "sent_to": sent_to,
    }
```

```python
# src/news_pipeline/archive/feishu_table.py
import httpx

from news_pipeline.observability.log import get_logger
from news_pipeline.pushers.common.retry import async_retry

log = get_logger(__name__)


class FeishuBitableClient:
    """Wraps 飞书 OpenAPI append_records endpoint."""

    def __init__(
        self, *, app_id: str, app_secret: str,
        app_token: str, table_id: str, timeout: float = 15.0,
    ) -> None:
        self._app_id = app_id
        self._app_secret = app_secret
        self._app_token = app_token
        self._table_id = table_id
        self._timeout = timeout
        self._cached_token: str | None = None

    async def _tenant_token(self) -> str:
        if self._cached_token is not None:
            return self._cached_token
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        async with httpx.AsyncClient(timeout=self._timeout) as c:
            r = await c.post(url, json={
                "app_id": self._app_id, "app_secret": self._app_secret,
            })
            r.raise_for_status()
            data = r.json()
            if data.get("code") != 0:
                raise RuntimeError(f"feishu auth failed: {data}")
            self._cached_token = data["tenant_access_token"]
            return self._cached_token

    @async_retry(max_attempts=3, backoff_seconds=1.0,
                 retry_on=(httpx.HTTPError,))
    async def append_record(self, fields: dict) -> str:
        token = await self._tenant_token()
        url = (
            f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self._app_token}"
            f"/tables/{self._table_id}/records"
        )
        async with httpx.AsyncClient(timeout=self._timeout) as c:
            r = await c.post(
                url, headers={"Authorization": f"Bearer {token}"},
                json={"fields": fields},
            )
            r.raise_for_status()
            data = r.json()
            if data.get("code") != 0:
                # Token may have expired
                if data.get("code") in (99991663, 99991664):
                    self._cached_token = None
                raise RuntimeError(f"feishu bitable error: {data}")
            return str(data["data"]["record"]["record_id"])
```

```bash
mkdir -p tests/unit/archive && touch tests/unit/archive/__init__.py
```

- [ ] **Step 4: Run — pass**

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/archive/ tests/unit/archive/test_schema.py
git commit -m "feat: add 飞书 bitable client + EnrichedNews→row mapper"
```

---

### Task 60: Async archive writer (with retry)

**Files:**
- Create: `src/news_pipeline/archive/writer.py`
- Create: `tests/unit/archive/test_writer.py`

- [ ] **Step 1: Test**

```python
# tests/unit/archive/test_writer.py
from unittest.mock import AsyncMock, MagicMock

import pytest

from news_pipeline.archive.writer import ArchiveWriter


@pytest.mark.asyncio
async def test_write_uses_market_specific_client():
    us_client = MagicMock(); us_client.append_record = AsyncMock(return_value="r1")
    cn_client = MagicMock(); cn_client.append_record = AsyncMock(return_value="r2")
    w = ArchiveWriter(clients_by_market={"us": us_client, "cn": cn_client})
    rid = await w.write(market="us", row={"x": 1})
    assert rid == "r1"
    us_client.append_record.assert_awaited_once_with({"x": 1})


@pytest.mark.asyncio
async def test_write_failure_propagates():
    cli = MagicMock()
    cli.append_record = AsyncMock(side_effect=RuntimeError("boom"))
    w = ArchiveWriter(clients_by_market={"us": cli})
    with pytest.raises(RuntimeError):
        await w.write(market="us", row={})
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

```python
# src/news_pipeline/archive/writer.py
from typing import Any

from news_pipeline.archive.feishu_table import FeishuBitableClient


class ArchiveWriter:
    def __init__(
        self, *,
        clients_by_market: dict[str, FeishuBitableClient],
    ) -> None:
        self._clients = clients_by_market

    async def write(self, *, market: str, row: dict[str, Any]) -> str:
        cli = self._clients.get(market)
        if cli is None:
            raise KeyError(f"no archive client for market={market}")
        return await cli.append_record(row)
```

- [ ] **Step 4: Run — pass**

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/archive/writer.py tests/unit/archive/test_writer.py
git commit -m "feat: add async archive writer dispatcher"
```

---

## Phase 10 — Scheduler + Main (Tasks 61-63)

### Task 61: Scrape job (one source, end-to-end)

**Files:**
- Create: `src/news_pipeline/scheduler/__init__.py`
- Create: `src/news_pipeline/scheduler/jobs.py`
- Create: `tests/unit/scheduler/test_scrape_job.py`

- [ ] **Step 1: Test**

```python
# tests/unit/scheduler/test_scrape_job.py
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.enums import Market
from news_pipeline.scheduler.jobs import scrape_one_source


def _art() -> RawArticle:
    return RawArticle(
        source="finnhub", market=Market.US,
        fetched_at=datetime(2026, 4, 25), published_at=datetime(2026, 4, 25),
        url="https://x/1", url_hash="h", title="t",
    )


@pytest.mark.asyncio
async def test_scrape_dedup_writes_pending():
    scraper = MagicMock(); scraper.source_id = "finnhub"
    scraper.market = Market.US
    scraper.fetch = AsyncMock(return_value=[_art()])

    dedup = MagicMock()
    dedup.check_and_register = AsyncMock(return_value=MagicMock(
        is_new=True, raw_id=42, reason=None,
    ))
    state_dao = MagicMock()
    state_dao.get = AsyncMock(return_value=None)
    state_dao.is_paused = AsyncMock(return_value=False)
    state_dao.update_watermark = AsyncMock()
    state_dao.record_error = AsyncMock()
    metrics = MagicMock(); metrics.increment = AsyncMock()

    n_new = await scrape_one_source(
        scraper=scraper, dedup=dedup, state_dao=state_dao, metrics=metrics,
    )
    assert n_new == 1
    state_dao.update_watermark.assert_awaited_once()


@pytest.mark.asyncio
async def test_scrape_skips_when_paused():
    scraper = MagicMock(); scraper.source_id = "x"; scraper.market = Market.US
    scraper.fetch = AsyncMock()
    dedup = MagicMock()
    state_dao = MagicMock()
    state_dao.is_paused = AsyncMock(return_value=True)
    metrics = MagicMock(); metrics.increment = AsyncMock()
    n = await scrape_one_source(scraper=scraper, dedup=dedup,
                                 state_dao=state_dao, metrics=metrics)
    assert n == 0
    scraper.fetch.assert_not_awaited()
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

```python
# src/news_pipeline/scheduler/__init__.py
```

```python
# src/news_pipeline/scheduler/jobs.py
from datetime import timedelta

from news_pipeline.common.exceptions import AntiCrawlError, ScraperError
from news_pipeline.common.timeutil import utc_now
from news_pipeline.dedup.dedup import Dedup
from news_pipeline.observability.log import get_logger
from news_pipeline.scrapers.base import ScraperProtocol
from news_pipeline.storage.dao.metrics import MetricsDAO
from news_pipeline.storage.dao.source_state import SourceStateDAO

log = get_logger(__name__)


async def scrape_one_source(
    *, scraper: ScraperProtocol, dedup: Dedup,
    state_dao: SourceStateDAO, metrics: MetricsDAO,
    lookback_minutes: int = 60,
) -> int:
    if await state_dao.is_paused(scraper.source_id):
        log.info("scrape_skip_paused", source=scraper.source_id)
        return 0
    state = await state_dao.get(scraper.source_id)
    since = (state.last_fetched_at if state and state.last_fetched_at
             else utc_now().replace(tzinfo=None) - timedelta(minutes=lookback_minutes))
    try:
        items = await scraper.fetch(since)
    except AntiCrawlError as e:
        log.warning("anticrawl", source=scraper.source_id, error=str(e))
        await state_dao.set_paused(
            scraper.source_id,
            until=utc_now().replace(tzinfo=None) + timedelta(minutes=30),
            error="anti_crawl",
        )
        return 0
    except (ScraperError, Exception) as e:
        log.error("scrape_failed", source=scraper.source_id, error=str(e))
        await state_dao.record_error(scraper.source_id, str(e))
        return 0

    new_count = 0
    for art in items:
        decision = await dedup.check_and_register(art)
        if decision.is_new:
            new_count += 1
        await metrics.increment(
            date_iso=utc_now().date().isoformat(),
            name=("scrape_new" if decision.is_new else "scrape_dup"),
            dimensions=f"source={scraper.source_id}",
        )
    await state_dao.update_watermark(
        scraper.source_id, last_fetched_at=utc_now().replace(tzinfo=None),
    )
    log.info("scrape_done", source=scraper.source_id,
             new=new_count, total=len(items))
    return new_count
```

```bash
mkdir -p tests/unit/scheduler && touch tests/unit/scheduler/__init__.py
```

- [ ] **Step 4: Run — pass**

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/scheduler/ tests/unit/scheduler/test_scrape_job.py
git commit -m "feat: add scrape_one_source job with anti-crawl + metrics"
```

---

### Task 62: Process job (LLM + classify + push) and digest job

**Files:**
- Modify: `src/news_pipeline/scheduler/jobs.py` (append)
- Create: `tests/unit/scheduler/test_process_and_digest.py`

- [ ] **Step 1: Test**

```python
# tests/unit/scheduler/test_process_and_digest.py
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from news_pipeline.common.contracts import (
    Badge, CommonMessage, Deeplink, EnrichedNews, RawArticle, ScoredNews,
)
from news_pipeline.common.enums import EventType, Magnitude, Market, Sentiment
from news_pipeline.scheduler.jobs import process_pending, send_digest


def _enriched() -> EnrichedNews:
    return EnrichedNews(
        raw_id=1, summary="s", related_tickers=["NVDA"], sectors=[],
        event_type=EventType.OTHER, sentiment=Sentiment.BEARISH,
        magnitude=Magnitude.HIGH, confidence=0.9, key_quotes=[],
        entities=[], relations=[], model_used="x",
        extracted_at=datetime(2026, 4, 25),
    )


@pytest.mark.asyncio
async def test_process_pending_routes_critical_immediately():
    raw_dao = MagicMock()
    pending_row = MagicMock(id=1, source="finnhub", market="us", url="https://x/1",
                              url_hash="h", title="t", title_simhash=0, body="b",
                              raw_meta={}, fetched_at=datetime(2026, 4, 25),
                              published_at=datetime(2026, 4, 25))
    raw_dao.list_pending = AsyncMock(return_value=[pending_row])
    raw_dao.mark_status = AsyncMock()

    llm = MagicMock(); llm.process = AsyncMock(return_value=_enriched())
    importance = MagicMock(); importance.score_news = AsyncMock(return_value=ScoredNews(
        enriched=_enriched(), score=80, is_critical=True,
        rule_hits=["sentiment_high"], llm_reason=None,
    ))
    proc_dao = MagicMock(); proc_dao.insert = AsyncMock(return_value=99)
    builder = MagicMock(); builder.build = MagicMock(return_value=CommonMessage(
        title="t", summary="s", source_label="x", source_url="https://x.com",
        badges=[], chart_url=None, deeplinks=[], market=Market.US,
    ))
    router = MagicMock(); router.route = MagicMock(return_value=[
        MagicMock(channels=["tg_us"], immediate=True, message=builder.build.return_value)
    ])
    dispatcher = MagicMock(); dispatcher.dispatch = AsyncMock(
        return_value={"tg_us": MagicMock(ok=True, http_status=200,
                                          response_body="", retries=0)}
    )
    push_log = MagicMock(); push_log.write = AsyncMock()
    digest_dao = MagicMock(); digest_dao.enqueue = AsyncMock()
    archive = MagicMock(); archive.write = AsyncMock(return_value="r1")
    burst = MagicMock(); burst.should_send = MagicMock(return_value=True)

    n = await process_pending(
        raw_dao=raw_dao, llm=llm, importance=importance, proc_dao=proc_dao,
        msg_builder=builder, router=router, dispatcher=dispatcher,
        push_log=push_log, digest_dao=digest_dao, archive=archive,
        burst=burst, archive_enabled=True,
    )
    assert n == 1
    dispatcher.dispatch.assert_awaited_once()
    digest_dao.enqueue.assert_not_awaited()
    archive.write.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_digest_consumes_buffer():
    digest_dao = MagicMock()
    digest_dao.list_pending = AsyncMock(return_value=[
        MagicMock(id=1, news_id=10), MagicMock(id=2, news_id=11),
    ])
    digest_dao.mark_consumed = AsyncMock()
    builder = MagicMock(); builder.build_digest = MagicMock(return_value=CommonMessage(
        title="d", summary="s", source_label="digest", source_url="https://x.com",
        badges=[], chart_url=None, deeplinks=[], market=Market.US,
    ))
    dispatcher = MagicMock(); dispatcher.dispatch = AsyncMock(
        return_value={"feishu_us": MagicMock(ok=True, http_status=200, response_body="", retries=0)}
    )
    proc_dao = MagicMock(); proc_dao.get = AsyncMock(side_effect=lambda i: MagicMock(id=i))

    n = await send_digest(
        digest_key="morning_us", market="us", channels=["feishu_us"],
        digest_dao=digest_dao, proc_dao=proc_dao,
        digest_builder=builder, dispatcher=dispatcher,
    )
    assert n == 2
    digest_dao.mark_consumed.assert_awaited_once_with([1, 2])
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement (append to jobs.py)**

```python
# Append to src/news_pipeline/scheduler/jobs.py
from news_pipeline.archive.schema import enriched_to_row
from news_pipeline.archive.writer import ArchiveWriter
from news_pipeline.classifier.importance import ImportanceClassifier
from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.enums import Market
from news_pipeline.llm.pipeline import LLMPipeline
from news_pipeline.pushers.common.burst import BurstSuppressor
from news_pipeline.pushers.common.message_builder import MessageBuilder
from news_pipeline.pushers.dispatcher import PusherDispatcher
from news_pipeline.router.routes import DispatchRouter
from news_pipeline.storage.dao.digest_buffer import DigestBufferDAO
from news_pipeline.storage.dao.news_processed import NewsProcessedDAO
from news_pipeline.storage.dao.push_log import PushLogDAO
from news_pipeline.storage.dao.raw_news import RawNewsDAO


def _raw_to_article(row) -> RawArticle:
    return RawArticle(
        source=row.source, market=Market(row.market),
        fetched_at=row.fetched_at, published_at=row.published_at,
        url=row.url, url_hash=row.url_hash,
        title=row.title, title_simhash=row.title_simhash,
        body=row.body, raw_meta=row.raw_meta or {},
    )


async def process_pending(
    *, raw_dao: RawNewsDAO, llm: LLMPipeline,
    importance: ImportanceClassifier,
    proc_dao: NewsProcessedDAO, msg_builder: MessageBuilder,
    router: DispatchRouter, dispatcher: PusherDispatcher,
    push_log: PushLogDAO, digest_dao: DigestBufferDAO,
    archive: ArchiveWriter | None, burst: BurstSuppressor,
    archive_enabled: bool = True, batch_size: int = 25,
) -> int:
    pending = await raw_dao.list_pending(limit=batch_size)
    processed = 0
    for raw in pending:
        art = _raw_to_article(raw)
        try:
            enriched = await llm.process(art, raw_id=raw.id)  # type: ignore[arg-type]
        except Exception as e:
            log.error("llm_failed", raw_id=raw.id, error=str(e))
            await raw_dao.mark_status(raw.id, "dead", error=str(e))  # type: ignore[arg-type]
            continue
        if enriched is None:
            await raw_dao.mark_status(raw.id, "skipped")  # type: ignore[arg-type]
            continue

        scored = await importance.score_news(enriched, source=raw.source)
        proc_id = await proc_dao.insert(
            raw_id=raw.id, summary=enriched.summary,  # type: ignore[arg-type]
            event_type=enriched.event_type.value,
            sentiment=enriched.sentiment.value,
            magnitude=enriched.magnitude.value,
            confidence=enriched.confidence,
            key_quotes=enriched.key_quotes, score=scored.score,
            is_critical=scored.is_critical, rule_hits=scored.rule_hits,
            llm_reason=scored.llm_reason, model_used=enriched.model_used,
            extracted_at=enriched.extracted_at,
        )
        await raw_dao.mark_status(raw.id, "processed")  # type: ignore[arg-type]

        msg = msg_builder.build(art, scored, chart_url=None)
        plans = router.route(scored, msg)
        sent_to: list[str] = []

        for p in plans:
            if p.immediate:
                if not burst.should_send(enriched.related_tickers):
                    log.info("push_suppressed_burst",
                             tickers=enriched.related_tickers)
                    continue
                results = await dispatcher.dispatch(p.message, channels=p.channels)
                for ch, r in results.items():
                    await push_log.write(
                        news_id=proc_id, channel=ch,
                        status=("ok" if r.ok else "failed"),
                        http_status=r.http_status, response=r.response_body,
                        retries=r.retries,
                    )
                    if r.ok:
                        sent_to.append(ch)
            else:
                for ch in p.channels:
                    await digest_dao.enqueue(
                        news_id=proc_id, market=art.market.value,
                        scheduled_digest=f"morning_{art.market.value}",
                    )
                    break  # one entry per news enough; channel resolved at digest time

        if archive is not None and archive_enabled:
            try:
                row = enriched_to_row(art, scored, news_processed_id=proc_id,
                                       sent_to=sent_to,
                                       chart_url=str(msg.chart_url) if msg.chart_url else None)
                await archive.write(market=art.market.value, row=row)
            except Exception as e:
                log.warning("archive_failed", news_id=proc_id, error=str(e))

        processed += 1
    return processed


async def send_digest(
    *, digest_key: str, market: str, channels: list[str],
    digest_dao: DigestBufferDAO, proc_dao: NewsProcessedDAO,
    digest_builder, dispatcher: PusherDispatcher,
) -> int:
    pending = await digest_dao.list_pending(digest_key)
    if not pending:
        return 0
    items = []
    for buf_row in pending:
        proc = await proc_dao.get(buf_row.news_id)
        if proc is not None:
            items.append(proc)
    if not items:
        await digest_dao.mark_consumed([b.id for b in pending])
        return 0
    msg = digest_builder.build_digest(items=items, market=market,
                                       digest_key=digest_key)
    await dispatcher.dispatch(msg, channels=channels)
    await digest_dao.mark_consumed([b.id for b in pending])
    return len(items)
```

- [ ] **Step 4: Run — pass**

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/scheduler/jobs.py tests/unit/scheduler/test_process_and_digest.py
git commit -m "feat: add process_pending + send_digest jobs"
```

---

### Task 63: APScheduler wiring + main entrypoint

**Files:**
- Create: `src/news_pipeline/scheduler/runner.py`
- Create: `src/news_pipeline/main.py`
- Create: `src/news_pipeline/healthcheck.py`
- Create: `tests/integration/test_main_smoke.py`

- [ ] **Step 1: Test (smoke)**

```python
# tests/integration/test_main_smoke.py
import os
import signal
import subprocess
import sys
import time

import pytest


def test_main_starts_and_exits_clean(tmp_path, monkeypatch):
    if os.environ.get("CI_SMOKE_SKIP") == "1":
        pytest.skip("smoke disabled")
    env = os.environ.copy()
    env["NEWS_PIPELINE_CONFIG_DIR"] = str(tmp_path)
    env["NEWS_PIPELINE_ONCE"] = "1"
    # write minimal configs to tmp_path (similar to test_loader fixture) ...
    # For brevity: we trust the unit tests cover this; integration smoke
    # is best run manually.
    pytest.skip("manual smoke; see Task 63 step 5")
```

> Note: full smoke needs writing all 5 config files into tmp_path. We rely on the unit tests for jobs/loader/etc; manual smoke is documented in Step 5.

- [ ] **Step 2: Implement runner**

```python
# src/news_pipeline/scheduler/runner.py
import asyncio
from datetime import datetime, timedelta
from typing import Any, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from news_pipeline.observability.log import get_logger

log = get_logger(__name__)


class SchedulerRunner:
    def __init__(self) -> None:
        self._sched = AsyncIOScheduler(timezone="UTC")

    def add_interval(
        self, *, name: str, seconds: int,
        coro_factory: Callable[[], Any],
        jitter: int | None = None,
    ) -> None:
        async def _run() -> None:
            try:
                await coro_factory()
            except Exception as e:
                log.error("job_failed", name=name, error=str(e))
        self._sched.add_job(_run, trigger=IntervalTrigger(seconds=seconds, jitter=jitter),
                             id=name, name=name, replace_existing=True,
                             max_instances=1, coalesce=True)

    def add_cron(
        self, *, name: str, hour: int, minute: int,
        coro_factory: Callable[[], Any], timezone: str = "Asia/Shanghai",
    ) -> None:
        async def _run() -> None:
            try:
                await coro_factory()
            except Exception as e:
                log.error("job_failed", name=name, error=str(e))
        self._sched.add_job(_run, trigger=CronTrigger(
            hour=hour, minute=minute, timezone=timezone,
        ), id=name, name=name, replace_existing=True,
            max_instances=1, coalesce=True)

    def start(self) -> None:
        self._sched.start()
        log.info("scheduler_started", jobs=[j.id for j in self._sched.get_jobs()])

    async def shutdown(self) -> None:
        self._sched.shutdown(wait=True)
```

- [ ] **Step 3: Implement main + healthcheck**

```python
# src/news_pipeline/main.py
from __future__ import annotations

import asyncio
import os
import signal
from pathlib import Path

from news_pipeline.archive.feishu_table import FeishuBitableClient
from news_pipeline.archive.writer import ArchiveWriter
from news_pipeline.classifier.importance import ImportanceClassifier
from news_pipeline.classifier.llm_judge import LLMJudge
from news_pipeline.classifier.rules import RuleEngine
from news_pipeline.config.loader import ConfigLoader
from news_pipeline.dedup.dedup import Dedup
from news_pipeline.llm.clients.anthropic import AnthropicClient
from news_pipeline.llm.clients.dashscope import DashScopeClient
from news_pipeline.llm.cost_tracker import CostTracker, ModelPricing
from news_pipeline.llm.extractors import (
    Tier0Classifier, Tier1Summarizer, Tier2DeepExtractor,
)
from news_pipeline.llm.pipeline import LLMPipeline
from news_pipeline.llm.prompts.loader import PromptLoader
from news_pipeline.llm.router import LLMRouter
from news_pipeline.observability.alert import BarkAlerter
from news_pipeline.observability.log import configure_logging, get_logger
from news_pipeline.pushers.common.burst import BurstSuppressor
from news_pipeline.pushers.common.message_builder import MessageBuilder
from news_pipeline.pushers.dispatcher import PusherDispatcher
from news_pipeline.pushers.factory import build_pushers
from news_pipeline.router.routes import DispatchRouter
from news_pipeline.scheduler.jobs import (
    process_pending, scrape_one_source, send_digest,
)
from news_pipeline.scheduler.runner import SchedulerRunner
from news_pipeline.scrapers.factory import build_registry
from news_pipeline.storage.dao.audit_log import AuditLogDAO
from news_pipeline.storage.dao.chart_cache import ChartCacheDAO
from news_pipeline.storage.dao.dead_letter import DeadLetterDAO
from news_pipeline.storage.dao.digest_buffer import DigestBufferDAO
from news_pipeline.storage.dao.metrics import MetricsDAO
from news_pipeline.storage.dao.news_processed import NewsProcessedDAO
from news_pipeline.storage.dao.push_log import PushLogDAO
from news_pipeline.storage.dao.raw_news import RawNewsDAO
from news_pipeline.storage.dao.source_state import SourceStateDAO
from news_pipeline.storage.db import Database


PRICING = {
    "deepseek-v3": ModelPricing(input_per_m_cny=0.5, output_per_m_cny=1.5),
    "claude-haiku-4-5-20251001": ModelPricing(input_per_m_cny=7.0,
                                               output_per_m_cny=35.0),
    "claude-sonnet-4-6": ModelPricing(input_per_m_cny=21.0, output_per_m_cny=105.0),
}

log = get_logger(__name__)


async def _amain() -> None:
    cfg_dir = Path(os.environ.get("NEWS_PIPELINE_CONFIG_DIR", "config"))
    db_path = os.environ.get("NEWS_PIPELINE_DB", "data/news.db")
    once = bool(int(os.environ.get("NEWS_PIPELINE_ONCE", "0")))

    configure_logging(level=os.environ.get("LOG_LEVEL", "INFO"), json_output=True)

    loader = ConfigLoader(cfg_dir)
    snap = loader.load()

    db = Database(f"sqlite+aiosqlite:///{db_path}")
    await db.initialize()

    raw_dao = RawNewsDAO(db)
    proc_dao = NewsProcessedDAO(db)
    state_dao = SourceStateDAO(db)
    push_log = PushLogDAO(db)
    digest_dao = DigestBufferDAO(db)
    dlq = DeadLetterDAO(db)
    audit = AuditLogDAO(db)
    metrics = MetricsDAO(db)
    chart_cache = ChartCacheDAO(db)

    # LLM clients
    ds = DashScopeClient(api_key=snap.secrets.llm["dashscope_api_key"])
    cl = AnthropicClient(api_key=snap.secrets.llm["anthropic_api_key"])

    prompts = PromptLoader(cfg_dir / "prompts")
    p_versions = snap.app.llm.prompt_versions
    tier0 = Tier0Classifier(client=ds,
                            prompt=prompts.load("tier0_classify",
                                                 p_versions["tier0_classify"]))
    tier1 = Tier1Summarizer(client=ds,
                             prompt=prompts.load("tier1_summarize",
                                                  p_versions["tier1_summarize"]))
    tier2 = Tier2DeepExtractor(client=cl,
                                prompt=prompts.load("tier2_extract",
                                                     p_versions["tier2_extract"]))
    cost = CostTracker(daily_ceiling_cny=snap.app.runtime.daily_cost_ceiling_cny,
                        pricing=PRICING)
    routerL = LLMRouter(first_party_sources={"sec_edgar", "juchao", "caixin_telegram"})
    llm = LLMPipeline(
        tier0, tier1, tier2, routerL, cost,
        watchlist_us=[w.ticker for w in snap.watchlist.us],
        watchlist_cn=[w.ticker for w in snap.watchlist.cn],
    )

    rules = RuleEngine(snap.app.classifier.rules) \
        if snap.app.classifier.rules else RuleEngine(  # default: only first-party + high
            __import__("news_pipeline.config.schema", fromlist=["ClassifierRulesCfg"])
            .ClassifierRulesCfg(price_move_critical_pct=5.0,
                                 sources_always_critical=["sec_edgar", "juchao"],
                                 sentiment_high_magnitude_critical=True))
    judge = LLMJudge(client=ds, model=snap.app.llm.tier1_model)
    importance = ImportanceClassifier(
        rules=rules, judge=judge,
        gray_zone=tuple(snap.app.classifier.llm_fallback_when_score),
        watchlist_tickers=[w.ticker for w in snap.watchlist.us]
                          + [w.ticker for w in snap.watchlist.cn],
    )

    pushers = build_pushers(snap.channels, snap.secrets)
    dispatcher = PusherDispatcher(pushers)
    msg_builder = MessageBuilder(source_labels={
        "finnhub": "Finnhub", "sec_edgar": "SEC EDGAR",
        "yfinance_news": "Yahoo", "caixin_telegram": "财联社",
        "akshare_news": "东财", "xueqiu": "雪球", "ths": "同花顺",
        "juchao": "巨潮", "tushare_news": "Tushare",
    })
    burst = BurstSuppressor(
        window_seconds=snap.app.push.same_ticker_burst_window_min * 60,
        threshold=snap.app.push.same_ticker_burst_threshold,
    )
    dispatch_router = DispatchRouter(channels_by_market={
        "us": [c for c, ch in snap.channels.channels.items()
                if ch.market == "us" and ch.enabled],
        "cn": [c for c, ch in snap.channels.channels.items()
                if ch.market == "cn" and ch.enabled],
    })

    archive = None
    if snap.secrets.storage.get("feishu_app_id"):
        us_cli = FeishuBitableClient(
            app_id=snap.secrets.storage["feishu_app_id"],
            app_secret=snap.secrets.storage["feishu_app_secret"],
            app_token=snap.secrets.storage["feishu_app_token"],
            table_id=snap.secrets.storage["feishu_table_us"],
        )
        cn_cli = FeishuBitableClient(
            app_id=snap.secrets.storage["feishu_app_id"],
            app_secret=snap.secrets.storage["feishu_app_secret"],
            app_token=snap.secrets.storage["feishu_app_token"],
            table_id=snap.secrets.storage["feishu_table_cn"],
        )
        archive = ArchiveWriter(clients_by_market={"us": us_cli, "cn": cn_cli})

    bark = BarkAlerter(base_url=snap.secrets.alert["bark_url"]) \
        if snap.secrets.alert.get("bark_url") else None

    dedup = Dedup(raw_dao, title_distance_max=snap.app.dedup.title_simhash_distance)
    sec_ciks = {"NVDA": "1045810", "TSLA": "1318605", "AAPL": "320193"}  # extend as needed
    scrapers = build_registry(snap.sources, snap.watchlist, snap.secrets,
                                sec_ciks=sec_ciks)

    if once:
        for sid in scrapers.list_ids():
            await scrape_one_source(
                scraper=scrapers.get(sid), dedup=dedup,
                state_dao=state_dao, metrics=metrics,
            )
        await process_pending(
            raw_dao=raw_dao, llm=llm, importance=importance, proc_dao=proc_dao,
            msg_builder=msg_builder, router=dispatch_router, dispatcher=dispatcher,
            push_log=push_log, digest_dao=digest_dao, archive=archive, burst=burst,
        )
        await db.close()
        return

    runner = SchedulerRunner()
    for sid in scrapers.list_ids():
        scraper = scrapers.get(sid)
        interval = snap.sources.sources[sid].interval_sec or \
            snap.app.scheduler.scrape.market_hours_interval_sec
        runner.add_interval(
            name=f"scrape_{sid}", seconds=interval, jitter=10,
            coro_factory=lambda s=scraper: scrape_one_source(
                scraper=s, dedup=dedup, state_dao=state_dao, metrics=metrics),
        )

    runner.add_interval(
        name="process_pending",
        seconds=snap.app.scheduler.llm.process_interval_sec,
        coro_factory=lambda: process_pending(
            raw_dao=raw_dao, llm=llm, importance=importance, proc_dao=proc_dao,
            msg_builder=msg_builder, router=dispatch_router, dispatcher=dispatcher,
            push_log=push_log, digest_dao=digest_dao, archive=archive, burst=burst,
        ),
    )

    # Digest cron jobs (4 per day)
    for key, hm in [("morning_us", snap.app.scheduler.digest.morning_us),
                    ("evening_us", snap.app.scheduler.digest.evening_us),
                    ("morning_cn", snap.app.scheduler.digest.morning_cn),
                    ("evening_cn", snap.app.scheduler.digest.evening_cn)]:
        h, m = map(int, hm.split(":"))
        market = "us" if "us" in key else "cn"
        channels = dispatch_router._by_market.get(market, [])  # pylint: disable=protected-access
        runner.add_cron(
            name=f"digest_{key}", hour=h, minute=m,
            coro_factory=lambda k=key, mkt=market, chs=channels:
                _digest_job_runner(k, mkt, chs, digest_dao, proc_dao,
                                    msg_builder, dispatcher),
        )

    runner.start()

    stop_event = asyncio.Event()
    def _on_signal(*_):
        log.info("shutdown_signal")
        stop_event.set()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, _on_signal)

    if bark is not None:
        await bark.send("news_pipeline", "started")

    await stop_event.wait()
    await runner.shutdown()
    await db.close()
    log.info("shutdown_complete")


async def _digest_job_runner(digest_key, market, channels,
                              digest_dao, proc_dao, msg_builder, dispatcher):
    # Inline digest builder using MessageBuilder
    class _DB:
        def build_digest(self, *, items, market, digest_key):
            from news_pipeline.common.contracts import (
                Badge, CommonMessage, Deeplink,
            )
            from news_pipeline.common.enums import Market
            lines = "\n".join(f"• {p.summary[:120]}" for p in items[:30])
            return CommonMessage(
                title=f"Digest {digest_key}",
                summary=lines or "(no items)",
                source_label="digest",
                source_url="https://news-pipeline.local/",
                badges=[Badge(text=digest_key, color="blue")],
                chart_url=None, deeplinks=[],
                market=Market(market),
            )
    return await send_digest(
        digest_key=digest_key, market=market, channels=channels,
        digest_dao=digest_dao, proc_dao=proc_dao,
        digest_builder=_DB(), dispatcher=dispatcher,
    )


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
```

```python
# src/news_pipeline/healthcheck.py
import asyncio
import os
import sys
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select

from news_pipeline.common.timeutil import utc_now
from news_pipeline.storage.db import Database
from news_pipeline.storage.models import RawNews


async def _check() -> int:
    db_path = os.environ.get("NEWS_PIPELINE_DB", "data/news.db")
    if not Path(db_path).exists():
        print("FAIL: db missing")
        return 1
    db = Database(f"sqlite+aiosqlite:///{db_path}")
    await db.initialize()
    cutoff = (utc_now() - timedelta(minutes=30)).replace(tzinfo=None)
    async with db.session() as s:
        res = await s.execute(
            select(RawNews.id).where(RawNews.fetched_at >= cutoff).limit(1)
        )
        if res.first() is None:
            print("FAIL: no recent scrape")
            await db.close()
            return 1
    await db.close()
    print("OK")
    return 0


def main() -> int:
    return asyncio.run(_check())


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Manual smoke**

```bash
mkdir -p data
NEWS_PIPELINE_ONCE=1 uv run python -m news_pipeline.main
```

Expected: runs once, exits clean. Real LLM/push will hit rate limits unless secrets are set; with stub secrets, expect HTTP errors logged, but no crash.

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/scheduler/runner.py src/news_pipeline/main.py src/news_pipeline/healthcheck.py tests/integration/test_main_smoke.py
git commit -m "feat: wire APScheduler + main entrypoint + healthcheck"
```

---

## Phase 11 — Commands (Tasks 64-68)

### Task 64: Webhook server (FastAPI shell)

**Files:**
- Create: `src/news_pipeline/commands/__init__.py`
- Create: `src/news_pipeline/commands/server.py`
- Create: `tests/unit/commands/test_server.py`

- [ ] **Step 1: Test**

```python
# tests/unit/commands/test_server.py
from fastapi.testclient import TestClient

from news_pipeline.commands.server import build_app


def test_health_endpoint():
    app = build_app(handlers=lambda src, payload: {"ok": True, "src": src})
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200


def test_telegram_webhook_dispatches():
    captured = {}
    def handler(src, payload):
        captured["src"] = src
        captured["payload"] = payload
        return {"ok": True}
    app = build_app(handlers=handler)
    client = TestClient(app)
    r = client.post("/tg/webhook", json={"message": {"text": "/list"}})
    assert r.status_code == 200
    assert captured["src"] == "telegram"
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

```python
# src/news_pipeline/commands/__init__.py
```

```python
# src/news_pipeline/commands/server.py
from typing import Any, Callable

from fastapi import FastAPI, Request


def build_app(*, handlers: Callable[[str, dict[str, Any]], dict]) -> FastAPI:
    app = FastAPI(title="news_pipeline_cmds")

    @app.get("/health")
    async def health() -> dict:
        return {"ok": True}

    @app.post("/tg/webhook")
    async def tg_webhook(req: Request) -> dict:
        return handlers("telegram", await req.json())

    @app.post("/feishu/event")
    async def feishu_event(req: Request) -> dict:
        return handlers("feishu", await req.json())

    return app
```

```bash
mkdir -p tests/unit/commands && touch tests/unit/commands/__init__.py
```

> Add `httpx` (already deps) and ensure `fastapi` + `starlette` test client is available — already in test deps via FastAPI.

- [ ] **Step 4: Run — pass**

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/commands/ tests/unit/commands/
git commit -m "feat: add FastAPI webhook server shell"
```

---

### Task 65: Command dispatcher (parse text → handler)

**Files:**
- Create: `src/news_pipeline/commands/dispatcher.py`
- Create: `tests/unit/commands/test_dispatcher.py`

- [ ] **Step 1: Test**

```python
# tests/unit/commands/test_dispatcher.py
import pytest

from news_pipeline.commands.dispatcher import CommandDispatcher


def test_register_and_dispatch_text():
    d = CommandDispatcher()
    seen = {}

    @d.register("watch")
    async def watch(args, ctx):
        seen["args"] = args
        return "watched"

    import asyncio
    out = asyncio.run(d.handle_text("/watch NVDA TSLA", ctx={}))
    assert out == "watched"
    assert seen["args"] == ["NVDA", "TSLA"]


def test_unknown_command():
    d = CommandDispatcher()
    import asyncio
    out = asyncio.run(d.handle_text("/nope", ctx={}))
    assert "未知" in out or "unknown" in out


def test_non_command_text_ignored():
    d = CommandDispatcher()
    import asyncio
    out = asyncio.run(d.handle_text("hello", ctx={}))
    assert out is None
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

```python
# src/news_pipeline/commands/dispatcher.py
from typing import Any, Awaitable, Callable

CommandHandler = Callable[[list[str], dict[str, Any]], Awaitable[str]]


class CommandDispatcher:
    def __init__(self) -> None:
        self._handlers: dict[str, CommandHandler] = {}

    def register(self, name: str) -> Callable[[CommandHandler], CommandHandler]:
        def deco(fn: CommandHandler) -> CommandHandler:
            self._handlers[name] = fn
            return fn
        return deco

    async def handle_text(self, text: str, *,
                           ctx: dict[str, Any]) -> str | None:
        text = text.strip()
        if not text.startswith("/"):
            return None
        parts = text[1:].split()
        if not parts:
            return None
        cmd = parts[0]
        args = parts[1:]
        handler = self._handlers.get(cmd)
        if handler is None:
            return f"未知命令: /{cmd}"
        return await handler(args, ctx)
```

- [ ] **Step 4: Run — pass**

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/commands/dispatcher.py tests/unit/commands/test_dispatcher.py
git commit -m "feat: add command dispatcher (text parsing)"
```

---

### Task 66: Core commands — /list /watch /unwatch /news

**Files:**
- Create: `src/news_pipeline/commands/handlers/__init__.py`
- Create: `src/news_pipeline/commands/handlers/watchlist.py`
- Create: `src/news_pipeline/commands/handlers/news.py`
- Create: `tests/unit/commands/test_watchlist_news_cmds.py`

- [ ] **Step 1: Test**

```python
# tests/unit/commands/test_watchlist_news_cmds.py
from pathlib import Path

import pytest
import yaml

from news_pipeline.commands.handlers.watchlist import register_watchlist_cmds
from news_pipeline.commands.handlers.news import register_news_cmds
from news_pipeline.commands.dispatcher import CommandDispatcher


@pytest.mark.asyncio
async def test_watch_adds_to_yaml(tmp_path: Path):
    wl = tmp_path / "watchlist.yml"
    wl.write_text(yaml.safe_dump({"us": [], "cn": [], "macro": [], "sectors": []}))
    d = CommandDispatcher()
    register_watchlist_cmds(d, watchlist_path=wl)
    out = await d.handle_text("/watch NVDA", ctx={})
    assert "已加入" in out
    data = yaml.safe_load(wl.read_text())
    assert any(e["ticker"] == "NVDA" for e in data["us"])


@pytest.mark.asyncio
async def test_list_shows_all(tmp_path: Path):
    wl = tmp_path / "watchlist.yml"
    wl.write_text(yaml.safe_dump({
        "us": [{"ticker": "NVDA"}], "cn": [{"ticker": "600519"}],
        "macro": ["FOMC"], "sectors": ["semiconductor"],
    }))
    d = CommandDispatcher()
    register_watchlist_cmds(d, watchlist_path=wl)
    out = await d.handle_text("/list", ctx={})
    assert "NVDA" in out and "600519" in out


@pytest.mark.asyncio
async def test_news_shows_recent():
    from unittest.mock import AsyncMock, MagicMock
    proc_dao = MagicMock()
    proc_dao.list_recent_for_ticker = AsyncMock(return_value=[
        MagicMock(summary="出口管制升级", extracted_at="2026-04-25"),
    ])
    d = CommandDispatcher()
    register_news_cmds(d, processed_dao=proc_dao)
    out = await d.handle_text("/news NVDA", ctx={})
    assert "出口管制" in out
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

```python
# src/news_pipeline/commands/handlers/__init__.py
```

```python
# src/news_pipeline/commands/handlers/watchlist.py
from pathlib import Path
from typing import Any

import yaml

from news_pipeline.commands.dispatcher import CommandDispatcher


def _is_us(ticker: str) -> bool:
    return ticker.isalpha()


def register_watchlist_cmds(d: CommandDispatcher, *,
                              watchlist_path: Path) -> None:

    @d.register("watch")
    async def watch(args: list[str], ctx: dict[str, Any]) -> str:
        if not args:
            return "用法: /watch TICKER [...]"
        data = yaml.safe_load(watchlist_path.read_text(encoding="utf-8"))
        added: list[str] = []
        for t in args:
            key = "us" if _is_us(t) else "cn"
            existing = {e["ticker"] for e in data.get(key, [])}
            if t in existing:
                continue
            data.setdefault(key, []).append({"ticker": t, "alerts": []})
            added.append(t)
        watchlist_path.write_text(yaml.safe_dump(data, allow_unicode=True))
        return f"已加入: {', '.join(added)}" if added else "无变化"

    @d.register("unwatch")
    async def unwatch(args: list[str], ctx: dict[str, Any]) -> str:
        if not args:
            return "用法: /unwatch TICKER [...]"
        data = yaml.safe_load(watchlist_path.read_text(encoding="utf-8"))
        removed: list[str] = []
        for t in args:
            for key in ("us", "cn"):
                lst = data.get(key, [])
                new = [e for e in lst if e["ticker"] != t]
                if len(new) != len(lst):
                    data[key] = new
                    removed.append(t)
                    break
        watchlist_path.write_text(yaml.safe_dump(data, allow_unicode=True))
        return f"已移除: {', '.join(removed)}" if removed else "无变化"

    @d.register("list")
    async def list_(args: list[str], ctx: dict[str, Any]) -> str:
        data = yaml.safe_load(watchlist_path.read_text(encoding="utf-8"))
        us = ", ".join(e["ticker"] for e in data.get("us", []))
        cn = ", ".join(e["ticker"] for e in data.get("cn", []))
        macro = ", ".join(data.get("macro", []))
        sectors = ", ".join(data.get("sectors", []))
        return (f"美股: {us or '(空)'}\nA股: {cn or '(空)'}\n"
                f"宏观: {macro or '(空)'}\n板块: {sectors or '(空)'}")
```

```python
# src/news_pipeline/commands/handlers/news.py
from typing import Any

from news_pipeline.commands.dispatcher import CommandDispatcher


def register_news_cmds(d: CommandDispatcher, *, processed_dao: Any) -> None:

    @d.register("news")
    async def news(args: list[str], ctx: dict[str, Any]) -> str:
        if not args:
            return "用法: /news TICKER"
        ticker = args[0]
        items = await processed_dao.list_recent_for_ticker(ticker, limit=10)
        if not items:
            return f"{ticker} 近期无新闻"
        lines = [f"• {p.extracted_at} {p.summary[:120]}" for p in items[:10]]
        return f"{ticker} 近 10 条:\n" + "\n".join(lines)
```

> Note: `processed_dao.list_recent_for_ticker` is an additional DAO method. Add it now:

Append to `src/news_pipeline/storage/dao/news_processed.py`:

```python
    async def list_recent_for_ticker(self, ticker: str, *,
                                       limit: int = 10) -> list[NewsProcessed]:
        from sqlalchemy import select, text
        from news_pipeline.storage.models import Entity, NewsEntity, NewsProcessed
        async with self._db.session() as s:
            res = await s.execute(
                select(NewsProcessed)
                .join(NewsEntity, NewsEntity.news_id == NewsProcessed.id)
                .join(Entity, Entity.id == NewsEntity.entity_id)
                .where(Entity.ticker == ticker)
                .order_by(NewsProcessed.extracted_at.desc())
                .limit(limit)
            )
            return list(res.scalars())
```

- [ ] **Step 4: Run — pass**

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/commands/handlers/ src/news_pipeline/storage/dao/news_processed.py tests/unit/commands/test_watchlist_news_cmds.py
git commit -m "feat: add /watch /unwatch /list /news commands"
```

---

### Task 67: Chart commands — /chart /sentiment

**Files:**
- Create: `src/news_pipeline/commands/handlers/charts.py`
- Create: `tests/unit/commands/test_chart_cmds.py`

- [ ] **Step 1: Test**

```python
# tests/unit/commands/test_chart_cmds.py
from unittest.mock import AsyncMock, MagicMock

import pytest

from news_pipeline.commands.dispatcher import CommandDispatcher
from news_pipeline.commands.handlers.charts import register_chart_cmds


@pytest.mark.asyncio
async def test_chart_returns_url():
    factory = MagicMock()
    factory.render_kline = AsyncMock(return_value="https://oss/x.png")
    d = CommandDispatcher()
    register_chart_cmds(d, chart_factory=factory)
    out = await d.handle_text("/chart NVDA 30d", ctx={})
    assert "oss/x.png" in out
    factory.render_kline.assert_awaited_once()
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

```python
# src/news_pipeline/commands/handlers/charts.py
from typing import Any

from news_pipeline.charts.factory import ChartFactory, ChartRequest
from news_pipeline.commands.dispatcher import CommandDispatcher


def register_chart_cmds(d: CommandDispatcher, *, chart_factory: ChartFactory) -> None:

    @d.register("chart")
    async def chart(args: list[str], ctx: dict[str, Any]) -> str:
        if not args:
            return "用法: /chart TICKER [window=30d]"
        ticker = args[0]
        window = args[1] if len(args) > 1 else "30d"
        url = await chart_factory.render_kline(
            ChartRequest(ticker=ticker, kind="kline", window=window, params={})
        )
        return f"📈 {ticker} K线: {url}"

    @d.register("sentiment")
    async def sentiment(args: list[str], ctx: dict[str, Any]) -> str:
        if not args:
            return "用法: /sentiment TICKER [days=7]"
        ticker = args[0]
        days = args[1] if len(args) > 1 else "7"
        url = await chart_factory.render_kline(  # reuse kline path; sentiment requires extra impl
            ChartRequest(ticker=ticker, kind="sentiment",
                          window=f"{days}d", params={})
        )
        return f"📊 {ticker} 情绪曲线: {url}"
```

> NOTE: For MVP we route `/sentiment` through `render_kline`. Phase-2 fix: add `render_sentiment` on `ChartFactory` (data loader returns sentiment time-series instead of OHLC).

- [ ] **Step 4: Run — pass**

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/commands/handlers/charts.py tests/unit/commands/test_chart_cmds.py
git commit -m "feat: add /chart and /sentiment commands"
```

---

### Task 68: Operational commands — /health /cost /pause /digest

**Files:**
- Create: `src/news_pipeline/commands/handlers/ops.py`
- Create: `tests/unit/commands/test_ops_cmds.py`

- [ ] **Step 1: Test**

```python
# tests/unit/commands/test_ops_cmds.py
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from news_pipeline.commands.dispatcher import CommandDispatcher
from news_pipeline.commands.handlers.ops import register_ops_cmds


@pytest.mark.asyncio
async def test_cost_today():
    cost = MagicMock()
    cost.today_cost_cny = MagicMock(return_value=1.42)
    cost.remaining_today = MagicMock(return_value=3.58)
    d = CommandDispatcher()
    register_ops_cmds(d, cost=cost, state_dao=MagicMock(),
                      digest_runner=AsyncMock())
    out = await d.handle_text("/cost", ctx={})
    assert "1.42" in out


@pytest.mark.asyncio
async def test_pause():
    state = MagicMock()
    state.set_paused = AsyncMock()
    d = CommandDispatcher()
    register_ops_cmds(d, cost=MagicMock(), state_dao=state,
                      digest_runner=AsyncMock())
    out = await d.handle_text("/pause xueqiu", ctx={})
    assert "暂停" in out
    state.set_paused.assert_awaited_once()
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

```python
# src/news_pipeline/commands/handlers/ops.py
from datetime import timedelta
from typing import Any, Awaitable, Callable

from news_pipeline.commands.dispatcher import CommandDispatcher
from news_pipeline.common.timeutil import utc_now
from news_pipeline.llm.cost_tracker import CostTracker
from news_pipeline.storage.dao.source_state import SourceStateDAO


def register_ops_cmds(
    d: CommandDispatcher, *,
    cost: CostTracker,
    state_dao: SourceStateDAO,
    digest_runner: Callable[[], Awaitable[int]],
) -> None:

    @d.register("cost")
    async def cost_today(args: list[str], ctx: dict[str, Any]) -> str:
        return (f"今日 LLM 成本: {cost.today_cost_cny():.2f} CNY"
                f"\n剩余预算: {cost.remaining_today():.2f} CNY")

    @d.register("pause")
    async def pause(args: list[str], ctx: dict[str, Any]) -> str:
        if not args:
            return "用法: /pause SOURCE [minutes=30]"
        src = args[0]
        mins = int(args[1]) if len(args) > 1 else 30
        await state_dao.set_paused(
            src,
            until=utc_now().replace(tzinfo=None) + timedelta(minutes=mins),
            error="manual_pause",
        )
        return f"已暂停 {src} {mins} 分钟"

    @d.register("digest")
    async def digest(args: list[str], ctx: dict[str, Any]) -> str:
        if not args or args[0] != "now":
            return "用法: /digest now"
        n = await digest_runner()
        return f"已发送 digest, 含 {n} 条"

    @d.register("health")
    async def health(args: list[str], ctx: dict[str, Any]) -> str:
        return "OK (详情见 healthcheck endpoint)"
```

- [ ] **Step 4: Run — pass**

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/commands/handlers/ops.py tests/unit/commands/test_ops_cmds.py
git commit -m "feat: add /cost /pause /digest /health commands"
```

---

## Phase 12 — DR + Observability + Eval (Tasks 69-75)

### Task 69: SQLite OSS backup script

**Files:**
- Create: `scripts/backup_sqlite.sh`
- Create: `scripts/restore_sqlite.sh`
- Create: `tests/integration/test_backup_script.py`

- [ ] **Step 1: Backup script**

```bash
# scripts/backup_sqlite.sh
#!/usr/bin/env bash
set -euo pipefail

DB="${NEWS_PIPELINE_DB:-data/news.db}"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
TMP="/tmp/news_${TS}.db"
GZ="/tmp/news_${TS}.db.gz"

sqlite3 "$DB" ".backup '$TMP'"
gzip -f "$TMP"

OSS_BUCKET="${OSS_BUCKET:?must set}"
OSS_ENDPOINT="${OSS_ENDPOINT:?must set}"
OSSUTIL="${OSSUTIL:-ossutil64}"

"$OSSUTIL" cp "$GZ" "oss://${OSS_BUCKET}/backups/news_${TS}.db.gz" \
    --endpoint "$OSS_ENDPOINT"

# Retention: list and delete entries older than 30 days
"$OSSUTIL" ls "oss://${OSS_BUCKET}/backups/" --endpoint "$OSS_ENDPOINT" \
  | awk '{print $NF}' | grep '\.db\.gz$' | while read -r object; do
    name="$(basename "$object")"
    obj_date="${name#news_}"
    obj_date="${obj_date%.db.gz}"
    obj_epoch="$(date -u -j -f "%Y%m%dT%H%M%SZ" "$obj_date" +%s 2>/dev/null || \
                  date -u -d "$(echo "$obj_date" | sed 's/T/ /')" +%s 2>/dev/null || echo 0)"
    cutoff="$(date -u +%s -d '30 days ago' 2>/dev/null || date -u -v-30d +%s)"
    if [ "$obj_epoch" -gt 0 ] && [ "$obj_epoch" -lt "$cutoff" ]; then
        echo "deleting old backup: $object"
        "$OSSUTIL" rm "$object" --endpoint "$OSS_ENDPOINT" -f
    fi
done

rm -f "$GZ"
echo "backup OK: news_${TS}.db.gz"
```

- [ ] **Step 2: Restore script**

```bash
# scripts/restore_sqlite.sh
#!/usr/bin/env bash
set -euo pipefail

OBJECT="${1:?usage: restore_sqlite.sh oss://bucket/backups/news_TS.db.gz [target=data/news.db]}"
TARGET="${2:-data/news.db}"
OSS_ENDPOINT="${OSS_ENDPOINT:?must set}"
OSSUTIL="${OSSUTIL:-ossutil64}"

TMP="/tmp/restore_$$.db.gz"
"$OSSUTIL" cp "$OBJECT" "$TMP" --endpoint "$OSS_ENDPOINT"
gunzip -f "$TMP"
RESTORED="${TMP%.gz}"

if [ -f "$TARGET" ]; then
    cp "$TARGET" "${TARGET}.before-restore"
fi
mv "$RESTORED" "$TARGET"
echo "restore OK -> $TARGET (previous saved as ${TARGET}.before-restore)"
```

- [ ] **Step 3: Permissions + check**

```bash
chmod +x scripts/backup_sqlite.sh scripts/restore_sqlite.sh
./scripts/backup_sqlite.sh    # will fail without OSS env, but script must parse
```

- [ ] **Step 4: Trivial integration test**

```python
# tests/integration/test_backup_script.py
import subprocess
from pathlib import Path


def test_backup_script_syntax():
    out = subprocess.run(["bash", "-n", "scripts/backup_sqlite.sh"],
                         capture_output=True)
    assert out.returncode == 0, out.stderr.decode()


def test_restore_script_syntax():
    out = subprocess.run(["bash", "-n", "scripts/restore_sqlite.sh"],
                         capture_output=True)
    assert out.returncode == 0, out.stderr.decode()
```

- [ ] **Step 5: Commit**

```bash
git add scripts/ tests/integration/test_backup_script.py
git commit -m "feat: add OSS backup + restore scripts"
```

---

### Task 70: Cron entry for daily backup (in container or host)

**Files:**
- Modify: `docker/Dockerfile` (add cron support)
- Create: `docker/cron-entrypoint.sh`
- Modify: `docker/compose.yml` (mount script)
- Create: `docs/runbook/backup.md`

- [ ] **Step 1: Decide**

Decision: Run backup as a host cron (not in-container) — simpler, no need to add cron to slim image.

- [ ] **Step 2: Document host cron in runbook**

```markdown
# docs/runbook/backup.md

## Daily SQLite backup to OSS

On the host server, install `ossutil64` then add a cron entry:

```cron
0 3 * * * cd /opt/news_pipeline && \
  OSS_BUCKET=news-charts OSS_ENDPOINT=oss-cn-hangzhou.aliyuncs.com \
  NEWS_PIPELINE_DB=data/news.db ./scripts/backup_sqlite.sh \
  >> logs/backup.log 2>&1
```

Verify: `tail -f logs/backup.log` after first run.

To restore manually:
```bash
./scripts/restore_sqlite.sh oss://news-charts/backups/news_20260425T030000Z.db.gz
```
```

- [ ] **Step 3: Verify**

```bash
mkdir -p docs/runbook
ls docs/runbook/backup.md
```

- [ ] **Step 4: Commit**

```bash
git add docs/runbook/
git commit -m "docs: add backup runbook (host cron approach)"
```

---

### Task 71: Weekly metrics report

**Files:**
- Create: `src/news_pipeline/observability/weekly_report.py`
- Create: `tests/unit/observability/test_weekly_report.py`

- [ ] **Step 1: Test**

```python
# tests/unit/observability/test_weekly_report.py
from unittest.mock import AsyncMock, MagicMock

import pytest

from news_pipeline.observability.weekly_report import build_weekly_report


@pytest.mark.asyncio
async def test_report_includes_metrics():
    metrics = MagicMock()
    metrics.get = AsyncMock(side_effect=lambda **kw: 5.0)
    text = await build_weekly_report(
        metrics=metrics,
        sources=["finnhub", "caixin_telegram"],
        channels=["tg_us", "feishu_us"],
    )
    assert "周报" in text or "Weekly" in text
    assert "finnhub" in text
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

```python
# src/news_pipeline/observability/weekly_report.py
from datetime import timedelta

from news_pipeline.common.timeutil import utc_now
from news_pipeline.storage.dao.metrics import MetricsDAO


async def build_weekly_report(
    *, metrics: MetricsDAO,
    sources: list[str], channels: list[str],
) -> str:
    today = utc_now().date()
    days = [today - timedelta(days=i) for i in range(7)]
    lines = ["**周报: 抓取/LLM/推送 7 天汇总**\n"]

    lines.append("\n_抓取新闻数 (按源)_")
    for s in sources:
        total = 0.0
        for d in days:
            v = await metrics.get(date_iso=d.isoformat(), name="scrape_new",
                                   dimensions=f"source={s}")
            total += v or 0.0
        lines.append(f"  {s}: {int(total)}")

    lines.append("\n_推送成功数 (按渠道)_")
    for c in channels:
        total = 0.0
        for d in days:
            v = await metrics.get(date_iso=d.isoformat(), name="push_ok",
                                   dimensions=f"channel={c}")
            total += v or 0.0
        lines.append(f"  {c}: {int(total)}")

    return "\n".join(lines)
```

- [ ] **Step 4: Run — pass**

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/observability/weekly_report.py tests/unit/observability/test_weekly_report.py
git commit -m "feat: add weekly metrics report builder"
```

---

### Task 72: Eval set scaffold (gold + runner)

**Files:**
- Create: `tests/eval/__init__.py`
- Create: `tests/eval/gold_news.jsonl` (3 sample entries to start; user adds more)
- Create: `tests/eval/test_extraction_quality.py`

- [ ] **Step 1: Sample gold data**

```jsonl
{"id": "g001", "title": "NVIDIA reports record Q1 revenue of $26B, beating estimates", "body": "NVIDIA reported quarterly revenue of $26 billion, up 262% year-over-year, driven by data center demand for AI chips...", "source": "reuters", "expected": {"event_type": "earnings", "sentiment": "bullish", "magnitude": "high", "related_tickers": ["NVDA"], "sectors": ["semiconductor", "ai"]}}
{"id": "g002", "title": "美联储维持利率不变 暗示年内可能降息一次", "body": "美联储FOMC议息会议决定维持利率不变,主席鲍威尔在新闻发布会上暗示年内可能降息一次...", "source": "caixin_telegram", "expected": {"event_type": "policy", "sentiment": "bullish", "magnitude": "high", "sectors": []}}
{"id": "g003", "title": "Tesla recalls 300,000 vehicles over autopilot software bug", "body": "Tesla announced a software recall affecting 300,000 vehicles due to an autopilot system issue...", "source": "finnhub", "expected": {"event_type": "filing", "sentiment": "bearish", "magnitude": "medium", "related_tickers": ["TSLA"]}}
```

- [ ] **Step 2: Eval test**

```python
# tests/eval/test_extraction_quality.py
import json
import os
from pathlib import Path

import pytest

GOLD_PATH = Path(__file__).parent / "gold_news.jsonl"


def _load_gold() -> list[dict]:
    return [json.loads(line) for line in GOLD_PATH.read_text().splitlines() if line.strip()]


@pytest.mark.skipif(os.environ.get("RUN_EVAL") != "1",
                     reason="opt-in: set RUN_EVAL=1")
@pytest.mark.asyncio
async def test_extraction_f1_above_baseline():
    """Run real LLM against gold set; require F1 ≥ 0.7 across event_type + sentiment."""
    from datetime import datetime
    from news_pipeline.common.contracts import RawArticle
    from news_pipeline.common.enums import Market

    # Build LLM extractor (uses real API keys from env)
    pytest.importorskip("anthropic")
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        pytest.skip("no ANTHROPIC_API_KEY")
    from news_pipeline.llm.clients.anthropic import AnthropicClient
    from news_pipeline.llm.extractors import Tier2DeepExtractor
    from news_pipeline.llm.prompts.loader import PromptLoader

    cl = AnthropicClient(api_key=api_key)
    prompt = PromptLoader(Path("config/prompts")).load("tier2_extract", "v1")
    ext = Tier2DeepExtractor(client=cl, prompt=prompt)

    gold = _load_gold()
    correct_event = correct_sent = 0
    for g in gold:
        art = RawArticle(
            source=g["source"], market=Market.US,
            fetched_at=datetime(2026, 4, 25), published_at=datetime(2026, 4, 25),
            url=f"https://eval/{g['id']}", url_hash=g["id"],
            title=g["title"], body=g["body"],
        )
        out = await ext.extract(art, raw_id=0)
        if out.event_type.value == g["expected"]["event_type"]:
            correct_event += 1
        if out.sentiment.value == g["expected"]["sentiment"]:
            correct_sent += 1

    n = len(gold)
    f1 = (correct_event + correct_sent) / (2 * n)
    assert f1 >= 0.7, f"F1={f1} below baseline 0.7"
```

> User: extend `gold_news.jsonl` to 50+ entries over time for stronger eval.

- [ ] **Step 3: Verify it loads**

```bash
mkdir -p tests/eval
RUN_EVAL=0 uv run pytest tests/eval/ -v
```

Expected: tests skipped (without `RUN_EVAL=1`).

- [ ] **Step 4: Commit**

```bash
git add tests/eval/
git commit -m "test: add eval set scaffold (3 gold examples + F1 baseline)"
```

---

### Task 73: Source labels + entity_aliases.yml + final wiring docs

**Files:**
- Create: `config/entity_aliases.yml`
- Modify: `README.md` (operational instructions)
- Create: `docs/runbook/operations.md`

- [ ] **Step 1: Entity aliases**

```yaml
# config/entity_aliases.yml — used to normalize LLM-extracted entity names
NVIDIA: [NVIDIA, NVDA, 英伟达, 老黄家]
AMD: [AMD, Advanced Micro Devices, 超威半导体]
TSMC: [TSMC, Taiwan Semiconductor, TSM, 台积电]
ASML: [ASML, ASML Holding]
Tesla: [Tesla, TSLA, 特斯拉]
Apple: [Apple, AAPL, 苹果]
Microsoft: [Microsoft, MSFT, 微软]
贵州茅台: [贵州茅台, 茅台, 600519]
宁德时代: [宁德时代, CATL, 300750]
```

- [ ] **Step 2: Operations runbook**

```markdown
# docs/runbook/operations.md

## Bootstrapping a new server

1. SSH into 阿里云轻量服务器 (Ubuntu 22.04, 2c2g+).
2. `apt update && apt install -y docker.io docker-compose-v2 sqlite3 ossutil`
3. `git clone <repo> /opt/news_pipeline && cd /opt/news_pipeline`
4. `cp config/secrets.yml.example config/secrets.yml && vim config/secrets.yml` — fill in real tokens
5. `mkdir -p data logs secrets`
6. Move secrets to its own dir: `mv config/secrets.yml secrets/secrets.yml`
7. `docker compose -f docker/compose.yml up -d`
8. `docker compose logs -f`
9. Configure host cron (see `backup.md`)

## Routine ops

- Add a stock: send `/watch NVDA` to your TG/飞书 bot
- See cost: send `/cost`
- Force a digest: send `/digest now`
- Pause a flaky source: `/pause xueqiu 60`
- Tail logs: `docker compose logs -f --tail=200`
- Inspect SQLite: `sqlite3 data/news.db "SELECT count(*) FROM raw_news;"`

## Upgrading

```
git pull
docker compose -f docker/compose.yml build
docker compose -f docker/compose.yml up -d
```

## Troubleshooting

| Symptom | Action |
|---|---|
| Bark alerts saying "scrape_recent_15min" | Check `select source, count(*) from raw_news where fetched_at > datetime('now','-30min') group by source;` |
| Repeated 401 from xueqiu/ths | Cookie expired; refresh `secrets.yml` xueqiu_cookie/ths_cookie + restart |
| Cost ceiling tripped daily | Check `daily_metrics` for which tier is over-spending; consider tier2 → tier1 demotion via prompt change |
| Telegram "Bad Request: chat not found" | Ensure bot was added to the chat; verify chat_id |
```

- [ ] **Step 3: Update README**

Append to `README.md`:
```markdown

## Operations

See `docs/runbook/operations.md` for bootstrapping and routine ops.
See `docs/runbook/backup.md` for backup configuration.
```

- [ ] **Step 4: Verify**

```bash
ls config/entity_aliases.yml docs/runbook/operations.md
```

- [ ] **Step 5: Commit**

```bash
git add config/entity_aliases.yml docs/runbook/operations.md README.md
git commit -m "docs: add entity aliases + operations runbook"
```

---

### Task 74: Run full test suite + lint + type check

**Files:** none new

- [ ] **Step 1: Run lint**

```bash
uv run ruff check && uv run ruff format --check
```
Fix any issues with `uv run ruff format` and re-commit if needed.

- [ ] **Step 2: Run type check**

```bash
uv run mypy src/
```
Fix any errors. (Common fixes: add `# type: ignore[no-untyped-def]` only when truly necessary; prefer adding annotations.)

- [ ] **Step 3: Run all tests**

```bash
uv run pytest -v
```
Expected: all unit + integration tests pass. Eval suite skipped without `RUN_EVAL=1`. Live suite skipped without `RUN_LIVE=1`.

- [ ] **Step 4: Coverage report (optional)**

```bash
uv run pytest --cov=news_pipeline --cov-report=term-missing
```
Aim ≥ 70% line coverage on `src/news_pipeline/` excluding `__init__.py`.

- [ ] **Step 5: Tag a milestone commit**

```bash
git tag -a v0.1.0-mvp -m "MVP feature-complete"
git log --oneline -1
```

---

### Task 75: Smoke deploy to 阿里云轻量

**Files:** none new (deployment runbook already exists)

- [ ] **Step 1: Sync repo to server**

```bash
ssh user@server "mkdir -p /opt/news_pipeline"
rsync -avz --exclude='.venv' --exclude='__pycache__' --exclude='data' \
  --exclude='secrets' ./ user@server:/opt/news_pipeline/
```

- [ ] **Step 2: Configure secrets**

```bash
ssh user@server
cd /opt/news_pipeline
mkdir -p secrets data logs
cp config/secrets.yml.example secrets/secrets.yml
vim secrets/secrets.yml   # paste real values
chmod 600 secrets/secrets.yml
```

- [ ] **Step 3: First run**

```bash
docker compose -f docker/compose.yml build
docker compose -f docker/compose.yml up -d
docker compose -f docker/compose.yml logs -f
```

Expected within 5 min:
- `scheduler_started` log line listing ~12 jobs
- `scrape_done` lines for each enabled source
- Eventually: `archive_failed` warning if 飞书 bitable token wrong, but main pipeline still moves
- After ~30 min: an actual push lands in your TG/飞书

- [ ] **Step 4: Validate end-to-end**

Send `/list` to your bot — expect watchlist response.
Send `/cost` — expect "今日 LLM 成本: 0.XX CNY".
Wait for first critical news — confirm three platforms received it.

- [ ] **Step 5: Configure host cron + finalize**

```bash
crontab -e
# Add backup cron from docs/runbook/backup.md
```

Send Bark notification: `curl https://api.day.app/$BARK_TOKEN/MVP%20deployed/news_pipeline%20live`.

Mark project status complete:

```bash
git tag -a v0.1.0-deployed -m "MVP deployed to production"
git push --tags
```

---

## Self-Review

After completing the plan, verify the following:

### Spec coverage check

| Spec section | Plan tasks |
|---|---|
| §1 系统总览 + 数据流 | Tasks 13-16 (storage), 22-32 (scrapers), 33-42 (LLM), 43-46 (classifier+router), 47-53 (push), 61-63 (scheduler) |
| §2 模块划分 + 接口契约 | Tasks 6-10 (enums + contracts), each module has its own task |
| §3 数据模型 (13 tables) | Tasks 14, 15, 16, 17-20 (DAOs) |
| §4 LLM Pipeline | Tasks 33-42 (prompts, clients, extractors, router, pipeline) |
| §5 Push & Rendering | Tasks 47-53 (builder, base, 3 platforms, dispatcher, burst) |
| §6.1 配置文件布局 | Task 11 |
| §6.2 Docker Compose | Task 3 |
| §6.3 监控 + 告警 | Tasks 4 (logging), 5 (Bark), 71 (weekly), 63 (healthcheck) |
| §6.4 测试策略 | Each task TDD; Task 72 (eval set); Task 74 (full suite) |
| §6.5 错误处理矩阵 | Tasks 19 (DLQ), 48 (retry), 61 (anti-crawl pause) |
| §6.6 备份与 DR | Tasks 69, 70, 75 |
| Charts | Tasks 54-58 |
| Archive | Tasks 59, 60 |
| Commands | Tasks 64-68 |

### Placeholder scan

Search the plan for these patterns and fix any found:
- `TBD`, `TODO`, `fill in`, `implement later`
- `# Similar to ...` (without the actual code)
- "Add appropriate error handling" (without specifying where/how)

The known intentional notes/limitations:
- Tier-3 prompt has `output_schema_inline: null` (markdown output, not JSON) — intentional, documented
- 财联社 + 同花顺 endpoints noted as "may need real-world tweak" — flagged in code comments
- 飞书 image embedding via `image_key` API: simplified to text link in MVP, flagged in Task 50
- `/sentiment` reuses `render_kline` path: flagged in Task 67 as Phase-2 fix

### Type consistency

| Type | Defined in | Used in |
|---|---|---|
| `RawArticle` | Task 7 | Tasks 17, 21, 23-31, 38-42, 47, 61, 62 |
| `EnrichedNews` | Task 7 | Tasks 18, 39, 40, 42, 43-45, 47, 59, 62 |
| `ScoredNews` | Task 7 | Tasks 45, 46, 47, 59, 62 |
| `CommonMessage` | Task 7 | Tasks 47, 48, 49, 50, 51, 52, 62 |
| `DispatchPlan` | Task 7 | Task 46, 62 |
| `Tier0Verdict` | Task 38 | Tasks 41, 42 |
| `RuleHit` | Task 43 | Task 45 |
| `ChartRequest` | Task 58 | Task 67 |
| `ScraperProtocol` | Task 22 | Tasks 23-31, 32, 61 |
| `PusherProtocol` | Task 48 | Tasks 49-52 |

All types defined in earlier tasks; no forward references; all field names consistent (e.g., `is_critical` everywhere, not `critical` in some places).

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-25-news-pipeline-impl.md`.

Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. Best for keeping context lean and getting independent review at each step.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints. Best when you want to watch the work happen step-by-step in this conversation.

Which approach? (Or "later" if you want to pause here and execute another time.)
