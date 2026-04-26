from typing import Any, Protocol, runtime_checkable

import ahocorasick

from news_pipeline.rules.patterns import Match, Pattern


@runtime_checkable
class MatcherProtocol(Protocol):
    """Pluggable matcher interface. Implementations: AhoCorasickMatcher (default),
    future TfidfMatcher / EmbeddingMatcher / RegexMatcher / CompositeMatcher.
    """

    def rebuild(self, patterns: list[Pattern]) -> None:
        ...

    def find_all(self, text: str) -> list[Match]:
        ...


def _is_word_char(c: str) -> bool:
    """Word char = ASCII alphanumeric. CJK chars are treated as boundaries
    so 'FOMC加息' word-boundary-matches FOMC."""
    return c.isascii() and c.isalnum()


def _word_boundary_ok(text: str, start: int, end: int) -> bool:
    left_ok = (start == 0) or not _is_word_char(text[start - 1])
    right_ok = (end == len(text) - 1) or not _is_word_char(text[end + 1])
    return left_ok and right_ok


class AhoCorasickMatcher:
    """Default matcher: O(N+M) multi-pattern keyword search via pyahocorasick.

    English patterns post-filtered by word boundary; CJK patterns matched
    as substrings (no boundary, since '茅台' inside '贵州茅台' is correct).
    """

    def __init__(self) -> None:
        self._auto: ahocorasick.Automaton | None = None

    def rebuild(self, patterns: list[Pattern]) -> None:
        auto: ahocorasick.Automaton = ahocorasick.Automaton()
        grouped: dict[str, list[Pattern]] = {}
        for p in patterns:
            grouped.setdefault(p.text, []).append(p)
        for text, group in grouped.items():
            if text:
                auto.add_word(text, group)
        if patterns:
            auto.make_automaton()
        self._auto = auto

    def find_all(self, text: str) -> list[Match]:
        if self._auto is None:
            return []
        text_lc = text.lower()
        out: list[Match] = []
        try:
            iter_results = list(self._auto.iter(text_lc))
        except (AttributeError, ValueError):
            return []
        for end_idx, payloads in iter_results:
            for p in payloads:
                start_idx = end_idx - len(p.text) + 1
                if p.is_english and not _word_boundary_ok(text_lc, start_idx, end_idx):
                    continue
                out.append(Match(
                    pattern=p, start=start_idx, end=end_idx,
                    matched_text=text_lc[start_idx : end_idx + 1],
                ))
        return out


def build_matcher(name: str, options: dict[str, Any]) -> MatcherProtocol:
    if name == "aho_corasick":
        return AhoCorasickMatcher(**options)
    raise ValueError(f"unknown matcher: {name!r}")
