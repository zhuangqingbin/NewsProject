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
