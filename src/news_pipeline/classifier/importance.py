# src/news_pipeline/classifier/importance.py
from typing import Literal

from news_pipeline.classifier.llm_judge import LLMJudge
from news_pipeline.classifier.rules import RuleEngine
from news_pipeline.common.contracts import EnrichedNews, ScoredNews
from news_pipeline.rules.verdict import RulesVerdict


class ImportanceClassifier:
    def __init__(
        self,
        *,
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
                # llm_reason flag = drop signal (process_pending checks this prefix)
                is_crit = False
                gz_reason = "rules-only-grayzone-skip"
            else:  # digest
                is_crit = False
                gz_reason = "rules-only-grayzone-digest"
            return ScoredNews(
                enriched=e, score=score, is_critical=is_crit,
                rule_hits=rule_names, llm_reason=gz_reason,
            )

        # LLM-enabled gray zone: judge breaks the tie
        is_crit, reason = await self._judge.judge(e, watchlist_tickers=self._wl)
        return ScoredNews(
            enriched=e, score=score, is_critical=is_crit,
            rule_hits=rule_names, llm_reason=reason,
        )
