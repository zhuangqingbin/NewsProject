import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

_CODE = re.compile(r"[\(\uff08][a-z0-9\.\-]{2,12}[\)\uff09]")
_LEAD = re.compile(r"^(?:市场消息|据报道|报道|消息称|据悉|快讯|突发)[:\uff1a\uff0c,\s]*")
_STRIP = re.compile(r"[\s\W_]+")
_NUM = re.compile(r"\d+(?:\.\d+)?(?:%|亿|万|倍|美元|元)")


@dataclass(frozen=True)
class Features:
    norm: str
    bigrams: frozenset[str]
    numbers: frozenset[str]
    subjects: frozenset[str]
    at: datetime


def features(headline: str, subjects: Iterable[str], at: datetime) -> Features:
    text = _LEAD.sub("", _CODE.sub("", headline.lower()))
    # Extract before punctuation normalization, which removes decimal points and %.
    numbers = frozenset(_NUM.findall(text))
    norm = _STRIP.sub("", text)
    return Features(
        norm,
        frozenset(norm[i : i + 2] for i in range(len(norm) - 1)),
        numbers,
        frozenset(subjects),
        at,
    )


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    return len(a & b) / len(a | b) if a or b else 0.0


def _containment(a: frozenset[str], b: frozenset[str]) -> float:
    return len(a & b) / min(len(a), len(b)) if a and b else 0.0


def same_event(a: Features, b: Features) -> bool:
    if a.subjects and b.subjects and a.subjects != b.subjects:
        return False
    similarity = _jaccard(a.bigrams, b.bigrams)
    if a.numbers and b.numbers and not a.numbers & b.numbers:
        return similarity >= 0.9
    if similarity >= 0.6:
        return True
    if a.subjects and a.subjects == b.subjects:
        small, big = sorted((a.numbers, b.numbers), key=len)
        if similarity >= 0.3 and small and small <= big:
            return True
        if min(len(a.norm), len(b.norm)) >= 8 and _containment(a.bigrams, b.bigrams) >= 0.85:
            return True
    return False


def within_event_window(at: datetime, first_seen_at: datetime, last_seen_at: datetime) -> bool:
    """Accept out-of-order evidence as long as the resulting event span stays open."""
    return abs(at - last_seen_at) <= timedelta(hours=6) and abs(at - first_seen_at) <= timedelta(
        hours=12
    )
