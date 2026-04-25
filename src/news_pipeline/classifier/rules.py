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

        # Rule: first-party source → always critical
        if source in self._cfg.sources_always_critical:
            hits.append(RuleHit("first_party_source", 30))

        # Rule: high magnitude + strong sentiment → critical
        if (
            self._cfg.sentiment_high_magnitude_critical
            and e.magnitude.value == "high"
            and e.sentiment.value in ("bullish", "bearish")
        ):
            hits.append(RuleHit("sentiment_high", 40))

        # Rule: notable event types
        if e.event_type.value in ("earnings", "m_and_a", "downgrade", "upgrade"):
            hits.append(RuleHit(f"event_{e.event_type.value}", 20))

        # Rule: regulatory filings
        if e.event_type.value == "filing":
            hits.append(RuleHit("filing", 25))

        return hits

    @staticmethod
    def score(hits: list[RuleHit]) -> int:
        return min(100, sum(h.weight for h in hits))
