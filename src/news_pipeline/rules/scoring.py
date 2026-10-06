import re
from collections.abc import Iterable
from typing import Literal

from news_pipeline.config.schema import ScoringConfig

RuleDecision = Literal["push", "digest_hi", "digest_lo", "drop"]
_PERCENT = re.compile(r"[涨跌](?:幅|超|逾|近|约|达|了|至|幅达|幅扩大至)*\s*(\d+(?:\.\d+)?)\s*%")
_AMOUNT = re.compile(r"\d+(?:\.\d+)?\s*(?:亿|万|美元|美金|元)")
_OBJECT_ACTION = re.compile(r"拿下|获得|签下|采购")


def contains(text: str, word: str) -> bool:
    if word.startswith("re:"):
        return re.search(word[3:], text, re.IGNORECASE) is not None
    if word.isascii():
        return (
            re.search(r"(?<![a-z0-9_])" + re.escape(word) + r"(?![a-z0-9_])", text, re.IGNORECASE)
            is not None
        )
    return word in text


def first_hit(text: str, words: Iterable[str]) -> str | None:
    return next((word for word in words if contains(text, word.lower())), None)


def percentage_moves(text: str) -> list[float]:
    return [float(match) for match in _PERCENT.findall(text)]


def evaluate_subject(
    headline: str, text: str, subject_positions: Iterable[int], scoring: ScoringConfig
) -> tuple[RuleDecision, str, bool]:
    moves = percentage_moves(text)
    roundup = len(moves) >= 3 or first_hit(headline, scoring.roundup_words) is not None
    if len(moves) <= 2 and any(move >= scoring.big_move_pct for move in percentage_moves(headline)):
        return "push", "big_move", roundup
    if not roundup:
        if word := first_hit(headline, scoring.strong_events):
            return "push", f"event:{word}", False
        # The explicit AMD Helios counterexample is a mention after another company's
        # action. Position alone does not establish it as the actor for weaker events.
        lead = any(
            position < scoring.lead_window_chars and not _OBJECT_ACTION.search(headline[:position])
            for position in subject_positions
        )
        if lead:
            if word := first_hit(headline, scoring.lead_events):
                return "push", f"lead:{word}", False
            if (word := first_hit(headline, scoring.amount_events)) and _AMOUNT.search(headline):
                return "push", f"amount:{word}", False
    return "digest_hi", "roundup" if roundup else "subject", roundup
