import json
from collections.abc import Iterable
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

EventType = Literal[
    "earnings",
    "guidance",
    "analyst_action",
    "m_and_a",
    "capital_action",
    "insider_trade",
    "contract_order",
    "product_tech",
    "capacity",
    "regulatory_legal",
    "management_change",
    "price_move",
    "macro_policy",
    "industry_trend",
    "market_color",
    "other",
]


class HoldingImpact(BaseModel):
    model_config = ConfigDict(extra="ignore")
    ticker: str
    relation: Literal["subject", "counterparty", "peer", "mention"]
    direction: Literal["positive", "negative", "neutral", "unclear"]


class EventAssessment(BaseModel):
    model_config = ConfigDict(extra="ignore")
    event_type: EventType
    scope: Literal["company", "sector", "market"]
    holdings: list[HoldingImpact] = Field(default_factory=list)
    materiality: Annotated[int, Field(strict=True, ge=1, le=5)]
    novelty: Literal["new", "update", "repeat"]
    same_as_event_id: Annotated[int, Field(strict=True, gt=0)] | None = None
    summary: Annotated[str, Field(min_length=4, max_length=120)]
    so_what: Annotated[str, Field(max_length=80)]
    confidence: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]


def parse_assessment(
    content: str, known_tickers: Iterable[str], recent_ids: Iterable[int]
) -> EventAssessment:
    assessment = EventAssessment.model_validate(json.loads(content))
    known = {ticker.upper(): ticker for ticker in known_tickers}
    sanitized = []
    for holding in assessment.holdings:
        ticker = known.get(holding.ticker.upper())
        if ticker is not None:
            sanitized.append(holding.model_copy(update={"ticker": ticker}))
    updates: dict[str, object] = {"holdings": sanitized, "summary": assessment.summary[:60]}
    if assessment.same_as_event_id not in set(recent_ids):
        updates["same_as_event_id"] = None
        if assessment.novelty == "repeat":
            updates["novelty"] = "new"
    return assessment.model_copy(update=updates)
