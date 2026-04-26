from dataclasses import dataclass
from enum import StrEnum

from news_pipeline.common.enums import Market


class PatternKind(StrEnum):
    TICKER = "ticker"
    ALIAS = "alias"
    SECTOR = "sector"
    MACRO = "macro"
    GENERIC = "generic"


@dataclass(frozen=True)
class Pattern:
    """A single keyword pattern compiled from RulesSection config.

    `text` is always lowercase. `is_english` controls whether word boundary
    check applies during matching (English yes, CJK no).
    """
    text: str
    is_english: bool
    kind: PatternKind
    market: Market
    owner: str  # ticker code for TICKER/ALIAS; keyword self for SECTOR/MACRO/GENERIC


@dataclass(frozen=True)
class Match:
    """A successful match of a Pattern against an article text (lowercased)."""
    pattern: Pattern
    start: int
    end: int           # inclusive
    matched_text: str  # actual text from input (already lowercase)
