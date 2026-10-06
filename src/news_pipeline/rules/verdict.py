from dataclasses import dataclass, field
from typing import Literal

RuleDecision = Literal["push", "digest_hi", "digest_lo", "drop"]


@dataclass(frozen=True, init=False)
class RulesVerdict:
    """Rule decision with transitional accessors for legacy and shadow consumers."""

    decision: RuleDecision
    reason: str
    subject_tickers: list[str] = field(default_factory=list)
    tagged_tickers: list[str] = field(default_factory=list)
    markets: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    is_roundup: bool = False
    importance_hint: int = 0
    rank_score: float = 0.0
    sectors: list[str] = field(default_factory=list)
    macros: list[str] = field(default_factory=list)
    generic_hits: list[str] = field(default_factory=list)
    score_boost: float = 0.0

    def __init__(
        self,
        matched: bool | None = None,
        tickers: list[str] | None = None,
        related_tickers: list[str] | None = None,
        sectors: list[str] | None = None,
        macros: list[str] | None = None,
        generic_hits: list[str] | None = None,
        markets: list[str] | None = None,
        score_boost: float | None = None,
        *,
        decision: RuleDecision | None = None,
        reason: str = "",
        subject_tickers: list[str] | None = None,
        tagged_tickers: list[str] | None = None,
        keywords: list[str] | None = None,
        is_roundup: bool = False,
        importance_hint: int = 0,
        rank_score: float = 0.0,
    ) -> None:
        decision = decision or ("digest_hi" if matched else "drop")
        subjects = list(subject_tickers if subject_tickers is not None else tickers or [])
        tagged = list(
            tagged_tickers
            if tagged_tickers is not None
            else sorted(set(subjects) | set(related_tickers or []))
        )
        values = {
            "decision": decision,
            "reason": reason,
            "subject_tickers": subjects,
            "tagged_tickers": tagged,
            "markets": list(markets or []),
            "keywords": list(keywords or []),
            "is_roundup": is_roundup,
            "importance_hint": importance_hint,
            "rank_score": rank_score,
            "sectors": list(sectors or []),
            "macros": list(macros or []),
            "generic_hits": list(generic_hits or []),
            "score_boost": (
                score_boost
                if score_boost is not None
                else {"push": 90.0, "digest_hi": 60.0, "digest_lo": 30.0, "drop": 0.0}[decision]
            ),
        }
        for key, value in values.items():
            object.__setattr__(self, key, value)

    @property
    def matched(self) -> bool:
        return self.decision != "drop"

    @property
    def tickers(self) -> list[str]:
        return self.subject_tickers

    @property
    def related_tickers(self) -> list[str]:
        return sorted(set(self.tagged_tickers) - set(self.subject_tickers))
