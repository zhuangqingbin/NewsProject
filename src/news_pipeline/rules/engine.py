from typing import TYPE_CHECKING

from news_pipeline.common.enums import Market
from news_pipeline.config.schema import FirstPartyConfig, ScoringConfig
from news_pipeline.rules.aliases import remove_exclusions
from news_pipeline.rules.first_party import match_first_party
from news_pipeline.rules.headline import headline
from news_pipeline.rules.matcher import build_matcher
from news_pipeline.rules.patterns import Pattern, PatternKind
from news_pipeline.rules.scoring import contains, evaluate_subject, percentage_moves
from news_pipeline.rules.verdict import RulesVerdict

if TYPE_CHECKING:
    from news_pipeline.common.contracts import RawArticle
    from news_pipeline.config.schema import RulesSection
    from news_pipeline.rules.matcher import MatcherProtocol


def _compile(
    rules: "RulesSection",
) -> list[Pattern]:
    """Compile strong aliases and person mentions for candidate recall."""
    patterns: list[Pattern] = []

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
            for person in entry.people:
                patterns.append(
                    Pattern(
                        text=person.lower(),
                        is_english=person.isascii(),
                        kind=PatternKind.PERSON,
                        market=market,
                        owner=entry.ticker,
                    )
                )
    return patterns


class RulesEngine:
    """Recall candidates and provide a deterministic rule fallback for assessment."""

    def __init__(
        self,
        rules: "RulesSection",
        matcher: "MatcherProtocol | None" = None,
        *,
        scoring: ScoringConfig | None = None,
        first_party: FirstPartyConfig | None = None,
    ) -> None:
        self._matcher = matcher or build_matcher("aho_corasick", {})
        self._scoring = scoring or ScoringConfig()
        self._first_party = first_party or FirstPartyConfig()
        self.rebuild(rules)

    def rebuild(self, rules: "RulesSection") -> None:
        patterns = _compile(rules)
        self._matcher.rebuild(patterns)
        self._rules = rules
        self._ticker_markets = {
            entry.ticker: market for market in ("us", "cn") for entry in getattr(rules, market)
        }

    def match(self, art: "RawArticle") -> RulesVerdict:
        if art.source in ("juchao", "sec_edgar"):
            return match_first_party(art, self._first_party, self._ticker_markets)
        title = remove_exclusions(art.title, self._rules)
        body = remove_exclusions(art.body or "", self._rules)
        h = headline(title, body)
        text = f"{title}  {body}"
        strong_kinds = {PatternKind.TICKER, PatternKind.ALIAS}
        headline_matches = self._matcher.find_all(h)
        subjects = {
            match.pattern.owner for match in headline_matches if match.pattern.kind in strong_kinds
        }
        tagged = {
            match.pattern.owner
            for match in self._matcher.find_all(text)
            if match.pattern.kind in strong_kinds | {PatternKind.PERSON}
        }
        hint = self._importance_hint(art)
        roundup = len(percentage_moves(text)) >= 3 or any(
            contains(h, word) for word in self._scoring.roundup_words
        )
        keywords = []
        sectors, macros, generics = [], [], []
        groups = self._scoring.keywords
        for category in ("macro", "policy", "sector", "en"):
            for word in getattr(groups, category):
                word = word.lower()
                if contains(h, word):
                    keywords.append(word)
                    if category == "sector":
                        sectors.append(word)
                    elif category == "macro":
                        macros.append(word)
                    else:
                        generics.append(word)
        if subjects:
            positions = [
                match.start for match in headline_matches if match.pattern.kind in strong_kinds
            ]
            decision, reason, roundup = evaluate_subject(h, text, positions, self._scoring)
        elif tagged:
            decision, reason = "digest_lo", "mention"
        elif keywords:
            decision, reason = "digest_lo", f"keyword:{keywords[0]}"
        else:
            decision, reason = "drop", "no_match"
        market_tickers = subjects or tagged
        markets = (
            sorted({self._ticker_markets[ticker] for ticker in market_tickers})
            if market_tickers
            else [art.market.value]
        )
        return RulesVerdict(
            decision=decision,
            reason=reason,
            subject_tickers=sorted(subjects),
            tagged_tickers=sorted(tagged),
            markets=markets,
            keywords=list(dict.fromkeys(keywords)),
            is_roundup=roundup,
            importance_hint=hint,
            rank_score={"push": 90, "digest_hi": 60, "digest_lo": 30, "drop": 0}[decision]
            + hint * 10,
            sectors=sorted(set(sectors)),
            macros=sorted(set(macros)),
            generic_hits=sorted(set(generics)),
        )

    @staticmethod
    def _importance_hint(art: "RawArticle") -> int:
        if art.source == "cls_telegraph":
            return {"A": 3, "B": 2}.get(str(art.raw_meta.get("level", "")).upper(), 0)
        if art.source == "wallstreetcn":
            score = art.raw_meta.get("score", 0)
            return 3 if score == 3 else 2 if score == 2 else 0
        return 0
