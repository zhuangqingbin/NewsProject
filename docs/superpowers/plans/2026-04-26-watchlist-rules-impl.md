# Watchlist Rules + LLM Implementation Plan (v0.3.0)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace flat `watchlist.yml` with `rules + llm` dual-section architecture. Rules-only mode runs zero LLM via Aho-Corasick keyword match; LLM mode preserved as opt-in.

**Architecture:** New `rules/` module (matcher.py + engine.py + verdict.py) sits between scrape and LLM pipeline. `RulesEngine.match(article)` returns `RulesVerdict`. `process_pending` uses rules as gate when `rules.enable=True`; rules-matched articles either get LLM Tier-1/2 (when `llm.enable=True`) or skip LLM entirely (`synth_enriched_from_rules`). Pluggable matcher via `MatcherProtocol`.

**Tech Stack:** Python 3.12, pydantic v2, pyahocorasick, pytest.

**Reference spec:** `docs/superpowers/specs/2026-04-26-watchlist-rules-design.md` — consult for any ambiguity.

---

## File Structure

```
src/news_pipeline/
├── rules/                                   # NEW MODULE
│   ├── __init__.py
│   ├── verdict.py                           # RulesVerdict dataclass
│   ├── patterns.py                          # Pattern + PatternKind + Match
│   ├── matcher.py                           # MatcherProtocol + AhoCorasickMatcher + word_boundary helper + build_matcher factory
│   └── engine.py                            # RulesEngine + _compile()
│
├── config/schema.py                         # MODIFIED: WatchlistFile rewrite
├── llm/pipeline.py                          # MODIFIED: process_with_rules()
├── classifier/importance.py                 # MODIFIED: accept verdict + gray_zone_action
├── pushers/common/message_builder.py        # MODIFIED: build_from_rules()
├── router/routes.py                         # MODIFIED: markets parameter
├── scheduler/jobs.py                        # MODIFIED: rules pre-filter in process_pending + synth_enriched_from_rules helper
└── main.py                                  # MODIFIED: wire RulesEngine + at_least_one_enabled check

config/watchlist.yml                          # MIGRATED to new format
scripts/migrate_watchlist_v0_3_0.py           # NEW: one-off migration helper

tests/unit/rules/                             # NEW
├── __init__.py
├── test_matcher.py
├── test_engine.py
└── test_compile.py

tests/unit/config/test_watchlist_schema.py    # NEW (replaces watchlist parts of test_schema.py)
tests/unit/classifier/test_importance.py      # MODIFIED: add verdict-based cases
tests/unit/pushers/test_message_builder.py    # MODIFIED: add build_from_rules cases
tests/unit/router/test_routes.py              # MODIFIED: add multi-market cases
tests/unit/scheduler/test_process_pending_rules.py  # NEW
```

---

## Conventions

- **Test runner:** `uv run pytest`
- **Lint:** `uv run ruff check src/ tests/`
- **Type:** `uv run mypy src/`
- **Async tests:** `@pytest.mark.asyncio` (pytest-asyncio mode=auto)
- **Each task:** TDD where applicable (test → fail → impl → pass → commit). Pure config/scripts skip TDD where impractical.
- **Commit format:** `feat(v0.3.0): ...` / `test(v0.3.0): ...` / `refactor(v0.3.0): ...`

---

## Phase 0 — Dependency

### Task 1: Add `pyahocorasick` to dev deps + create rules package skeleton

**Files:**
- Modify: `pyproject.toml`
- Create: `src/news_pipeline/rules/__init__.py`
- Create: `tests/unit/rules/__init__.py`

- [ ] **Step 1: Add dep + create empty package**

```bash
cd /Users/qingbin.zhuang/Personal/NewsProject
uv add pyahocorasick
mkdir -p src/news_pipeline/rules tests/unit/rules
touch src/news_pipeline/rules/__init__.py tests/unit/rules/__init__.py
```

- [ ] **Step 2: Verify**

Run: `uv run python -c "import ahocorasick; print(ahocorasick.__version__)"`
Expected: prints version like `2.1.0`.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock src/news_pipeline/rules tests/unit/rules
git commit -m "chore(v0.3.0): add pyahocorasick dep + empty rules package"
```

---

## Phase 1 — Core Rules Module

### Task 2: `RulesVerdict` data contract

**Files:**
- Create: `src/news_pipeline/rules/verdict.py`
- Create: `tests/unit/rules/test_verdict.py`

- [ ] **Step 1: Write the test**

```python
# tests/unit/rules/test_verdict.py
from news_pipeline.rules.verdict import RulesVerdict


def test_default_no_match():
    v = RulesVerdict(matched=False)
    assert v.matched is False
    assert v.tickers == []
    assert v.related_tickers == []
    assert v.sectors == []
    assert v.macros == []
    assert v.generic_hits == []
    assert v.markets == []
    assert v.score_boost == 0.0


def test_full_verdict():
    v = RulesVerdict(
        matched=True,
        tickers=["NVDA"],
        related_tickers=["AMD"],
        sectors=["semiconductor"],
        macros=["FOMC"],
        generic_hits=["powell"],
        markets=["us"],
        score_boost=85.0,
    )
    assert v.matched is True
    assert v.tickers == ["NVDA"]
    assert v.score_boost == 85.0


def test_frozen():
    import dataclasses
    v = RulesVerdict(matched=False)
    try:
        v.matched = True  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        return
    assert False, "RulesVerdict must be frozen"
```

- [ ] **Step 2: Run test — expect import error**

Run: `uv run pytest tests/unit/rules/test_verdict.py -v`
Expected: FAIL with `ModuleNotFoundError: news_pipeline.rules.verdict`.

- [ ] **Step 3: Implement**

```python
# src/news_pipeline/rules/verdict.py
from dataclasses import dataclass, field


@dataclass(frozen=True)
class RulesVerdict:
    """Result of running rules engine against an article.

    Returned by RulesEngine.match() and consumed by:
    - scheduler/jobs.process_pending (gate logic)
    - classifier/importance.score_news (score_boost)
    - pushers/common/message_builder.build_from_rules (badges)
    - router/routes.route (markets routing)
    """

    matched: bool
    tickers: list[str] = field(default_factory=list)         # direct ticker/alias hits
    related_tickers: list[str] = field(default_factory=list) # via sector/macro associations
    sectors: list[str] = field(default_factory=list)         # sector_keywords hits
    macros: list[str] = field(default_factory=list)          # macro_keywords hits
    generic_hits: list[str] = field(default_factory=list)    # keyword_list hits
    markets: list[str] = field(default_factory=list)         # 'us' / 'cn' / both
    score_boost: float = 0.0                                  # 0-100, added to classifier score
```

- [ ] **Step 4: Run — pass**

Run: `uv run pytest tests/unit/rules/test_verdict.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/rules/verdict.py tests/unit/rules/test_verdict.py
git commit -m "feat(v0.3.0): add RulesVerdict data contract"
```

---

### Task 3: `Pattern` + `PatternKind` + `Match` data contracts

**Files:**
- Create: `src/news_pipeline/rules/patterns.py`
- Create: `tests/unit/rules/test_patterns.py`

- [ ] **Step 1: Write the test**

```python
# tests/unit/rules/test_patterns.py
import dataclasses

from news_pipeline.common.enums import Market
from news_pipeline.rules.patterns import Match, Pattern, PatternKind


def test_pattern_kind_values():
    assert PatternKind.TICKER.value == "ticker"
    assert PatternKind.ALIAS.value == "alias"
    assert PatternKind.SECTOR.value == "sector"
    assert PatternKind.MACRO.value == "macro"
    assert PatternKind.GENERIC.value == "generic"


def test_pattern_minimal():
    p = Pattern(
        text="nvda",
        is_english=True,
        kind=PatternKind.TICKER,
        market=Market.US,
        owner="NVDA",
    )
    assert p.text == "nvda"
    assert p.is_english is True


def test_pattern_chinese():
    p = Pattern(
        text="茅台",
        is_english=False,
        kind=PatternKind.ALIAS,
        market=Market.CN,
        owner="600519",
    )
    assert p.is_english is False


def test_pattern_frozen():
    p = Pattern(text="x", is_english=True, kind=PatternKind.TICKER,
                market=Market.US, owner="X")
    try:
        p.text = "y"  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        return
    assert False, "Pattern must be frozen"


def test_match():
    p = Pattern(text="nvda", is_english=True, kind=PatternKind.TICKER,
                market=Market.US, owner="NVDA")
    m = Match(pattern=p, start=0, end=3, matched_text="nvda")
    assert m.start == 0 and m.end == 3
    assert m.matched_text == "nvda"
```

- [ ] **Step 2: Run — fail**

Run: `uv run pytest tests/unit/rules/test_patterns.py -v`
Expected: FAIL with ModuleNotFoundError.

- [ ] **Step 3: Implement**

```python
# src/news_pipeline/rules/patterns.py
from dataclasses import dataclass
from enum import StrEnum

from news_pipeline.common.enums import Market


class PatternKind(StrEnum):
    TICKER = "ticker"
    ALIAS = "alias"
    SECTOR = "sector"
    MACRO = "macro"
    GENERIC = "generic"


@dataclass(frozen=True)
class Pattern:
    """A single keyword pattern compiled from RulesSection config.

    `text` is always lowercase. `is_english` controls whether word boundary
    check applies during matching (English yes, CJK no).
    """
    text: str
    is_english: bool
    kind: PatternKind
    market: Market
    owner: str  # ticker code for TICKER/ALIAS; keyword self for SECTOR/MACRO/GENERIC


@dataclass(frozen=True)
class Match:
    """A successful match of a Pattern against an article text (lowercased)."""
    pattern: Pattern
    start: int
    end: int           # inclusive
    matched_text: str  # actual text from input (already lowercase)
```

- [ ] **Step 4: Run — pass**

Run: `uv run pytest tests/unit/rules/test_patterns.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/rules/patterns.py tests/unit/rules/test_patterns.py
git commit -m "feat(v0.3.0): add Pattern + PatternKind + Match data contracts"
```

---

### Task 4: `MatcherProtocol` + `AhoCorasickMatcher`

**Files:**
- Create: `src/news_pipeline/rules/matcher.py`
- Create: `tests/unit/rules/test_matcher.py`

- [ ] **Step 1: Write the test**

```python
# tests/unit/rules/test_matcher.py
from news_pipeline.common.enums import Market
from news_pipeline.rules.matcher import (
    AhoCorasickMatcher,
    MatcherProtocol,
    build_matcher,
)
from news_pipeline.rules.patterns import Pattern, PatternKind


def _en(text: str, owner: str = "X", kind: PatternKind = PatternKind.TICKER) -> Pattern:
    return Pattern(
        text=text.lower(), is_english=text.isascii(),
        kind=kind, market=Market.US, owner=owner,
    )


def _cn(text: str, owner: str = "X", kind: PatternKind = PatternKind.ALIAS) -> Pattern:
    return Pattern(
        text=text.lower(), is_english=text.isascii(),
        kind=kind, market=Market.CN, owner=owner,
    )


def test_aho_protocol_compliance():
    assert isinstance(AhoCorasickMatcher(), MatcherProtocol)


def test_basic_english_match():
    m = AhoCorasickMatcher()
    m.rebuild([_en("NVDA", owner="NVDA")])
    matches = m.find_all("NVDA reports earnings beat")
    assert len(matches) == 1
    assert matches[0].pattern.owner == "NVDA"
    assert matches[0].matched_text == "nvda"


def test_word_boundary_protects_against_substring():
    m = AhoCorasickMatcher()
    m.rebuild([_en("NVDA", owner="NVDA")])
    # 'ENVDAQ' contains 'NVDA' but should NOT match (no word boundary)
    matches = m.find_all("ENVDAQ shares")
    assert matches == []


def test_word_boundary_allows_punctuation():
    m = AhoCorasickMatcher()
    m.rebuild([_en("NVDA", owner="NVDA")])
    # comma/period/space all count as boundary
    assert len(m.find_all("NVDA, AMD")) == 1
    assert len(m.find_all("AMD NVDA.")) == 1
    assert len(m.find_all("(NVDA)")) == 1


def test_chinese_substring_match():
    m = AhoCorasickMatcher()
    m.rebuild([_cn("茅台", owner="600519")])
    # CJK has NO word boundary check
    matches = m.find_all("贵州茅台公布业绩")
    assert len(matches) == 1
    assert matches[0].pattern.owner == "600519"


def test_case_insensitive():
    m = AhoCorasickMatcher()
    m.rebuild([_en("NVDA", owner="NVDA")])
    assert len(m.find_all("nvda news")) == 1
    assert len(m.find_all("Nvda News")) == 1
    assert len(m.find_all("NVDA")) == 1


def test_multiple_patterns_same_text():
    """Two Patterns with same text but different kind/market should both match."""
    m = AhoCorasickMatcher()
    m.rebuild([
        _en("AI", owner="AI", kind=PatternKind.GENERIC),
        _en("AI", owner="AI", kind=PatternKind.SECTOR),
    ])
    matches = m.find_all("AI is the future")
    assert len(matches) == 2
    kinds = {m.pattern.kind for m in matches}
    assert kinds == {PatternKind.GENERIC, PatternKind.SECTOR}


def test_empty_patterns():
    m = AhoCorasickMatcher()
    m.rebuild([])
    assert m.find_all("anything") == []


def test_rebuild_overwrites():
    m = AhoCorasickMatcher()
    m.rebuild([_en("NVDA")])
    m.rebuild([_en("AMD")])  # NVDA should be gone
    assert m.find_all("NVDA AMD") == [
        next(iter(m.find_all("NVDA AMD")))
    ] or len(m.find_all("NVDA AMD")) == 1


def test_factory_aho_corasick():
    matcher = build_matcher("aho_corasick", {})
    assert isinstance(matcher, AhoCorasickMatcher)


def test_factory_unknown_raises():
    import pytest
    with pytest.raises(ValueError, match="unknown matcher"):
        build_matcher("xxx", {})
```

- [ ] **Step 2: Run — fail**

Run: `uv run pytest tests/unit/rules/test_matcher.py -v`
Expected: FAIL ModuleNotFoundError.

- [ ] **Step 3: Implement**

```python
# src/news_pipeline/rules/matcher.py
from typing import Any, Protocol, runtime_checkable

import ahocorasick

from news_pipeline.rules.patterns import Match, Pattern


@runtime_checkable
class MatcherProtocol(Protocol):
    """Pluggable matcher interface. Implementations: AhoCorasickMatcher (default),
    future TfidfMatcher / EmbeddingMatcher / RegexMatcher / CompositeMatcher.
    """

    def rebuild(self, patterns: list[Pattern]) -> None:
        """(Re)build the internal index from a fresh pattern list."""
        ...

    def find_all(self, text: str) -> list[Match]:
        """Return all matches in text. Text is matched case-insensitively."""
        ...


def _word_boundary_ok(text: str, start: int, end: int) -> bool:
    """English patterns must have non-alphanumeric chars (or string boundary)
    immediately before `start` and immediately after `end`. Prevents 'NVDA'
    from matching inside 'ENVDAQ'.
    """
    left_ok = (start == 0) or not text[start - 1].isalnum()
    right_ok = (end == len(text) - 1) or not text[end + 1].isalnum()
    return left_ok and right_ok


class AhoCorasickMatcher:
    """Default matcher: O(N+M) multi-pattern keyword search via pyahocorasick.

    English patterns post-filtered by word boundary; CJK patterns matched
    as substrings (no boundary, since '茅台' inside '贵州茅台' is correct).
    """

    def __init__(self) -> None:
        self._auto: ahocorasick.Automaton | None = None

    def rebuild(self, patterns: list[Pattern]) -> None:
        auto: ahocorasick.Automaton = ahocorasick.Automaton()
        # Multiple Patterns may share text (e.g., "AI" as both SECTOR and GENERIC);
        # group them so payload is a list.
        grouped: dict[str, list[Pattern]] = {}
        for p in patterns:
            grouped.setdefault(p.text, []).append(p)
        for text, group in grouped.items():
            if text:  # skip empty
                auto.add_word(text, group)
        if patterns:
            auto.make_automaton()
        self._auto = auto

    def find_all(self, text: str) -> list[Match]:
        if self._auto is None:
            return []
        text_lc = text.lower()
        out: list[Match] = []
        try:
            iter_results = list(self._auto.iter(text_lc))
        except (AttributeError, ValueError):
            # Empty automaton or not finalized
            return []
        for end_idx, payloads in iter_results:
            for p in payloads:
                start_idx = end_idx - len(p.text) + 1
                if p.is_english and not _word_boundary_ok(text_lc, start_idx, end_idx):
                    continue
                out.append(Match(
                    pattern=p, start=start_idx, end=end_idx,
                    matched_text=text_lc[start_idx : end_idx + 1],
                ))
        return out


def build_matcher(name: str, options: dict[str, Any]) -> MatcherProtocol:
    """Factory: pick matcher implementation by name. Future implementations
    drop in here without touching engine.py or downstream code.
    """
    if name == "aho_corasick":
        return AhoCorasickMatcher(**options)
    raise ValueError(f"unknown matcher: {name!r}")
```

- [ ] **Step 4: Run — pass**

Run: `uv run pytest tests/unit/rules/test_matcher.py -v`
Expected: 11 passed.

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/rules/matcher.py tests/unit/rules/test_matcher.py
git commit -m "feat(v0.3.0): add MatcherProtocol + AhoCorasickMatcher with English word boundary"
```

---

### Task 5: `_compile()` — RulesSection → patterns + reverse indexes

**Files:**
- Modify: `src/news_pipeline/rules/engine.py` (will be created)
- Create: `tests/unit/rules/test_compile.py`

This task creates `_compile()` as a top-level function in `engine.py` (which we'll fully populate in Task 6).

- [ ] **Step 1: Write the test (uses NEW WatchlistFile schema, which we'll define in Task 9 but anticipate here)**

```python
# tests/unit/rules/test_compile.py
import pytest

from news_pipeline.rules.engine import _compile
from news_pipeline.rules.patterns import PatternKind


def _section():
    """Build a minimal RulesSection-shaped object via dict (we'll switch to
    real RulesSection in Task 11 once schema lands)."""
    from news_pipeline.config.schema import (
        MarketKeywords, RulesSection, TickerEntry,
    )
    return RulesSection(
        enable=True,
        us=[
            TickerEntry(
                ticker="NVDA", name="NVIDIA",
                aliases=["英伟达"],
                sectors=["semiconductor"],
                macro_links=["FOMC"],
            ),
        ],
        cn=[
            TickerEntry(
                ticker="600519", name="贵州茅台",
                aliases=["茅台"],
                sectors=["白酒"],
                macro_links=["央行"],
            ),
        ],
        keyword_list=MarketKeywords(us=["powell"], cn=["证监会"]),
        macro_keywords=MarketKeywords(us=["FOMC", "CPI"], cn=["央行"]),
        sector_keywords=MarketKeywords(us=["semiconductor"], cn=["白酒"]),
    )


def test_compile_emits_all_pattern_kinds():
    patterns, sec_idx, mac_idx = _compile(_section())
    kinds = {p.kind for p in patterns}
    assert kinds == {
        PatternKind.TICKER, PatternKind.ALIAS,
        PatternKind.SECTOR, PatternKind.MACRO, PatternKind.GENERIC,
    }


def test_compile_ticker_pattern():
    patterns, _, _ = _compile(_section())
    nvda = [p for p in patterns if p.kind == PatternKind.TICKER and p.owner == "NVDA"]
    assert len(nvda) == 1
    assert nvda[0].text == "nvda"
    assert nvda[0].is_english is True


def test_compile_alias_lowercase():
    patterns, _, _ = _compile(_section())
    aliases = [p for p in patterns if p.kind == PatternKind.ALIAS]
    texts = {p.text for p in aliases}
    # name + aliases for both us and cn (4 total: NVIDIA, 英伟达, 贵州茅台, 茅台)
    assert "nvidia" in texts
    assert "英伟达" in texts
    assert "贵州茅台" in texts
    assert "茅台" in texts


def test_compile_sector_reverse_index():
    _, sec_idx, _ = _compile(_section())
    assert sec_idx["semiconductor"] == {"NVDA"}
    assert sec_idx["白酒"] == {"600519"}


def test_compile_macro_reverse_index():
    _, _, mac_idx = _compile(_section())
    assert mac_idx["fomc"] == {"NVDA"}
    assert mac_idx["央行"] == {"600519"}


def test_compile_chinese_pattern_marked_not_english():
    patterns, _, _ = _compile(_section())
    p = next(p for p in patterns if p.text == "茅台")
    assert p.is_english is False


def test_compile_empty_section():
    from news_pipeline.config.schema import RulesSection
    patterns, sec_idx, mac_idx = _compile(RulesSection(enable=True))
    assert patterns == []
    assert sec_idx == {}
    assert mac_idx == {}
```

- [ ] **Step 2: Run — fail**

Run: `uv run pytest tests/unit/rules/test_compile.py -v`
Expected: FAIL (engine.py / RulesSection not yet defined). NOTE: this test depends on Task 9's `RulesSection` schema being in place. Sequence Task 9 before this test passes — alternative: stub RulesSection as a small dataclass in engine.py for now.

- [ ] **Step 3: Implement engine.py with _compile() (full RulesEngine in Task 6)**

```python
# src/news_pipeline/rules/engine.py
from typing import TYPE_CHECKING

from news_pipeline.common.enums import Market
from news_pipeline.rules.patterns import Pattern, PatternKind
from news_pipeline.rules.verdict import RulesVerdict

if TYPE_CHECKING:
    from news_pipeline.config.schema import RulesSection
    from news_pipeline.common.contracts import RawArticle
    from news_pipeline.rules.matcher import MatcherProtocol


def _compile(
    rules: "RulesSection",
) -> tuple[list[Pattern], dict[str, set[str]], dict[str, set[str]]]:
    """Compile RulesSection config into:
      - flat pattern list (for matcher.rebuild)
      - sector_to_tickers reverse index (lowercase keyword → set of ticker codes)
      - macro_to_tickers reverse index (same)
    """
    patterns: list[Pattern] = []
    sector_to_tickers: dict[str, set[str]] = {}
    macro_to_tickers: dict[str, set[str]] = {}

    for market_str in ("us", "cn"):
        market = Market(market_str)
        # Per-ticker entries
        for entry in getattr(rules, market_str):
            patterns.append(Pattern(
                text=entry.ticker.lower(),
                is_english=entry.ticker.isascii(),
                kind=PatternKind.TICKER,
                market=market,
                owner=entry.ticker,
            ))
            patterns.append(Pattern(
                text=entry.name.lower(),
                is_english=entry.name.isascii(),
                kind=PatternKind.ALIAS,
                market=market,
                owner=entry.ticker,
            ))
            for alias in entry.aliases:
                patterns.append(Pattern(
                    text=alias.lower(),
                    is_english=alias.isascii(),
                    kind=PatternKind.ALIAS,
                    market=market,
                    owner=entry.ticker,
                ))
            for sec in entry.sectors:
                sector_to_tickers.setdefault(sec.lower(), set()).add(entry.ticker)
            for mac in entry.macro_links:
                macro_to_tickers.setdefault(mac.lower(), set()).add(entry.ticker)

        # Global keywords for this market
        for kw in getattr(rules.sector_keywords, market_str):
            patterns.append(Pattern(
                text=kw.lower(),
                is_english=kw.isascii(),
                kind=PatternKind.SECTOR,
                market=market,
                owner=kw,
            ))
        for kw in getattr(rules.macro_keywords, market_str):
            patterns.append(Pattern(
                text=kw.lower(),
                is_english=kw.isascii(),
                kind=PatternKind.MACRO,
                market=market,
                owner=kw,
            ))
        for kw in getattr(rules.keyword_list, market_str):
            patterns.append(Pattern(
                text=kw.lower(),
                is_english=kw.isascii(),
                kind=PatternKind.GENERIC,
                market=market,
                owner=kw,
            ))

    return patterns, sector_to_tickers, macro_to_tickers
```

- [ ] **Step 4: Defer test pass to Task 9**

Run: `uv run pytest tests/unit/rules/test_compile.py -v` will currently fail because `RulesSection` doesn't exist yet. Task 9 creates it; tests will pass after Task 9.

- [ ] **Step 5: Commit (engine.py partial)**

```bash
git add src/news_pipeline/rules/engine.py tests/unit/rules/test_compile.py
git commit -m "feat(v0.3.0): add _compile() function (RulesEngine wiring in Task 6)"
```

---

### Task 6: `RulesEngine` class + score_boost

**Files:**
- Modify: `src/news_pipeline/rules/engine.py`
- Create: `tests/unit/rules/test_engine.py`

- [ ] **Step 1: Write the test**

```python
# tests/unit/rules/test_engine.py
from datetime import datetime, UTC

from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.enums import Market
from news_pipeline.config.schema import (
    MarketKeywords, RulesSection, TickerEntry,
)
from news_pipeline.rules.engine import RulesEngine, _compute_boost
from news_pipeline.rules.matcher import AhoCorasickMatcher


def _section():
    return RulesSection(
        enable=True,
        us=[TickerEntry(
            ticker="NVDA", name="NVIDIA",
            aliases=["英伟达"],
            sectors=["semiconductor"],
            macro_links=["FOMC"],
        )],
        cn=[TickerEntry(
            ticker="600519", name="贵州茅台",
            aliases=["茅台"],
            sectors=["白酒"],
            macro_links=["央行"],
        )],
        keyword_list=MarketKeywords(us=["powell"], cn=[]),
        macro_keywords=MarketKeywords(us=["FOMC"], cn=["央行"]),
        sector_keywords=MarketKeywords(us=["semiconductor"], cn=["白酒"]),
    )


def _article(title: str, body: str = "", market: Market = Market.US) -> RawArticle:
    return RawArticle(
        source="x", market=market,
        fetched_at=datetime(2026, 4, 26, tzinfo=UTC),
        published_at=datetime(2026, 4, 26, tzinfo=UTC),
        url="https://x.com/1", url_hash="h1", title=title, body=body,
        title_simhash=0, raw_meta={},
    )


def test_no_match():
    e = RulesEngine(_section(), AhoCorasickMatcher())
    v = e.match(_article("Random news about politics"))
    assert v.matched is False


def test_direct_ticker_match():
    e = RulesEngine(_section(), AhoCorasickMatcher())
    v = e.match(_article("NVDA reports earnings"))
    assert v.matched is True
    assert v.tickers == ["NVDA"]
    assert v.markets == ["us"]
    assert v.score_boost >= 50.0


def test_alias_match():
    e = RulesEngine(_section(), AhoCorasickMatcher())
    v = e.match(_article("英伟达发布新一代GPU"))
    assert v.matched is True
    assert v.tickers == ["NVDA"]


def test_chinese_substring_alias():
    e = RulesEngine(_section(), AhoCorasickMatcher())
    v = e.match(_article("贵州茅台一季报营收增长"))
    assert v.tickers == ["600519"]
    assert v.markets == ["cn"]


def test_sector_associates_ticker():
    e = RulesEngine(_section(), AhoCorasickMatcher())
    v = e.match(_article("Semiconductor industry rebounds"))
    assert v.matched is True
    assert v.sectors == ["semiconductor"]
    assert v.related_tickers == ["NVDA"]
    assert v.tickers == []


def test_macro_associates_ticker():
    e = RulesEngine(_section(), AhoCorasickMatcher())
    v = e.match(_article("FOMC decision keeps rates unchanged"))
    assert v.macros == ["fomc"]
    assert v.related_tickers == ["NVDA"]


def test_generic_keyword_no_ticker():
    e = RulesEngine(_section(), AhoCorasickMatcher())
    v = e.match(_article("Powell speaks at the Fed today"))
    assert v.matched is True
    assert v.tickers == []
    assert v.related_tickers == []
    assert "powell" in v.generic_hits


def test_multi_market_match():
    e = RulesEngine(_section(), AhoCorasickMatcher())
    v = e.match(_article("FOMC加息影响A股茅台"))
    assert "us" in v.markets
    assert "cn" in v.markets


def test_score_boost_ticker():
    assert _compute_boost({"NVDA"}, set(), set()) == 50.0


def test_score_boost_combo():
    # ticker + sector + macro = 50 + 20 + 15 = 85
    assert _compute_boost({"NVDA"}, {"semiconductor"}, {"fomc"}) == 85.0


def test_score_boost_capped_at_100():
    assert _compute_boost({"A"}, {"B"}, {"C"}) <= 100.0
```

- [ ] **Step 2: Run — fail**

Run: `uv run pytest tests/unit/rules/test_engine.py -v`
Expected: FAIL — RulesEngine class not yet created (Task 5 only added `_compile`).

- [ ] **Step 3: Implement (append to engine.py)**

```python
# Append to src/news_pipeline/rules/engine.py (existing _compile stays)

from news_pipeline.common.contracts import RawArticle
from news_pipeline.config.schema import RulesSection
from news_pipeline.rules.matcher import MatcherProtocol


def _compute_boost(
    tickers: set[str], sectors: set[str], macros: set[str]
) -> float:
    boost = 0.0
    if tickers:
        boost += 50.0
    if sectors:
        boost += 20.0
    if macros:
        boost += 15.0
    return min(boost, 100.0)


class RulesEngine:
    """Compiles RulesSection into a matcher + reverse indexes, then provides
    match(article) → RulesVerdict.

    Hot reload: caller (main.py / config loader callback) calls rebuild() with
    a fresh RulesSection when watchlist.yml changes on disk.
    """

    def __init__(
        self,
        rules: RulesSection,
        matcher: MatcherProtocol,
    ) -> None:
        self._matcher = matcher
        self._sector_to_tickers: dict[str, set[str]] = {}
        self._macro_to_tickers: dict[str, set[str]] = {}
        self.rebuild(rules)

    def rebuild(self, rules: RulesSection) -> None:
        patterns, sec_idx, mac_idx = _compile(rules)
        self._matcher.rebuild(patterns)
        self._sector_to_tickers = sec_idx
        self._macro_to_tickers = mac_idx

    def match(self, art: RawArticle) -> RulesVerdict:
        text = f"{art.title}  {art.body or ''}"
        matches = self._matcher.find_all(text)

        if not matches:
            return RulesVerdict(matched=False)

        tickers: set[str] = set()
        sectors: set[str] = set()
        macros: set[str] = set()
        generics: list[str] = []
        markets: set[str] = set()
        related_tickers: set[str] = set()

        for m in matches:
            p = m.pattern
            markets.add(p.market.value)
            if p.kind in (PatternKind.TICKER, PatternKind.ALIAS):
                tickers.add(p.owner)
            elif p.kind == PatternKind.SECTOR:
                sectors.add(p.text)
                related_tickers.update(self._sector_to_tickers.get(p.text, []))
            elif p.kind == PatternKind.MACRO:
                macros.add(p.text)
                related_tickers.update(self._macro_to_tickers.get(p.text, []))
            elif p.kind == PatternKind.GENERIC:
                generics.append(p.text)

        return RulesVerdict(
            matched=True,
            tickers=sorted(tickers),
            related_tickers=sorted(related_tickers - tickers),
            sectors=sorted(sectors),
            macros=sorted(macros),
            generic_hits=generics,
            markets=sorted(markets),
            score_boost=_compute_boost(tickers, sectors, macros),
        )
```

- [ ] **Step 4: Defer pass to Task 9**

Tests still fail because RulesSection / TickerEntry / MarketKeywords don't exist yet. They're created in Task 9. Tests will pass after Task 9.

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/rules/engine.py tests/unit/rules/test_engine.py
git commit -m "feat(v0.3.0): add RulesEngine + _compute_boost (passes after Task 9)"
```

---

## Phase 2 — Config Schema Migration

### Task 7: New `WatchlistFile` schema (NO validators yet)

**Files:**
- Modify: `src/news_pipeline/config/schema.py`

- [ ] **Step 1: Replace existing `WatchlistFile`/`WatchlistEntry` with new structure**

In `src/news_pipeline/config/schema.py`, find the existing `WatchlistEntry` and `WatchlistFile` classes. Replace them with:

```python
# Replace these blocks in src/news_pipeline/config/schema.py:
#
# (Existing block to delete:)
# class WatchlistEntry(_Base):
#     ticker: str
#     alerts: list[str] = Field(default_factory=list)
# class WatchlistFile(_Base):
#     us: list[WatchlistEntry] = Field(default_factory=list)
#     cn: list[WatchlistEntry] = Field(default_factory=list)
#     macro: list[str] = Field(default_factory=list)
#     sectors: list[str] = Field(default_factory=list)
#
# Replace with:

from typing import Any, Literal


class TickerEntry(_Base):
    """One stock under rules.us or rules.cn."""
    ticker: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    sectors: list[str] = Field(default_factory=list)        # must be in sector_keywords[market]
    macro_links: list[str] = Field(default_factory=list)    # must be in macro_keywords[market]
    alerts: list[str] = Field(default_factory=list)         # legacy, LLM-only


class MarketKeywords(_Base):
    """A keyword list split by market."""
    us: list[str] = Field(default_factory=list)
    cn: list[str] = Field(default_factory=list)


class RulesSection(_Base):
    enable: bool = True
    gray_zone_action: Literal["skip", "digest", "push"] = "digest"
    matcher: str = "aho_corasick"
    matcher_options: dict[str, Any] = Field(default_factory=dict)
    us: list[TickerEntry] = Field(default_factory=list)
    cn: list[TickerEntry] = Field(default_factory=list)
    keyword_list: MarketKeywords = Field(default_factory=MarketKeywords)
    macro_keywords: MarketKeywords = Field(default_factory=MarketKeywords)
    sector_keywords: MarketKeywords = Field(default_factory=MarketKeywords)


class LLMSection(_Base):
    enable: bool = False
    us: list[str] = Field(default_factory=list)
    cn: list[str] = Field(default_factory=list)
    macro: list[str] = Field(default_factory=list)
    sectors: list[str] = Field(default_factory=list)


class WatchlistFile(_Base):
    rules: RulesSection = Field(default_factory=RulesSection)
    llm: LLMSection = Field(default_factory=LLMSection)
```

- [ ] **Step 2: Run existing config tests — expect failures**

Run: `uv run pytest tests/unit/config/ -v`
Expected: existing tests fail (they reference old `WatchlistEntry`/`WatchlistFile` shape).

- [ ] **Step 3: Defer fix to Task 8 (validators) and Task 11 (test rewrite)**

Don't try to fix existing tests yet — they'll be fully rewritten.

- [ ] **Step 4: Commit (intentionally breaks tests; will fix in following tasks)**

```bash
git add src/news_pipeline/config/schema.py
git commit -m "refactor(v0.3.0)!: replace WatchlistFile flat schema with rules+llm sections (breaks existing tests, fixed in Tasks 8/11)"
```

---

### Task 8: Schema validators

**Files:**
- Modify: `src/news_pipeline/config/schema.py`

- [ ] **Step 1: Add validators to `WatchlistFile`**

In `src/news_pipeline/config/schema.py`, modify `WatchlistFile`:

```python
from pydantic import Field, model_validator


class WatchlistFile(_Base):
    rules: RulesSection = Field(default_factory=RulesSection)
    llm: LLMSection = Field(default_factory=LLMSection)

    @model_validator(mode="after")
    def at_least_one_enabled(self) -> "WatchlistFile":
        if not self.rules.enable and not self.llm.enable:
            raise ValueError(
                "watchlist.yml: rules.enable AND llm.enable both False — "
                "at least one must be enabled"
            )
        return self

    @model_validator(mode="after")
    def ticker_unique(self) -> "WatchlistFile":
        for market in ("us", "cn"):
            tickers = [t.ticker for t in getattr(self.rules, market)]
            if len(tickers) != len(set(tickers)):
                dups = sorted({t for t in tickers if tickers.count(t) > 1})
                raise ValueError(
                    f"rules.{market}: duplicate tickers {dups}"
                )
        return self

    @model_validator(mode="after")
    def sector_macro_refs_valid(self) -> "WatchlistFile":
        for market in ("us", "cn"):
            sectors_set = set(getattr(self.rules.sector_keywords, market))
            macros_set = set(getattr(self.rules.macro_keywords, market))
            for entry in getattr(self.rules, market):
                bad_sectors = set(entry.sectors) - sectors_set
                bad_macros = set(entry.macro_links) - macros_set
                if bad_sectors:
                    raise ValueError(
                        f"{market} ticker {entry.ticker}: "
                        f"sectors {sorted(bad_sectors)} not in "
                        f"sector_keywords.{market}"
                    )
                if bad_macros:
                    raise ValueError(
                        f"{market} ticker {entry.ticker}: "
                        f"macro_links {sorted(bad_macros)} not in "
                        f"macro_keywords.{market}"
                    )
        return self
```

- [ ] **Step 2: Quick smoke test inline**

```bash
uv run python -c "
from news_pipeline.config.schema import (
    LLMSection, RulesSection, WatchlistFile,
)
# Default: rules.enable=True, llm.enable=False — should pass
w = WatchlistFile()
print('✅ default OK')

# Both off — should raise
try:
    WatchlistFile(rules=RulesSection(enable=False), llm=LLMSection(enable=False))
    print('❌ both-off should raise')
except ValueError as e:
    print('✅ both-off raises:', str(e)[:60])
"
```
Expected: prints `✅ default OK` and `✅ both-off raises: ...`.

- [ ] **Step 3: Commit**

```bash
git add src/news_pipeline/config/schema.py
git commit -m "feat(v0.3.0): add WatchlistFile validators (at-least-one-enabled, ticker-unique, ref-validity)"
```

---

### Task 9: Schema unit tests

**Files:**
- Create: `tests/unit/config/test_watchlist_schema.py`
- (existing `tests/unit/config/test_schema.py` will need its `test_watchlist_file_parses` deleted in Task 11)

- [ ] **Step 1: Write tests**

```python
# tests/unit/config/test_watchlist_schema.py
import pytest
from pydantic import ValidationError

from news_pipeline.config.schema import (
    LLMSection, MarketKeywords, RulesSection, TickerEntry, WatchlistFile,
)


def test_default_passes():
    """rules.enable=True (default), llm.enable=False — accepted."""
    w = WatchlistFile()
    assert w.rules.enable is True
    assert w.llm.enable is False


def test_both_disabled_rejects():
    with pytest.raises(ValidationError, match="both False"):
        WatchlistFile(
            rules=RulesSection(enable=False),
            llm=LLMSection(enable=False),
        )


def test_only_llm_enabled_passes():
    w = WatchlistFile(
        rules=RulesSection(enable=False),
        llm=LLMSection(enable=True),
    )
    assert w.rules.enable is False
    assert w.llm.enable is True


def test_duplicate_ticker_rejects():
    with pytest.raises(ValidationError, match="duplicate tickers"):
        WatchlistFile(rules=RulesSection(
            us=[
                TickerEntry(ticker="NVDA", name="NVIDIA"),
                TickerEntry(ticker="NVDA", name="NVIDIA Corp"),
            ],
        ))


def test_invalid_sector_ref_rejects():
    with pytest.raises(ValidationError, match="not in sector_keywords"):
        WatchlistFile(rules=RulesSection(
            us=[TickerEntry(
                ticker="NVDA", name="NVIDIA",
                sectors=["nonexistent_sector"],
            )],
            sector_keywords=MarketKeywords(us=["semiconductor"]),
        ))


def test_invalid_macro_link_rejects():
    with pytest.raises(ValidationError, match="not in macro_keywords"):
        WatchlistFile(rules=RulesSection(
            us=[TickerEntry(
                ticker="NVDA", name="NVIDIA",
                macro_links=["nonexistent_macro"],
            )],
            macro_keywords=MarketKeywords(us=["FOMC"]),
        ))


def test_valid_full_config():
    w = WatchlistFile(rules=RulesSection(
        us=[TickerEntry(
            ticker="NVDA", name="NVIDIA",
            aliases=["英伟达"],
            sectors=["semiconductor"],
            macro_links=["FOMC"],
        )],
        sector_keywords=MarketKeywords(us=["semiconductor"]),
        macro_keywords=MarketKeywords(us=["FOMC"]),
    ))
    assert len(w.rules.us) == 1
    assert w.rules.us[0].ticker == "NVDA"


def test_gray_zone_action_default():
    s = RulesSection()
    assert s.gray_zone_action == "digest"


def test_gray_zone_action_invalid_rejects():
    with pytest.raises(ValidationError):
        RulesSection(gray_zone_action="invalid_value")  # type: ignore[arg-type]


def test_matcher_default():
    s = RulesSection()
    assert s.matcher == "aho_corasick"
```

- [ ] **Step 2: Run — pass**

Run: `uv run pytest tests/unit/config/test_watchlist_schema.py -v`
Expected: 10 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/config/test_watchlist_schema.py
git commit -m "test(v0.3.0): WatchlistFile validators + new schema fields"
```

---

### Task 10: Run earlier deferred tests (rules/test_compile + test_engine)

**Files:** none (just run tests that were deferred in Tasks 5 and 6)

- [ ] **Step 1: Run all rules tests**

Run: `uv run pytest tests/unit/rules/ -v`
Expected: all of test_verdict.py (3), test_patterns.py (5), test_matcher.py (11), test_compile.py (7), test_engine.py (10) = **36 passed**.

If any fails, fix it inline now (likely small import/typo issues).

- [ ] **Step 2: Commit (only needed if you fixed something)**

```bash
git add -u
git commit -m "fix(v0.3.0): minor fixes to make deferred rules tests pass" || echo "nothing to commit"
```

---

### Task 11: Delete old watchlist tests + delete `WatchlistEntry` cleanup

**Files:**
- Modify: `tests/unit/config/test_schema.py` (remove old `test_watchlist_file_parses`)

- [ ] **Step 1: Find and delete the old test**

In `tests/unit/config/test_schema.py`, find:

```python
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

Delete this entire test function. Also remove `WatchlistFile` from any import in that file (if it's imported, leave the import; only delete the function body).

- [ ] **Step 2: Run all config tests**

Run: `uv run pytest tests/unit/config/ -v`
Expected: pass — `test_watchlist_schema.py` (10) + remaining `test_schema.py` tests.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/config/test_schema.py
git commit -m "test(v0.3.0): remove obsolete flat WatchlistFile test (replaced by test_watchlist_schema.py)"
```

---

## Phase 3 — Migration script + new watchlist.yml

### Task 12: Migration script `scripts/migrate_watchlist_v0_3_0.py`

**Files:**
- Create: `scripts/migrate_watchlist_v0_3_0.py`

- [ ] **Step 1: Write the script**

```python
#!/usr/bin/env python3
"""One-off: migrate watchlist.yml from v0.1.7 flat format to v0.3.0 rules+llm format.

Old format (v0.1.7):
    us: [{ticker, alerts}, ...]
    cn: [{ticker, alerts}, ...]
    macro: [str, ...]
    sectors: [str, ...]

New format (v0.3.0): see docs/superpowers/specs/2026-04-26-watchlist-rules-design.md §2.1

The script:
- Reads existing config/watchlist.yml
- Backs it up to config/watchlist.yml.v0_1_7.bak
- Writes new format with:
  * rules.enable=true, llm.enable=false (defaults)
  * rules.us / rules.cn: each ticker gets `name` placeholder + empty aliases/sectors/macro_links
  * macro keywords split heuristically into us/cn (English → us, CJK → cn)
  * sectors keywords split heuristically same way
  * llm: copies tickers + macro + sectors as-is
- Prints WARN for every heuristic decision (user must review)

After migration, user must manually:
  * Fill in `name` for each ticker
  * Add `aliases` per stock
  * Reference correct sector/macro_links from the global keyword lists
"""

from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

import yaml


def _is_cjk(s: str) -> bool:
    return any("一" <= ch <= "鿿" for ch in s)


def migrate(path: Path) -> dict:
    old = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    # Detect already-migrated
    if "rules" in old or "llm" in old:
        print("⚠ already in v0.3.0 format (has 'rules' or 'llm' top-level key); skipping")
        sys.exit(0)

    us_tickers = old.get("us", [])
    cn_tickers = old.get("cn", [])
    macros = old.get("macro", [])
    sectors = old.get("sectors", [])

    # Heuristic split: CJK → cn, ASCII → us
    macros_us = [m for m in macros if not _is_cjk(m)]
    macros_cn = [m for m in macros if _is_cjk(m)]
    sectors_us = [s for s in sectors if not _is_cjk(s)]
    sectors_cn = [s for s in sectors if _is_cjk(s)]

    print(f"  migrating {len(us_tickers)} US tickers, {len(cn_tickers)} CN tickers")
    print(f"  macros: {len(macros_us)} → us, {len(macros_cn)} → cn")
    print(f"  sectors: {len(sectors_us)} → us, {len(sectors_cn)} → cn")

    new = {
        "rules": {
            "enable": True,
            "gray_zone_action": "digest",
            "matcher": "aho_corasick",
            "us": [
                {
                    "ticker": t["ticker"] if isinstance(t, dict) else str(t),
                    "name": "TODO_FILL_NAME",
                    "aliases": [],
                    "sectors": [],
                    "macro_links": [],
                    "alerts": t.get("alerts", []) if isinstance(t, dict) else [],
                }
                for t in us_tickers
            ],
            "cn": [
                {
                    "ticker": str(t["ticker"]) if isinstance(t, dict) else str(t),
                    "name": "TODO_FILL_NAME",
                    "aliases": [],
                    "sectors": [],
                    "macro_links": [],
                    "alerts": t.get("alerts", []) if isinstance(t, dict) else [],
                }
                for t in cn_tickers
            ],
            "keyword_list": {"us": [], "cn": []},
            "macro_keywords": {"us": macros_us, "cn": macros_cn},
            "sector_keywords": {"us": sectors_us, "cn": sectors_cn},
        },
        "llm": {
            "enable": False,
            "us": [t["ticker"] if isinstance(t, dict) else str(t) for t in us_tickers],
            "cn": [str(t["ticker"]) if isinstance(t, dict) else str(t)
                   for t in cn_tickers],
            "macro": macros,
            "sectors": sectors,
        },
    }

    return new


def main() -> int:
    path = Path("config/watchlist.yml")
    if not path.exists():
        print(f"❌ {path} not found; run from project root")
        return 1

    backup = path.with_suffix(
        f".yml.v0_1_7.bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )
    print(f"🔒 backing up to {backup}")
    shutil.copy2(path, backup)

    new = migrate(path)
    path.write_text(
        yaml.safe_dump(new, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )

    print(f"\n✅ migrated. Now MANUALLY edit {path} to:")
    print("   1. Replace TODO_FILL_NAME with each ticker's full name")
    print("   2. Add aliases per ticker (e.g., NVDA → 英伟达, 老黄家)")
    print("   3. Reference sector / macro names from the global keyword lists")
    print("   4. Optionally add keyword_list entries (Powell, recession, etc.)")
    print("\n⚠ schema validators will reject sectors/macro_links not in the global lists")
    print("⚠ run `uv run python -c \"from news_pipeline.config.loader import ConfigLoader; "
          "from pathlib import Path; ConfigLoader(Path('config')).load()\"` to verify")

    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Make executable**

```bash
chmod +x scripts/migrate_watchlist_v0_3_0.py
```

- [ ] **Step 3: Verify imports clean**

Run: `uv run python -c "import scripts.migrate_watchlist_v0_3_0; print('ok')"` (might fail if scripts/ not in path; alternative: `uv run python -c "exec(open('scripts/migrate_watchlist_v0_3_0.py').read())" </dev/null` — but it tries to migrate. Skip dry test if no easy way.)

Just verify the file syntax: `uv run python -m py_compile scripts/migrate_watchlist_v0_3_0.py` → no output = OK.

- [ ] **Step 4: Commit**

```bash
git add scripts/migrate_watchlist_v0_3_0.py
git commit -m "feat(v0.3.0): add migration script for watchlist.yml v0.1.7 → v0.3.0"
```

---

### Task 13: Run migration on real `config/watchlist.yml` + manually fix

**Files:**
- Modify: `config/watchlist.yml`

- [ ] **Step 1: Backup current + run script**

```bash
uv run python scripts/migrate_watchlist_v0_3_0.py
# Backup file should appear: config/watchlist.yml.v0_1_7.bak.<timestamp>
```

- [ ] **Step 2: Manual fix-up**

Edit `config/watchlist.yml`:

For NVDA, set:
```yaml
- ticker: NVDA
  name: NVIDIA
  aliases: [英伟达, 老黄家, Jensen Huang]
  sectors: [semiconductor, ai]
  macro_links: [FOMC, CPI]
  alerts: [price_5pct, earnings, downgrade, sec_filing]
```

For 600519, set:
```yaml
- ticker: "600519"
  name: 贵州茅台
  aliases: [茅台]
  sectors: [白酒]
  macro_links: [央行, MLF, LPR]
  alerts: [price_5pct, announcement]
```

Add to `keyword_list.us`: `[Powell, recession]` (small starter set).

Confirm `sector_keywords.us` includes `semiconductor`, `ai`; `sector_keywords.cn` includes `白酒`. Add `ai` to `us` if missing.

Confirm `macro_keywords.us` includes `FOMC`, `CPI`; `macro_keywords.cn` includes `央行`, `MLF`, `LPR`.

- [ ] **Step 3: Verify schema loads**

```bash
uv run python -c "
from pathlib import Path
from news_pipeline.config.loader import ConfigLoader
snap = ConfigLoader(Path('config')).load()
print(f'✅ rules: {len(snap.watchlist.rules.us)} us, {len(snap.watchlist.rules.cn)} cn')
print(f'   matcher: {snap.watchlist.rules.matcher}')
print(f'   gray_zone_action: {snap.watchlist.rules.gray_zone_action}')
"
```
Expected: prints `✅ rules: 1 us, 1 cn` and matcher/gray_zone defaults.

- [ ] **Step 4: Commit**

```bash
git add config/watchlist.yml
git commit -m "chore(v0.3.0): migrate watchlist.yml to rules+llm format with NVDA + 600519 examples"
```

---

## Phase 4 — Pipeline Integration

### Task 14: `synth_enriched_from_rules()` helper

**Files:**
- Modify: `src/news_pipeline/scheduler/jobs.py`
- Modify: `tests/unit/scheduler/test_process_pending_rules.py` (will be created in Task 21)

- [ ] **Step 1: Write inline test in scheduler test (anticipate Task 21)**

For now, smoke test inline:

```python
# tests/unit/scheduler/test_synth_enriched.py (temporary; merged into test_process_pending_rules.py in Task 21)
from datetime import datetime, UTC

from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.enums import EventType, Magnitude, Market, Sentiment
from news_pipeline.rules.verdict import RulesVerdict
from news_pipeline.scheduler.jobs import synth_enriched_from_rules


def test_synth_basic():
    art = RawArticle(
        source="finnhub", market=Market.US,
        fetched_at=datetime(2026, 4, 26, tzinfo=UTC),
        published_at=datetime(2026, 4, 26, tzinfo=UTC),
        url="https://x/1", url_hash="h", title="t",
        body="hello world " * 30,  # > 200 chars
        title_simhash=0, raw_meta={},
    )
    verdict = RulesVerdict(
        matched=True, tickers=["NVDA"], related_tickers=["AMD"],
        sectors=["semiconductor"], markets=["us"], score_boost=70.0,
    )
    e = synth_enriched_from_rules(art, verdict, raw_id=42)
    assert e.raw_id == 42
    assert len(e.summary) <= 200
    assert e.related_tickers == ["AMD", "NVDA"]
    assert e.sectors == ["semiconductor"]
    assert e.event_type == EventType.OTHER
    assert e.sentiment == Sentiment.NEUTRAL
    assert e.magnitude == Magnitude.LOW
    assert e.confidence == 0.0
    assert e.model_used == "rules-only"


def test_synth_empty_body_uses_title():
    art = RawArticle(
        source="x", market=Market.US,
        fetched_at=datetime(2026, 4, 26, tzinfo=UTC),
        published_at=datetime(2026, 4, 26, tzinfo=UTC),
        url="https://x/1", url_hash="h", title="The Title",
        body=None, title_simhash=0, raw_meta={},
    )
    verdict = RulesVerdict(matched=True, tickers=["NVDA"], score_boost=50.0)
    e = synth_enriched_from_rules(art, verdict, raw_id=1)
    assert e.summary == "The Title"
```

- [ ] **Step 2: Run — fail**

Run: `uv run pytest tests/unit/scheduler/test_synth_enriched.py -v`
Expected: FAIL — `synth_enriched_from_rules` not defined in jobs.py.

- [ ] **Step 3: Implement (add to scheduler/jobs.py top-level functions)**

In `src/news_pipeline/scheduler/jobs.py`, add this function near the top (after imports):

```python
from news_pipeline.common.contracts import EnrichedNews
from news_pipeline.common.enums import EventType, Magnitude, Sentiment
from news_pipeline.common.timeutil import utc_now
from news_pipeline.rules.verdict import RulesVerdict


def synth_enriched_from_rules(
    art: RawArticle, verdict: RulesVerdict, *, raw_id: int
) -> EnrichedNews:
    """Build EnrichedNews from rules match without invoking LLM.

    Rules-only mode: summary = body[:200] truncation. sentiment/magnitude
    default to neutral/low (no LLM inference). model_used='rules-only' so
    push_log + downstream can distinguish.
    """
    body = art.body or ""
    body_excerpt = body[:200].rstrip()
    summary = body_excerpt or art.title

    related = sorted(set(verdict.tickers + verdict.related_tickers))

    return EnrichedNews(
        raw_id=raw_id,
        summary=summary,
        related_tickers=related,
        sectors=list(verdict.sectors),
        event_type=EventType.OTHER,
        sentiment=Sentiment.NEUTRAL,
        magnitude=Magnitude.LOW,
        confidence=0.0,
        key_quotes=[],
        entities=[],
        relations=[],
        model_used="rules-only",
        extracted_at=utc_now().replace(tzinfo=None),
    )
```

- [ ] **Step 4: Run — pass**

Run: `uv run pytest tests/unit/scheduler/test_synth_enriched.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/scheduler/jobs.py tests/unit/scheduler/test_synth_enriched.py
git commit -m "feat(v0.3.0): add synth_enriched_from_rules() helper for rules-only mode"
```

---

### Task 15: `LLMPipeline.process_with_rules()` method

**Files:**
- Modify: `src/news_pipeline/llm/pipeline.py`
- Modify: `tests/unit/llm/test_pipeline.py`

- [ ] **Step 1: Write test (append to existing file)**

Append to `tests/unit/llm/test_pipeline.py`:

```python
@pytest.mark.asyncio
async def test_process_with_rules_routes_to_tier2_when_ticker_hit():
    classifier = MagicMock()
    tier1 = MagicMock(); tier1.summarize = AsyncMock()
    tier2 = MagicMock(); tier2.extract = AsyncMock(return_value="enriched_t2")
    router = MagicMock()
    cost = MagicMock(); cost.check = MagicMock()

    p = LLMPipeline(
        classifier, tier1, tier2, router, cost,
        watchlist_us=["NVDA"], watchlist_cn=[],
    )
    p._first_party_sources = {"sec_edgar"}  # set on instance for test

    from news_pipeline.rules.verdict import RulesVerdict
    art = _art()  # uses helper from earlier in this test file
    verdict = RulesVerdict(matched=True, tickers=["NVDA"], score_boost=50.0)

    out = await p.process_with_rules(art, verdict, raw_id=1)
    assert out == "enriched_t2"
    tier2.extract.assert_awaited_once()
    tier1.summarize.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_with_rules_routes_to_tier1_when_no_ticker():
    classifier = MagicMock()
    tier1 = MagicMock(); tier1.summarize = AsyncMock(return_value="enriched_t1")
    tier2 = MagicMock(); tier2.extract = AsyncMock()
    router = MagicMock()
    cost = MagicMock(); cost.check = MagicMock()

    p = LLMPipeline(
        classifier, tier1, tier2, router, cost,
        watchlist_us=[], watchlist_cn=[],
    )
    p._first_party_sources = set()

    from news_pipeline.rules.verdict import RulesVerdict
    art = _art(source="generic")
    verdict = RulesVerdict(matched=True, sectors=["semi"], score_boost=20.0)

    out = await p.process_with_rules(art, verdict, raw_id=1)
    assert out == "enriched_t1"
    tier1.summarize.assert_awaited_once()
    tier2.extract.assert_not_awaited()
```

If `_first_party_sources` doesn't exist as attr yet, the helper sets it in next step.

- [ ] **Step 2: Run — fail**

Run: `uv run pytest tests/unit/llm/test_pipeline.py -v`
Expected: 2 new tests fail (process_with_rules not defined).

- [ ] **Step 3: Implement (add method to LLMPipeline class)**

In `src/news_pipeline/llm/pipeline.py`, add:

```python
# Inside LLMPipeline class (after existing process method):

async def process_with_rules(
    self, art: RawArticle, verdict: "RulesVerdict", *, raw_id: int
) -> EnrichedNews | None:
    """Rules + LLM mode: rules already classified relevant, skip Tier-0.
    Use verdict to choose between Tier-1 (summary) and Tier-2 (deep extract).
    """
    self._cost.check()
    from news_pipeline.rules.verdict import RulesVerdict  # local import to avoid cycle

    # Direct ticker hit OR first-party source → Tier-2 deep extract
    fps = getattr(self, "_first_party_sources", set())
    if verdict.tickers or art.source in fps:
        return await self._t2.extract(art, raw_id=raw_id, recent_context="")
    # Otherwise just summarize
    return await self._t1.summarize(art, raw_id=raw_id)
```

Also at top of file, add to imports:
```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from news_pipeline.rules.verdict import RulesVerdict
```

And add `_first_party_sources: set[str] = set()` as a class attribute (or keep as MAGIC for tests). Better: add to `__init__`:

```python
def __init__(
    self,
    classifier: Tier0Classifier,
    tier1: Tier1Summarizer,
    tier2: Tier2DeepExtractor,
    router: LLMRouter,
    cost_tracker: CostTracker,
    watchlist_us: list[str],
    watchlist_cn: list[str],
    first_party_sources: set[str] | None = None,  # NEW
) -> None:
    self._cls = classifier
    self._t1 = tier1
    self._t2 = tier2
    self._router = router
    self._cost = cost_tracker
    self._wl_us = watchlist_us
    self._wl_cn = watchlist_cn
    self._first_party_sources = first_party_sources or set()
```

- [ ] **Step 4: Run — pass**

Run: `uv run pytest tests/unit/llm/test_pipeline.py -v`
Expected: all (5+) passed.

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/llm/pipeline.py tests/unit/llm/test_pipeline.py
git commit -m "feat(v0.3.0): LLMPipeline.process_with_rules — skip Tier-0 when rules already classified"
```

---

### Task 16: `classifier/importance.py` — accept verdict + gray_zone_action

**Files:**
- Modify: `src/news_pipeline/classifier/importance.py`
- Modify: `tests/unit/classifier/test_importance.py`

- [ ] **Step 1: Write test (append)**

Append to `tests/unit/classifier/test_importance.py`:

```python
from news_pipeline.rules.verdict import RulesVerdict


@pytest.mark.asyncio
async def test_score_with_rules_verdict_applies_boost():
    rules = MagicMock(); rules.evaluate.return_value = []
    rules.score = lambda hits: 0
    judge = MagicMock(); judge.judge = AsyncMock()
    cls = ImportanceClassifier(
        rules=rules, judge=judge, gray_zone=(40, 70),
        watchlist_tickers=["NVDA"],
        gray_zone_action="digest",
        llm_enabled=False,
    )
    verdict = RulesVerdict(matched=True, tickers=["NVDA"], score_boost=50.0)
    scored = await cls.score_news(_e(), source="finnhub", verdict=verdict)
    # 0 base + 50 boost = 50, in gray zone, llm_enabled=False, action=digest
    assert scored.score == 50.0
    assert scored.is_critical is False
    assert "rules-only-grayzone-digest" in (scored.llm_reason or "")


@pytest.mark.asyncio
async def test_gray_zone_action_push():
    rules = MagicMock(); rules.evaluate.return_value = []
    rules.score = lambda hits: 0
    judge = MagicMock()
    cls = ImportanceClassifier(
        rules=rules, judge=judge, gray_zone=(40, 70),
        watchlist_tickers=[],
        gray_zone_action="push",
        llm_enabled=False,
    )
    verdict = RulesVerdict(matched=True, sectors=["semi"], score_boost=50.0)
    scored = await cls.score_news(_e(), source="x", verdict=verdict)
    assert scored.is_critical is True


@pytest.mark.asyncio
async def test_gray_zone_action_skip_marks_negative_score():
    rules = MagicMock(); rules.evaluate.return_value = []
    rules.score = lambda hits: 0
    judge = MagicMock()
    cls = ImportanceClassifier(
        rules=rules, judge=judge, gray_zone=(40, 70),
        watchlist_tickers=[],
        gray_zone_action="skip",
        llm_enabled=False,
    )
    verdict = RulesVerdict(matched=True, sectors=["semi"], score_boost=50.0)
    scored = await cls.score_news(_e(), source="x", verdict=verdict)
    assert scored.is_critical is False
    # router will look at score < 0 → drop entirely
    assert scored.score < 0


@pytest.mark.asyncio
async def test_high_score_critical_no_judge_call_with_verdict():
    rules = MagicMock()
    rules.evaluate.return_value = [RuleHit("first_party_source", 30)]
    rules.score = lambda hits: 30
    judge = MagicMock(); judge.judge = AsyncMock()
    cls = ImportanceClassifier(
        rules=rules, judge=judge, gray_zone=(40, 70),
        watchlist_tickers=[],
        gray_zone_action="digest",
        llm_enabled=True,
    )
    # 30 base + 50 ticker boost = 80 ≥ 70 → critical
    verdict = RulesVerdict(matched=True, tickers=["NVDA"], score_boost=50.0)
    scored = await cls.score_news(_e(), source="sec_edgar", verdict=verdict)
    assert scored.is_critical is True
    judge.judge.assert_not_awaited()
```

- [ ] **Step 2: Run — fail**

Run: `uv run pytest tests/unit/classifier/test_importance.py -v`
Expected: 4 new tests fail (signature mismatch — score_news doesn't accept verdict yet).

- [ ] **Step 3: Modify `score_news` signature + add fields**

In `src/news_pipeline/classifier/importance.py`, modify the class:

```python
from typing import Literal

from news_pipeline.rules.verdict import RulesVerdict


class ImportanceClassifier:
    def __init__(
        self, *,
        rules: RuleEngine,
        judge: LLMJudge,
        gray_zone: tuple[float, float],
        watchlist_tickers: list[str],
        gray_zone_action: Literal["skip", "digest", "push"] = "digest",
        llm_enabled: bool = True,
    ) -> None:
        self._rules = rules
        self._judge = judge
        self._lo, self._hi = gray_zone
        self._wl = watchlist_tickers
        self._gray_zone_action = gray_zone_action
        self._llm_enabled = llm_enabled

    async def score_news(
        self,
        e: EnrichedNews,
        *,
        source: str,
        verdict: RulesVerdict | None = None,
    ) -> ScoredNews:
        rule_hits = self._rules.evaluate(e, source=source)
        score = float(self._rules.score(rule_hits))
        rule_names = [h.name for h in rule_hits]

        if verdict is not None and verdict.matched:
            score += verdict.score_boost
            rule_names.append(f"rules_{','.join(verdict.markets)}")
        score = min(100.0, score)

        if score >= self._hi:
            return ScoredNews(
                enriched=e, score=score, is_critical=True,
                rule_hits=rule_names, llm_reason=None,
            )
        if score < self._lo:
            return ScoredNews(
                enriched=e, score=score, is_critical=False,
                rule_hits=rule_names, llm_reason=None,
            )

        # Gray zone
        if not self._llm_enabled:
            action = self._gray_zone_action
            if action == "push":
                is_crit = True
                gz_reason = "rules-only-grayzone-push"
            elif action == "skip":
                # Mark with negative score so router can drop entirely
                score = -1.0
                is_crit = False
                gz_reason = "rules-only-grayzone-skip"
            else:  # digest
                is_crit = False
                gz_reason = "rules-only-grayzone-digest"
            return ScoredNews(
                enriched=e, score=score, is_critical=is_crit,
                rule_hits=rule_names, llm_reason=gz_reason,
            )

        # LLM-enabled gray zone: judge
        is_crit, reason = await self._judge.judge(
            e, watchlist_tickers=self._wl,
        )
        return ScoredNews(
            enriched=e, score=score, is_critical=is_crit,
            rule_hits=rule_names, llm_reason=reason,
        )
```

- [ ] **Step 4: Update existing tests where `ImportanceClassifier(...)` is constructed**

Find all `ImportanceClassifier(...)` calls in `tests/unit/classifier/test_importance.py` and add `gray_zone_action="digest"` and `llm_enabled=True` to each (preserve existing behavior). The test from Task 16 Step 1 already has these. Existing tests (`test_high_score_critical_no_judge`, etc.) — add `gray_zone_action="digest", llm_enabled=True` to constructor.

- [ ] **Step 5: Run — pass**

Run: `uv run pytest tests/unit/classifier/test_importance.py -v`
Expected: all passed.

- [ ] **Step 6: Commit**

```bash
git add src/news_pipeline/classifier/importance.py tests/unit/classifier/test_importance.py
git commit -m "feat(v0.3.0): ImportanceClassifier accepts RulesVerdict + gray_zone_action config"
```

---

### Task 17: `pushers/common/message_builder.py` — `build_from_rules()`

**Files:**
- Modify: `src/news_pipeline/pushers/common/message_builder.py`
- Modify: `tests/unit/pushers/test_message_builder.py`

- [ ] **Step 1: Write test (append)**

Append to `tests/unit/pushers/test_message_builder.py`:

```python
from news_pipeline.rules.verdict import RulesVerdict


def test_build_from_rules_includes_verdict_badges():
    art, scored = _make()  # existing helper that returns (RawArticle, ScoredNews)
    verdict = RulesVerdict(
        matched=True,
        tickers=["NVDA"],
        related_tickers=["AMD"],
        sectors=["semiconductor"],
        macros=["FOMC"],
        markets=["us"],
        score_boost=85.0,
    )
    b = MessageBuilder(source_labels={"reuters": "Reuters"})
    msg = b.build_from_rules(art, scored, verdict)
    badge_texts = [bd.text for bd in msg.badges]
    assert "NVDA" in badge_texts
    assert "AMD" in badge_texts
    assert "#semiconductor" in badge_texts
    assert any("FOMC" in t for t in badge_texts)
    assert "rules" in badge_texts


def test_build_from_rules_generic_only():
    art, scored = _make()
    verdict = RulesVerdict(
        matched=True,
        generic_hits=["powell"],
        markets=["us"],
        score_boost=0.0,
    )
    b = MessageBuilder(source_labels={"reuters": "Reuters"})
    msg = b.build_from_rules(art, scored, verdict)
    badge_texts = [bd.text for bd in msg.badges]
    assert any("powell" in t for t in badge_texts)
    assert "rules" in badge_texts
```

- [ ] **Step 2: Run — fail**

Expected: `build_from_rules` not defined.

- [ ] **Step 3: Implement**

In `src/news_pipeline/pushers/common/message_builder.py`, add to `MessageBuilder`:

```python
from news_pipeline.rules.verdict import RulesVerdict


# Inside MessageBuilder class:
def build_from_rules(
    self,
    art: RawArticle,
    scored: ScoredNews,
    verdict: RulesVerdict,
    *,
    chart_url: str | None = None,
) -> CommonMessage:
    """Rules-only mode message construction. Differs from build():
    - badges driven by verdict (tickers + related + sectors + macros + generic)
    - rules badge added to indicate data source
    - summary comes from EnrichedNews.summary (which is body[:200] in rules-only)
    """
    e = scored.enriched
    badges: list[Badge] = []
    for t in (verdict.tickers + verdict.related_tickers)[:5]:
        badges.append(Badge(text=t, color="blue"))
    for s in verdict.sectors[:2]:
        badges.append(Badge(text=f"#{s}", color="gray"))
    if verdict.macros:
        badges.append(Badge(text=f"📊 {verdict.macros[0]}", color="yellow"))
    if verdict.generic_hits:
        badges.append(Badge(text=f"🔖 {verdict.generic_hits[0]}", color="gray"))
    badges.append(Badge(text="rules", color="green"))

    deeplinks = [Deeplink(label="原文", url=str(art.url))]
    for t in (verdict.tickers + verdict.related_tickers)[:3]:
        if art.market == Market.US:
            deeplinks.append(Deeplink(
                label=f"Yahoo {t}",
                url=f"https://finance.yahoo.com/quote/{t}",
            ))
        else:
            prefix = "sh" if t.startswith("6") else "sz"
            deeplinks.append(Deeplink(
                label=f"东财 {t}",
                url=f"https://quote.eastmoney.com/{prefix}{t}.html",
            ))

    return CommonMessage(
        title=art.title,
        summary=e.summary,  # body[:200] from synth_enriched_from_rules
        source_label=self._labels.get(art.source, art.source),
        source_url=str(art.url),
        badges=badges,
        chart_url=chart_url,
        chart_image=None,
        deeplinks=deeplinks,
        market=art.market,
    )
```

- [ ] **Step 4: Run — pass**

Run: `uv run pytest tests/unit/pushers/test_message_builder.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/pushers/common/message_builder.py tests/unit/pushers/test_message_builder.py
git commit -m "feat(v0.3.0): MessageBuilder.build_from_rules for rules-only mode"
```

---

### Task 18: `router/routes.py` — `markets` parameter

**Files:**
- Modify: `src/news_pipeline/router/routes.py`
- Modify: `tests/unit/router/test_routes.py`

- [ ] **Step 1: Append test**

```python
def test_route_with_markets_param_multi():
    r = DispatchRouter(channels_by_market={
        "us": ["tg_us", "feishu_us"],
        "cn": ["tg_cn", "feishu_cn"],
    })
    msg = _msg(Market.US)  # existing helper
    plans = r.route(_scored("us", critical=True), msg, markets=["us", "cn"])
    assert len(plans) == 2
    market_channels = {tuple(sorted(p.channels)) for p in plans}
    assert ("feishu_us", "tg_us") in market_channels
    assert ("feishu_cn", "tg_cn") in market_channels


def test_route_without_markets_falls_back_to_msg_market():
    r = DispatchRouter(channels_by_market={
        "us": ["tg_us"],
        "cn": ["tg_cn"],
    })
    msg = _msg(Market.US)
    plans = r.route(_scored("us", critical=True), msg)
    assert len(plans) == 1
    assert "tg_us" in plans[0].channels
```

- [ ] **Step 2: Run — fail**

Expected: `markets` is unknown kwarg.

- [ ] **Step 3: Modify `DispatchRouter.route`**

In `src/news_pipeline/router/routes.py`:

```python
def route(
    self,
    scored: ScoredNews,
    msg: CommonMessage,
    *,
    markets: list[str] | None = None,
) -> list[DispatchPlan]:
    """Route a scored news to one or more market channel sets.

    `markets`: explicit list of markets to route to (used by rules engine
    when a single article hits multiple markets — e.g., 'FOMC 影响 A 股').
    None defaults to [msg.market.value] (single market).
    """
    target_markets = markets or [msg.market.value]
    plans: list[DispatchPlan] = []
    for mkt in target_markets:
        channels = self._by_market.get(mkt, [])
        if not channels:
            continue
        plans.append(DispatchPlan(
            message=msg, channels=channels, immediate=scored.is_critical,
        ))
    return plans
```

- [ ] **Step 4: Run — pass**

Run: `uv run pytest tests/unit/router/test_routes.py -v`
Expected: all (existing + 2 new) passed.

- [ ] **Step 5: Commit**

```bash
git add src/news_pipeline/router/routes.py tests/unit/router/test_routes.py
git commit -m "feat(v0.3.0): DispatchRouter.route accepts markets list for multi-market hits"
```

---

### Task 19: `scheduler/jobs.py:process_pending` — rules pre-filter

**Files:**
- Modify: `src/news_pipeline/scheduler/jobs.py`

- [ ] **Step 1: Write integration test (this becomes the comprehensive Task 21)**

Defer comprehensive test to Task 21; for this task just modify the function and run all existing scheduler tests after.

- [ ] **Step 2: Modify signature + body of `process_pending`**

In `src/news_pipeline/scheduler/jobs.py`, replace `process_pending` with:

```python
async def process_pending(
    *,
    raw_dao: RawNewsDAO,
    llm: LLMPipeline,
    rules_engine: "RulesEngine | None",   # NEW: None when rules.enable=False
    importance: ImportanceClassifier,
    proc_dao: NewsProcessedDAO,
    msg_builder: MessageBuilder,
    router: DispatchRouter,
    dispatcher: PusherDispatcher,
    push_log: PushLogDAO,
    digest_dao: DigestBufferDAO,
    burst: BurstSuppressor,
    rules_enabled: bool,                  # NEW
    llm_enabled: bool,                    # NEW
    batch_size: int = 25,
) -> int:
    """Pull pending raw_news, run pipeline based on rules/llm enable flags."""
    pending = await raw_dao.list_pending(limit=batch_size)
    processed = 0
    for raw in pending:
        art = _raw_to_article(raw)

        # === 1. Rules gate ===
        verdict = None
        if rules_enabled and rules_engine is not None:
            verdict = rules_engine.match(art)
            if not verdict.matched:
                await raw_dao.mark_status(raw.id, "skipped_rules")  # type: ignore[arg-type]
                continue

        # === 2. EnrichedNews source ===
        if llm_enabled:
            try:
                if verdict is not None and verdict.matched:
                    enriched = await llm.process_with_rules(art, verdict, raw_id=raw.id)  # type: ignore[arg-type]
                else:
                    enriched = await llm.process(art, raw_id=raw.id)  # type: ignore[arg-type]
            except Exception as e:
                log.error("llm_failed", raw_id=raw.id, error=str(e))
                await raw_dao.mark_status(raw.id, "dead", error=str(e))  # type: ignore[arg-type]
                continue
            if enriched is None:
                await raw_dao.mark_status(raw.id, "skipped")  # type: ignore[arg-type]
                continue
        else:
            # rules-only mode: no LLM, synth from rules
            assert verdict is not None and verdict.matched, \
                "rules-only mode requires rules.enable=True and rules.match=True"
            enriched = synth_enriched_from_rules(art, verdict, raw_id=raw.id)  # type: ignore[arg-type]

        # === 3. Score ===
        scored = await importance.score_news(
            enriched, source=raw.source, verdict=verdict,
        )

        # Skip "skip" gray zone (negative score signal)
        if scored.score < 0:
            await raw_dao.mark_status(raw.id, "skipped_grayzone")  # type: ignore[arg-type]
            continue

        proc_id = await proc_dao.insert(
            raw_id=raw.id,  # type: ignore[arg-type]
            summary=enriched.summary,
            event_type=enriched.event_type.value,
            sentiment=enriched.sentiment.value,
            magnitude=enriched.magnitude.value,
            confidence=enriched.confidence,
            key_quotes=enriched.key_quotes,
            score=scored.score,
            is_critical=scored.is_critical,
            rule_hits=scored.rule_hits,
            llm_reason=scored.llm_reason,
            model_used=enriched.model_used,
            extracted_at=enriched.extracted_at,
        )
        await raw_dao.mark_status(raw.id, "processed")  # type: ignore[arg-type]

        # === 4. Render + route + push ===
        if llm_enabled:
            msg = msg_builder.build(art, scored, chart_url=None)
        else:
            msg = msg_builder.build_from_rules(art, scored, verdict)  # type: ignore[arg-type]

        plans = router.route(
            scored, msg,
            markets=verdict.markets if verdict is not None else None,
        )

        for p in plans:
            if p.immediate:
                if not burst.should_send(enriched.related_tickers):
                    log.info("push_suppressed_burst",
                             tickers=enriched.related_tickers)
                    continue
                results = await dispatcher.dispatch(p.message, channels=p.channels)
                for ch, r in results.items():
                    await push_log.write(
                        news_id=proc_id,
                        channel=ch,
                        status=("ok" if r.ok else "failed"),
                        http_status=r.http_status,
                        response=r.response_body,
                        retries=r.retries,
                    )
            else:
                # gray zone or non-critical → digest
                await digest_dao.enqueue(
                    news_id=proc_id,
                    market=art.market.value,
                    scheduled_digest=_choose_digest_key(art.market, utc_now()),
                )
                break  # one digest entry per news

        processed += 1
    return processed
```

- [ ] **Step 3: Run existing scheduler tests — likely some break due to signature change**

Run: `uv run pytest tests/unit/scheduler/ -v`
Expected: existing `test_process_and_digest.py` tests fail because `process_pending` signature changed.

- [ ] **Step 4: Update existing tests**

In `tests/unit/scheduler/test_process_and_digest.py`, find `process_pending(...)` calls and add the new params:
- `rules_engine=None` (or a MagicMock for new tests)
- `rules_enabled=False`
- `llm_enabled=True`

This preserves the existing test behavior (LLM-only mode).

Remove `archive=`, `archive_enabled=` if those params are still passed (already removed in v0.1.6 — should be fine).

- [ ] **Step 5: Run again — pass**

Run: `uv run pytest tests/unit/scheduler/ -v`
Expected: passed.

- [ ] **Step 6: Commit**

```bash
git add src/news_pipeline/scheduler/jobs.py tests/unit/scheduler/test_process_and_digest.py
git commit -m "feat(v0.3.0): process_pending integrates rules pre-filter + 4 enable combos"
```

---

### Task 20: `main.py` — wire RulesEngine + at_least_one_enabled check

**Files:**
- Modify: `src/news_pipeline/main.py`

- [ ] **Step 1: Modify _amain() — add RulesEngine wiring**

In `src/news_pipeline/main.py`, find where snap is loaded and pipeline is built. Add:

```python
# After snap = loader.load(), before db = Database(...):

# === Rules engine (v0.3.0) ===
from news_pipeline.rules.engine import RulesEngine
from news_pipeline.rules.matcher import build_matcher

rules_enabled = snap.watchlist.rules.enable
llm_enabled = snap.watchlist.llm.enable

if not rules_enabled and not llm_enabled:
    log.error("watchlist_both_disabled_aborting")
    raise SystemExit(2)

rules_engine = None
if rules_enabled:
    matcher = build_matcher(
        snap.watchlist.rules.matcher,
        snap.watchlist.rules.matcher_options,
    )
    rules_engine = RulesEngine(snap.watchlist.rules, matcher)
    log.info(
        "rules_engine_built",
        us_tickers=len(snap.watchlist.rules.us),
        cn_tickers=len(snap.watchlist.rules.cn),
        matcher=snap.watchlist.rules.matcher,
    )
```

Find where `ImportanceClassifier(...)` is constructed and pass new args:

```python
importance = ImportanceClassifier(
    rules=rules,
    judge=judge,
    gray_zone=tuple(snap.app.classifier.llm_fallback_when_score),
    watchlist_tickers=[w.ticker for w in snap.watchlist.rules.us]
                      + [w.ticker for w in snap.watchlist.rules.cn]
                      + snap.watchlist.llm.us
                      + snap.watchlist.llm.cn,
    gray_zone_action=snap.watchlist.rules.gray_zone_action,
    llm_enabled=llm_enabled,
)
```

Find `LLMPipeline(...)` construction — add `first_party_sources={"sec_edgar", "juchao", "caixin_telegram"}`:

```python
llm = LLMPipeline(
    tier0, tier1, tier2, routerL, cost,
    watchlist_us=[w.ticker for w in snap.watchlist.rules.us]
                 + snap.watchlist.llm.us,
    watchlist_cn=[w.ticker for w in snap.watchlist.rules.cn]
                 + snap.watchlist.llm.cn,
    first_party_sources={"sec_edgar", "juchao", "caixin_telegram"},
)
```

Find `process_pending(...)` calls — add new args:

```python
await process_pending(
    raw_dao=raw_dao,
    llm=llm,
    rules_engine=rules_engine,
    importance=importance,
    proc_dao=proc_dao,
    msg_builder=msg_builder,
    router=dispatch_router,
    dispatcher=dispatcher,
    push_log=push_log,
    digest_dao=digest_dao,
    burst=burst,
    rules_enabled=rules_enabled,
    llm_enabled=llm_enabled,
)
```

- [ ] **Step 2: Manual smoke test**

```bash
uv run python -c "from news_pipeline.main import main; print('main importable')"
```
Expected: `main importable` (no error).

- [ ] **Step 3: Run full test suite**

Run: `uv run pytest -q`
Expected: all passing (or close to it; fix anything obvious).

Run: `uv run ruff check src/ tests/`
Expected: clean.

Run: `uv run mypy src/`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add src/news_pipeline/main.py
git commit -m "feat(v0.3.0): wire RulesEngine into main + new ImportanceClassifier/LLMPipeline ctor args"
```

---

## Phase 5 — Tests

### Task 21: Comprehensive `process_pending` integration test

**Files:**
- Create: `tests/unit/scheduler/test_process_pending_rules.py`
- Delete: `tests/unit/scheduler/test_synth_enriched.py` (merged here)

- [ ] **Step 1: Write the test file**

```python
# tests/unit/scheduler/test_process_pending_rules.py
"""Comprehensive end-to-end-ish tests for process_pending across 4 enable combos."""

from datetime import datetime, UTC
from unittest.mock import AsyncMock, MagicMock

import pytest

from news_pipeline.common.contracts import EnrichedNews, RawArticle
from news_pipeline.common.enums import EventType, Magnitude, Market, Sentiment
from news_pipeline.rules.verdict import RulesVerdict
from news_pipeline.scheduler.jobs import process_pending, synth_enriched_from_rules


def _enriched() -> EnrichedNews:
    return EnrichedNews(
        raw_id=1, summary="s", related_tickers=["NVDA"], sectors=[],
        event_type=EventType.OTHER, sentiment=Sentiment.BEARISH,
        magnitude=Magnitude.HIGH, confidence=0.9, key_quotes=[],
        entities=[], relations=[], model_used="x",
        extracted_at=datetime(2026, 4, 26),
    )


def _pending_row(rid: int = 1):
    m = MagicMock(
        id=rid, source="finnhub", market="us", url="https://x/1",
        url_hash="h", title="NVDA news", title_simhash=0,
        body="NVDA earnings beat estimates by 10%",
        raw_meta={}, fetched_at=datetime(2026, 4, 26, tzinfo=UTC),
        published_at=datetime(2026, 4, 26, tzinfo=UTC),
    )
    return m


def _setup_mocks():
    raw_dao = MagicMock()
    raw_dao.list_pending = AsyncMock(return_value=[_pending_row()])
    raw_dao.mark_status = AsyncMock()

    rules_engine = MagicMock()

    llm = MagicMock()
    llm.process = AsyncMock(return_value=_enriched())
    llm.process_with_rules = AsyncMock(return_value=_enriched())

    importance = MagicMock()
    from news_pipeline.common.contracts import ScoredNews
    importance.score_news = AsyncMock(return_value=ScoredNews(
        enriched=_enriched(), score=80, is_critical=True,
        rule_hits=[], llm_reason=None,
    ))

    proc_dao = MagicMock(); proc_dao.insert = AsyncMock(return_value=42)
    msg_builder = MagicMock()
    from news_pipeline.common.contracts import CommonMessage
    msg_builder.build = MagicMock(return_value=CommonMessage(
        title="t", summary="s", source_label="x",
        source_url="https://x.com", badges=[], chart_url=None,
        deeplinks=[], market=Market.US,
    ))
    msg_builder.build_from_rules = MagicMock(return_value=CommonMessage(
        title="t", summary="s", source_label="x",
        source_url="https://x.com", badges=[], chart_url=None,
        deeplinks=[], market=Market.US,
    ))

    router = MagicMock()
    router.route = MagicMock(return_value=[
        MagicMock(channels=["tg_us"], immediate=True,
                  message=msg_builder.build.return_value),
    ])

    dispatcher = MagicMock()
    send_result = MagicMock(ok=True, http_status=200, response_body="", retries=0)
    dispatcher.dispatch = AsyncMock(return_value={"tg_us": send_result})

    push_log = MagicMock(); push_log.write = AsyncMock()
    digest_dao = MagicMock(); digest_dao.enqueue = AsyncMock()
    burst = MagicMock(); burst.should_send = MagicMock(return_value=True)

    return dict(
        raw_dao=raw_dao, llm=llm, rules_engine=rules_engine,
        importance=importance, proc_dao=proc_dao, msg_builder=msg_builder,
        router=router, dispatcher=dispatcher, push_log=push_log,
        digest_dao=digest_dao, burst=burst,
    )


@pytest.mark.asyncio
async def test_rules_only_match_synth_path():
    """rules.enable=True, llm.enable=False → match → synth_enriched, push."""
    mocks = _setup_mocks()
    mocks["rules_engine"].match = MagicMock(return_value=RulesVerdict(
        matched=True, tickers=["NVDA"], markets=["us"], score_boost=50.0,
    ))
    n = await process_pending(
        rules_enabled=True, llm_enabled=False, **mocks,
    )
    assert n == 1
    mocks["llm"].process.assert_not_awaited()
    mocks["llm"].process_with_rules.assert_not_awaited()
    mocks["msg_builder"].build_from_rules.assert_called_once()
    mocks["dispatcher"].dispatch.assert_awaited_once()


@pytest.mark.asyncio
async def test_rules_only_no_match_skipped():
    mocks = _setup_mocks()
    mocks["rules_engine"].match = MagicMock(return_value=RulesVerdict(matched=False))
    n = await process_pending(
        rules_enabled=True, llm_enabled=False, **mocks,
    )
    assert n == 0
    mocks["raw_dao"].mark_status.assert_awaited_with(1, "skipped_rules")
    mocks["dispatcher"].dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_rules_plus_llm_match_uses_process_with_rules():
    mocks = _setup_mocks()
    mocks["rules_engine"].match = MagicMock(return_value=RulesVerdict(
        matched=True, tickers=["NVDA"], markets=["us"], score_boost=50.0,
    ))
    n = await process_pending(
        rules_enabled=True, llm_enabled=True, **mocks,
    )
    assert n == 1
    mocks["llm"].process_with_rules.assert_awaited_once()
    mocks["llm"].process.assert_not_awaited()


@pytest.mark.asyncio
async def test_llm_only_uses_legacy_process():
    """rules.enable=False, llm.enable=True → traditional Tier-0 path."""
    mocks = _setup_mocks()
    n = await process_pending(
        rules_enabled=False, llm_enabled=True,
        rules_engine=None,
        **{k: v for k, v in mocks.items() if k != "rules_engine"},
    )
    assert n == 1
    mocks["llm"].process.assert_awaited_once()
    mocks["llm"].process_with_rules.assert_not_awaited()
    mocks["msg_builder"].build.assert_called_once()
    mocks["msg_builder"].build_from_rules.assert_not_called()


@pytest.mark.asyncio
async def test_rules_only_grayzone_skip_no_push():
    mocks = _setup_mocks()
    from news_pipeline.common.contracts import ScoredNews
    mocks["importance"].score_news = AsyncMock(return_value=ScoredNews(
        enriched=_enriched(), score=-1.0, is_critical=False,
        rule_hits=[], llm_reason="rules-only-grayzone-skip",
    ))
    mocks["rules_engine"].match = MagicMock(return_value=RulesVerdict(
        matched=True, sectors=["semi"], markets=["us"], score_boost=20.0,
    ))
    n = await process_pending(
        rules_enabled=True, llm_enabled=False, **mocks,
    )
    assert n == 0  # skipped before push
    mocks["raw_dao"].mark_status.assert_awaited_with(1, "skipped_grayzone")
    mocks["dispatcher"].dispatch.assert_not_awaited()


def test_synth_enriched_basic():
    """Inline test of synth helper (kept here to avoid extra file)."""
    art = RawArticle(
        source="finnhub", market=Market.US,
        fetched_at=datetime(2026, 4, 26, tzinfo=UTC),
        published_at=datetime(2026, 4, 26, tzinfo=UTC),
        url="https://x/1", url_hash="h", title="t",
        body="hello world " * 30,
        title_simhash=0, raw_meta={},
    )
    verdict = RulesVerdict(
        matched=True, tickers=["NVDA"], related_tickers=["AMD"],
        sectors=["semi"], markets=["us"], score_boost=70.0,
    )
    e = synth_enriched_from_rules(art, verdict, raw_id=42)
    assert e.raw_id == 42
    assert len(e.summary) <= 200
    assert e.related_tickers == ["AMD", "NVDA"]
    assert e.sentiment == Sentiment.NEUTRAL
    assert e.confidence == 0.0
    assert e.model_used == "rules-only"
```

- [ ] **Step 2: Delete the temporary `test_synth_enriched.py`**

```bash
rm tests/unit/scheduler/test_synth_enriched.py
```

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/unit/scheduler/ -v`
Expected: all passed (existing + 6 new in test_process_pending_rules.py).

- [ ] **Step 4: Commit**

```bash
git add tests/unit/scheduler/
git commit -m "test(v0.3.0): comprehensive process_pending tests for 4 enable combos + grayzone-skip"
```

---

## Phase 6 — Final verification + version bump

### Task 22: Full test + lint + type check

**Files:** none

- [ ] **Step 1: Full suite**

```bash
uv run pytest -q
```
Expected: all passing. If anything red, fix inline.

- [ ] **Step 2: Lint**

```bash
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
```
Expected: clean. If formatting issues, run `uv run ruff format src/ tests/` and re-commit as `chore(v0.3.0): ruff format`.

- [ ] **Step 3: Type check**

```bash
uv run mypy src/
```
Expected: clean. Fix any new type errors introduced by the changes.

- [ ] **Step 4: Manual smoke**

```bash
NEWS_PIPELINE_ONCE=1 uv run python -m news_pipeline.main 2>&1 | tail -20
```
Expected: runs cleanly, scrape happens, rules engine logs `rules_engine_built` line, no errors.

- [ ] **Step 5: Commit if any fixes were made**

```bash
git add -u
git commit -m "chore(v0.3.0): post-impl lint/format/type fixes" || echo "nothing to commit"
```

---

### Task 23: Update mkdocs pages (remove "planned" labels)

**Files:**
- Modify: `docs/components/rules.md`
- Modify: `mkdocs.yml`

- [ ] **Step 1: Remove "planned" admonition from rules.md**

In `docs/components/rules.md`, replace the top admonition:

```markdown
!!! info "状态：设计完成，待实施"
    本页描述 v0.3.0 的 watchlist 重设计...
```

with:

```markdown
!!! success "状态：v0.3.0 已上线"
    本页是当前生产生效的 watchlist 双段架构。
    完整 spec：[设计文档](../superpowers/specs/2026-04-26-watchlist-rules-design.md)
```

- [ ] **Step 2: Update mkdocs.yml nav**

In `mkdocs.yml`, change:
```yaml
- Rules Engine (v0.3.0 planned): components/rules.md
```
to:
```yaml
- Rules Engine: components/rules.md
```

- [ ] **Step 3: Verify mkdocs build**

```bash
uv run mkdocs build --strict
```
Expected: exit 0.

- [ ] **Step 4: Commit**

```bash
git add docs/components/rules.md mkdocs.yml
git commit -m "docs(v0.3.0): mark rules engine as live (no longer planned)"
```

---

### Task 24: CHANGELOG + tag v0.3.0

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Add v0.3.0 entry**

Append to top of `CHANGELOG.md` (after the current top-most entry):

```markdown
## v0.3.0 (2026-04-26)

### Added
- New `rules/` module: pluggable keyword-matching engine (Aho-Corasick default)
- `rules.enable` (default true) + `llm.enable` (default false) two-section watchlist
- Rules-only mode: zero LLM cost, < 1ms per article, deterministic matching
- `gray_zone_action`: configurable skip / digest / push for ambiguous cases
- Schema validators: at-least-one-enabled, ticker-unique, sector/macro ref validity
- `synth_enriched_from_rules()` — build EnrichedNews without LLM (body[:200] excerpt)
- `LLMPipeline.process_with_rules()` — skip Tier-0 when rules already classified
- `MessageBuilder.build_from_rules()` — push card with rules badges
- `DispatchRouter.route(markets=...)` — multi-market routing for shared news
- Migration script `scripts/migrate_watchlist_v0_3_0.py`

### Breaking
- `WatchlistFile` schema changed: top-level `us/cn/macro/sectors` → `rules` + `llm` sections
- Old watchlist.yml format rejected at startup; run migration script first

### Internal
- `ImportanceClassifier` accepts `verdict: RulesVerdict | None` and `gray_zone_action`
- `process_pending` accepts `rules_engine`, `rules_enabled`, `llm_enabled` kwargs
- `LLMPipeline.__init__` accepts `first_party_sources` set

### Performance
- Rules pipeline: ~350 patterns build in < 10ms, match in < 1ms per 1KB article
- Replaces LLM Tier-0 (1-2 seconds + DashScope cost) for the common case
```

- [ ] **Step 2: Tag**

```bash
git add CHANGELOG.md
git commit -m "docs(v0.3.0): CHANGELOG entry"
git tag -a v0.3.0 -m "Watchlist rules+llm dual-section architecture"
git log --oneline -3
git tag -l --sort=v:refname | tail -3
```

- [ ] **Step 3: Production deploy (optional)**

After all verification + tag, deploy via existing upgrade flow:

```bash
ssh root@8.135.67.243 'cd /opt/news_pipeline && git pull && \
  unset VIRTUAL_ENV && \
  /root/.local/bin/uv pip install --index-url https://pypi.tuna.tsinghua.edu.cn/simple --extra-index-url https://mirrors.aliyun.com/pypi/simple/ -e . && \
  systemctl restart news-pipeline'
```

But first the user must manually copy migrated watchlist.yml to the server (it has user-specific aliases / sectors).

---

## Self-Review

### Spec coverage check

| Spec section | Implementing tasks |
|---|---|
| §1.1 模块布局 (rules/) | Tasks 1, 2, 3, 4, 5, 6 |
| §1.2 4 种 enable 组合 | Task 19 (process_pending) + Task 21 (tests) |
| §2 Schema | Tasks 7, 8, 9, 11 |
| §3 Algorithm (Aho-Corasick + boundary) | Task 4 |
| §3.3 MatcherProtocol | Task 4 |
| §3.4 RulesEngine + score_boost | Task 6 |
| §4.1 RulesVerdict | Task 2 |
| §4.2 process_pending | Task 19 |
| §4.3 synth_enriched_from_rules | Task 14 |
| §4.4 process_with_rules | Task 15 |
| §4.5 ImportanceClassifier | Task 16 |
| §4.6 build_from_rules | Task 17 |
| §4.7 multi-market route | Task 18 |
| §6.4 Hot reload | Implicit in `RulesEngine.rebuild()` (Task 6) — covered by ConfigLoader watchdog already |
| §7 Migration | Tasks 12, 13 |
| §8 Testing | Tasks 4, 6, 9, 14, 15, 16, 17, 18, 21 |
| §10 ADR / risks | Documented in spec; runtime mitigations in code |

### Type consistency check

- `RulesVerdict` defined in Task 2 — used identically in Tasks 6, 14, 15, 16, 17, 19, 21 ✅
- `Pattern` / `PatternKind` defined in Task 3 — used in Tasks 4, 5 ✅
- `RulesSection` / `TickerEntry` / `MarketKeywords` defined in Task 7 — used in Tasks 5 (anticipated), 6, 9, 12, 20 ✅
- `RulesEngine` defined in Task 6 — used in Tasks 19 (process_pending param), 20 (main wiring) ✅
- `gray_zone_action: Literal["skip", "digest", "push"]` consistent: Task 7 (schema) → Task 16 (classifier) → Task 21 (tests) ✅
- `score_boost` formula: Task 6 (`_compute_boost`) → Task 16 (added to score) ✅

### Placeholder scan

No `TBD`, `TODO`, "fill in later", or `Similar to Task N` references. Each step has actual code. ✅

### Scope check

Single feature spanning 24 tasks. Phases:
- Phase 0 (1 task): dep
- Phase 1 (5 tasks): rules core
- Phase 2 (5 tasks): schema
- Phase 3 (2 tasks): migration
- Phase 4 (7 tasks): pipeline integration
- Phase 5 (1 task): comprehensive tests
- Phase 6 (3 tasks): verify + version + deploy

Total ~24 tasks, ~120 steps. Manageable for one plan.

### Known gaps

- **Hot-reload behavior on watchlist change** isn't explicitly tested. ConfigLoader's watchdog should trigger ConfigSnapshot reload, but the current main.py wires `RulesEngine` once at startup; auto-rebuild on change requires extra wiring to call `rules_engine.rebuild(new_snap.watchlist.rules)`. Documented in spec §6.4 but not in plan. **Add a future task in v0.3.x to wire this**, not blocking v0.3.0.
- **eval set updates** (gold_news.jsonl) — not in this plan; covered by separate eval workflow.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-26-watchlist-rules-impl.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
