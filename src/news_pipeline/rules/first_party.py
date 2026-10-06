import re
from typing import Literal

from news_pipeline.common.contracts import RawArticle
from news_pipeline.config.schema import FirstPartyConfig
from news_pipeline.rules.verdict import RulesVerdict

Tier = Literal["high", "normal", "low"]


def first_party_tier(article: RawArticle, config: FirstPartyConfig) -> Tier:
    if article.source == "juchao":
        if any(re.search(pattern, article.title) for pattern in config.juchao.low):
            return "low"
        if any(re.search(pattern, article.title) for pattern in config.juchao.high):
            return "high"
        return "normal"
    form = str(article.raw_meta.get("form", "")).upper().strip()
    if form in {value.upper() for value in config.sec.low.forms}:
        return "low"
    if form in {value.upper() for value in config.sec.high.forms}:
        return "high"
    raw_items = article.raw_meta.get("items", "")
    items = (
        {str(item).strip() for item in raw_items}
        if isinstance(raw_items, list)
        else {item.strip() for item in str(raw_items).split(",")}
    )
    if form == "8-K" and items & set(config.sec.high.items_8k):
        return "high"
    # Source implementations may include the filename explicitly or only in the URL.
    filename = str(
        article.raw_meta.get(
            "primaryDocument",
            article.raw_meta.get(
                "primary_document", article.raw_meta.get("doc_name", article.url.path or "")
            ),
        )
    ).lower()
    if form == "6-K" and any(value.lower() in filename for value in config.sec.high.doc_name_6k):
        return "high"
    return "normal"


def match_first_party(
    article: RawArticle, config: FirstPartyConfig, ticker_markets: dict[str, str]
) -> RulesVerdict:
    tier = first_party_tier(article, config)
    key = "code" if article.source == "juchao" else "ticker"
    ticker = str(article.raw_meta.get(key) or "").strip().upper()
    subjects = [ticker] if ticker else []
    hint = {"high": 3, "normal": 1, "low": 0}[tier]
    decision: Literal["push", "digest_hi", "drop"] = {
        "high": "push",
        "normal": "digest_hi",
        "low": "drop",
    }[tier]  # type: ignore[assignment]
    return RulesVerdict(
        decision=decision,
        reason=f"tier:{tier}",
        subject_tickers=subjects,
        tagged_tickers=subjects,
        markets=[ticker_markets.get(ticker, article.market.value)],
        importance_hint=hint,
        rank_score={"push": 90, "digest_hi": 60, "drop": 0}[decision] + hint * 10,
    )
