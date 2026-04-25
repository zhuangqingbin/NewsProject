# src/news_pipeline/classifier/importance.py
from news_pipeline.classifier.llm_judge import LLMJudge
from news_pipeline.classifier.rules import RuleEngine
from news_pipeline.common.contracts import EnrichedNews, ScoredNews


class ImportanceClassifier:
    def __init__(
        self,
        *,
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

        # Above gray-zone ceiling → definitively critical, no LLM needed
        if score >= self._hi:
            return ScoredNews(
                enriched=e,
                score=score,
                is_critical=True,
                rule_hits=rule_names,
                llm_reason=None,
            )

        # Below gray-zone floor → definitively not critical, no LLM needed
        if score < self._lo:
            return ScoredNews(
                enriched=e,
                score=score,
                is_critical=False,
                rule_hits=rule_names,
                llm_reason=None,
            )

        # Gray zone [lo, hi) → LLM judge breaks the tie
        is_crit, reason = await self._judge.judge(e, watchlist_tickers=self._wl)
        return ScoredNews(
            enriched=e,
            score=score,
            is_critical=is_crit,
            rule_hits=rule_names,
            llm_reason=reason,
        )
