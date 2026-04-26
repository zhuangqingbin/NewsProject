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
