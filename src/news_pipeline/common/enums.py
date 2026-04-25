# src/news_pipeline/common/enums.py
from enum import StrEnum


class Market(StrEnum):
    US = "us"
    CN = "cn"


class Sentiment(StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class Magnitude(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class EventType(StrEnum):
    EARNINGS = "earnings"
    M_AND_A = "m_and_a"
    POLICY = "policy"
    PRICE_MOVE = "price_move"
    DOWNGRADE = "downgrade"
    UPGRADE = "upgrade"
    FILING = "filing"
    OTHER = "other"


class EntityType(StrEnum):
    COMPANY = "company"
    PERSON = "person"
    EVENT = "event"
    SECTOR = "sector"
    POLICY = "policy"
    PRODUCT = "product"


class Predicate(StrEnum):
    SUPPLIES = "supplies"
    COMPETES_WITH = "competes_with"
    OWNS = "owns"
    REGULATES = "regulates"
    PARTNERS_WITH = "partners_with"
    MENTIONS = "mentions"


# --- Lenient coercion helpers ---
# LLMs ignore enum constraints in prompts ~5-10% of the time, returning values
# like "market_analysis" or "neutral_to_positive" that don't match our enums.
# These helpers fall back to a safe default rather than crashing the pipeline.


def safe_event_type(value: str | None) -> EventType:
    if value is None:
        return EventType.OTHER
    try:
        return EventType(value.lower())
    except (ValueError, AttributeError):
        return EventType.OTHER


def safe_sentiment(value: str | None) -> Sentiment:
    if value is None:
        return Sentiment.NEUTRAL
    try:
        return Sentiment(value.lower())
    except (ValueError, AttributeError):
        return Sentiment.NEUTRAL


def safe_magnitude(value: str | None) -> Magnitude:
    if value is None:
        return Magnitude.LOW
    try:
        return Magnitude(value.lower())
    except (ValueError, AttributeError):
        return Magnitude.LOW


def safe_predicate(value: str | None) -> Predicate:
    if value is None:
        return Predicate.MENTIONS
    try:
        return Predicate(value.lower())
    except (ValueError, AttributeError):
        return Predicate.MENTIONS


def safe_entity_type(value: str | None) -> EntityType:
    if value is None:
        return EntityType.COMPANY
    try:
        return EntityType(value.lower())
    except (ValueError, AttributeError):
        return EntityType.COMPANY


def safe_market(value: str | None) -> Market | None:
    if value is None:
        return None
    try:
        return Market(value.lower())
    except (ValueError, AttributeError):
        return None
