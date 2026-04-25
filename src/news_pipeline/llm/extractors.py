# src/news_pipeline/llm/extractors.py
from dataclasses import dataclass

from news_pipeline.common.contracts import EnrichedNews, Entity, RawArticle, Relation
from news_pipeline.common.enums import (
    safe_entity_type,
    safe_event_type,
    safe_magnitude,
    safe_market,
    safe_predicate,
    safe_sentiment,
)
from news_pipeline.common.exceptions import LLMError
from news_pipeline.common.timeutil import utc_now
from news_pipeline.llm.clients.base import LLMClient, LLMRequest
from news_pipeline.llm.cost_tracker import CostTracker
from news_pipeline.llm.prompts.loader import PromptHandle

# ---------------------------------------------------------------------------
# Tier-0: Title classifier
# ---------------------------------------------------------------------------


@dataclass
class Tier0Verdict:
    relevant: bool
    tier_hint: str  # "tier1" | "tier2"
    watchlist_hit: bool
    reason: str


class Tier0Classifier:
    def __init__(
        self,
        *,
        client: LLMClient,
        prompt: PromptHandle,
        cost: CostTracker,
        model_override: str | None = None,
    ) -> None:
        self._client = client
        self._prompt = prompt
        self._cost = cost
        self._model_override = model_override

    async def classify(
        self,
        art: RawArticle,
        *,
        watchlist_us: list[str],
        watchlist_cn: list[str],
    ) -> Tier0Verdict:
        rendered = self._prompt.render(
            title=art.title,
            source=art.source,
            tickers=",".join(art.raw_meta.get("tickers", []) or []),  # type: ignore[arg-type]
            watchlist=",".join(watchlist_us + watchlist_cn),
        )
        req = LLMRequest(
            model=self._model_override or rendered.model_target,
            system=rendered.system,
            user=rendered.user,
            json_mode=True,
            output_schema=rendered.output_schema,
            max_tokens=200,
        )
        resp = await self._client.call(req)
        self._cost.record(model=resp.model, usage=resp.usage)
        payload = resp.json_payload
        if payload is None:
            raise LLMError("tier0 invalid json")
        return Tier0Verdict(
            relevant=bool(payload.get("relevant", False)),
            tier_hint=str(payload.get("tier_hint", "tier1")),
            watchlist_hit=bool(payload.get("watchlist_hit", False)),
            reason=str(payload.get("reason", "")),
        )


# ---------------------------------------------------------------------------
# Tier-1: Summarizer
# ---------------------------------------------------------------------------


class Tier1Summarizer:
    def __init__(
        self,
        *,
        client: LLMClient,
        prompt: PromptHandle,
        cost: CostTracker,
        model_override: str | None = None,
    ) -> None:
        self._client = client
        self._prompt = prompt
        self._cost = cost
        self._model_override = model_override

    async def summarize(self, art: RawArticle, *, raw_id: int) -> EnrichedNews:
        rendered = self._prompt.render(
            source=art.source,
            published_at=art.published_at.isoformat(),
            title=art.title,
            body=art.body or "",
        )
        req = LLMRequest(
            model=self._model_override or rendered.model_target,
            system=rendered.system,
            user=rendered.user,
            json_mode=True,
            output_schema=rendered.output_schema,
            cache_segments=rendered.cache_segments,
            few_shot_examples=rendered.few_shot_examples,
            max_tokens=600,
        )
        resp = await self._client.call(req)
        self._cost.record(model=resp.model, usage=resp.usage)
        payload = resp.json_payload
        if payload is None:
            raise LLMError("tier1 invalid json")
        return EnrichedNews(
            raw_id=raw_id,
            summary=payload["summary"],
            related_tickers=payload.get("related_tickers", []),
            sectors=payload.get("sectors", []),
            event_type=safe_event_type(payload.get("event_type")),
            sentiment=safe_sentiment(payload.get("sentiment")),
            magnitude=safe_magnitude(payload.get("magnitude")),
            confidence=float(payload.get("confidence", 0.5)),
            key_quotes=payload.get("key_quotes", []),
            entities=[],
            relations=[],
            model_used=rendered.model_target,
            extracted_at=utc_now().replace(tzinfo=None),
        )


# ---------------------------------------------------------------------------
# Tier-2: Deep extractor (entities + relations)
# ---------------------------------------------------------------------------


class Tier2DeepExtractor:
    def __init__(
        self,
        *,
        client: LLMClient,
        prompt: PromptHandle,
        cost: CostTracker,
        model_override: str | None = None,
    ) -> None:
        self._client = client
        self._prompt = prompt
        self._cost = cost
        self._model_override = model_override

    async def extract(
        self,
        art: RawArticle,
        *,
        raw_id: int,
        recent_context: str = "",
    ) -> EnrichedNews:
        rendered = self._prompt.render(
            source=art.source,
            published_at=art.published_at.isoformat(),
            title=art.title,
            body=art.body or "",
            recent_context=recent_context,
        )
        req = LLMRequest(
            model=self._model_override or rendered.model_target,
            system=rendered.system,
            user=rendered.user,
            json_mode=True,
            output_schema=rendered.output_schema,
            cache_segments=rendered.cache_segments,
            few_shot_examples=rendered.few_shot_examples,
            max_tokens=1200,
        )
        resp = await self._client.call(req)
        self._cost.record(model=resp.model, usage=resp.usage)
        payload = resp.json_payload
        if payload is None:
            raise LLMError("tier2 invalid json")

        ents_by_name: dict[str, Entity] = {
            e["name"]: Entity(
                type=safe_entity_type(e.get("type")),
                name=e["name"],
                ticker=e.get("ticker"),
                market=safe_market(e.get("market")),
                aliases=e.get("aliases", []),
            )
            for e in payload.get("entities", [])
            if e.get("name")
        }

        relations: list[Relation] = []
        for r in payload.get("relations", []):
            sub = ents_by_name.get(r.get("subject_name", ""))
            obj = ents_by_name.get(r.get("object_name", ""))
            if sub is None or obj is None:
                continue
            relations.append(
                Relation(
                    subject=sub,
                    predicate=safe_predicate(r.get("predicate")),
                    object=obj,
                    confidence=float(r.get("confidence", 0.5)),
                )
            )

        return EnrichedNews(
            raw_id=raw_id,
            summary=payload.get("summary", ""),
            related_tickers=payload.get("related_tickers", []),
            sectors=payload.get("sectors", []),
            event_type=safe_event_type(payload.get("event_type")),
            sentiment=safe_sentiment(payload.get("sentiment")),
            magnitude=safe_magnitude(payload.get("magnitude")),
            confidence=float(payload.get("confidence", 0.5)),
            key_quotes=payload.get("key_quotes", []),
            entities=list(ents_by_name.values()),
            relations=relations,
            model_used=rendered.model_target,
            extracted_at=utc_now().replace(tzinfo=None),
        )
