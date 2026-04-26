from typing import TYPE_CHECKING

from news_pipeline.common.enums import Market
from news_pipeline.rules.patterns import Pattern, PatternKind
from news_pipeline.rules.verdict import RulesVerdict

if TYPE_CHECKING:
    from news_pipeline.common.contracts import RawArticle
    from news_pipeline.config.schema import RulesSection
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
        for entry in getattr(rules, market_str):
            patterns.append(
                Pattern(
                    text=entry.ticker.lower(),
                    is_english=entry.ticker.isascii(),
                    kind=PatternKind.TICKER,
                    market=market,
                    owner=entry.ticker,
                )
            )
            patterns.append(
                Pattern(
                    text=entry.name.lower(),
                    is_english=entry.name.isascii(),
                    kind=PatternKind.ALIAS,
                    market=market,
                    owner=entry.ticker,
                )
            )
            for alias in entry.aliases:
                patterns.append(
                    Pattern(
                        text=alias.lower(),
                        is_english=alias.isascii(),
                        kind=PatternKind.ALIAS,
                        market=market,
                        owner=entry.ticker,
                    )
                )
            for sec in entry.sectors:
                sector_to_tickers.setdefault(sec.lower(), set()).add(entry.ticker)
            for mac in entry.macro_links:
                macro_to_tickers.setdefault(mac.lower(), set()).add(entry.ticker)

        for kw in getattr(rules.sector_keywords, market_str):
            patterns.append(
                Pattern(
                    text=kw.lower(),
                    is_english=kw.isascii(),
                    kind=PatternKind.SECTOR,
                    market=market,
                    owner=kw,
                )
            )
        for kw in getattr(rules.macro_keywords, market_str):
            patterns.append(
                Pattern(
                    text=kw.lower(),
                    is_english=kw.isascii(),
                    kind=PatternKind.MACRO,
                    market=market,
                    owner=kw,
                )
            )
        for kw in getattr(rules.keyword_list, market_str):
            patterns.append(
                Pattern(
                    text=kw.lower(),
                    is_english=kw.isascii(),
                    kind=PatternKind.GENERIC,
                    market=market,
                    owner=kw,
                )
            )

    return patterns, sector_to_tickers, macro_to_tickers


def _compute_boost(tickers: set[str], sectors: set[str], macros: set[str]) -> float:
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
        rules: "RulesSection",
        matcher: "MatcherProtocol",
    ) -> None:
        self._matcher = matcher
        self._sector_to_tickers: dict[str, set[str]] = {}
        self._macro_to_tickers: dict[str, set[str]] = {}
        self.rebuild(rules)

    def rebuild(self, rules: "RulesSection") -> None:
        patterns, sec_idx, mac_idx = _compile(rules)
        self._matcher.rebuild(patterns)
        self._sector_to_tickers = sec_idx
        self._macro_to_tickers = mac_idx

    def match(self, art: "RawArticle") -> RulesVerdict:
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
