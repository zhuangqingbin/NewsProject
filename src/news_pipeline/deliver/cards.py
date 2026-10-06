"""Event cards and a byte limit measured against the actual Feishu renderer."""

import json
from collections.abc import Sequence
from datetime import UTC
from zoneinfo import ZoneInfo

from news_pipeline.rules.headline import headline
from news_pipeline.storage.models import Event, RawNews
from shared.common.contracts import Badge, CommonMessage, Deeplink, DigestItem
from shared.common.enums import Market
from shared.push.feishu import FeishuPusher

_FIRST_PARTY = {"juchao", "sec_edgar"}
_EVENT_TYPES = {
    "analyst_action": "评级调整",
    "capital_action": "资本动作",
    "insider_trade": "内部人交易",
    "contract_order": "合同订单",
    "product_tech": "产品技术",
    "capacity": "产能",
    "regulatory_legal": "监管诉讼",
    "management_change": "管理层变动",
    "macro_policy": "宏观政策",
    "industry_trend": "行业趋势",
    "market_color": "市场动态",
    "earnings": "业绩",
    "guidance": "业绩指引",
    "buyback": "回购",
    "dividend": "分红",
    "m_and_a": "并购",
    "contract": "重大合同",
    "financing": "融资",
    "litigation": "诉讼",
    "regulatory": "监管",
    "management": "管理层",
    "rating": "评级",
    "policy": "政策",
    "macro": "宏观",
    "product": "产品",
    "filing": "公告",
    "other": "其他",
    "upgrade": "评级上调",
    "downgrade": "评级下调",
    "price_move": "行情",
}
_RENDERER = FeishuPusher(channel_id="size-check", webhook="https://example.com/")


def primary_article(articles: Sequence[RawNews]) -> RawNews:
    if not articles:
        raise ValueError("An event card requires a source article")
    return max(
        articles,
        key=lambda article: (
            article.source in _FIRST_PARTY or bool((article.raw_meta or {}).get("first_party")),
            len(article.body or ""),
        ),
    )


def _rendered_bytes(msg: CommonMessage) -> int:
    body = _RENDERER._build_card(msg)
    body.update(timestamp="9999999999", sign="x" * 44)
    return len(json.dumps(body, ensure_ascii=False).encode("utf-8"))


def trim_message(msg: CommonMessage, max_bytes: int = 19000) -> CommonMessage:
    trimmed = msg.model_copy(deep=True)
    while _rendered_bytes(trimmed) > max_bytes:
        if len(trimmed.digest_items) > 1:
            trimmed.digest_items.pop()
            trimmed.omitted_count += 1
        elif trimmed.digest_items and len(trimmed.digest_items[0].summary) > 20:
            item = trimmed.digest_items[0]
            item.summary = item.summary[: max(20, len(item.summary) // 2)]
        elif len(trimmed.summary) > 20:
            trimmed.summary = trimmed.summary[: max(20, len(trimmed.summary) // 2)]
        elif trimmed.deeplinks:
            trimmed.deeplinks.pop()
        elif trimmed.badges:
            trimmed.badges.pop()
        elif len(trimmed.title) > 20:
            trimmed.title = trimmed.title[: max(20, len(trimmed.title) // 2)]
        else:
            raise ValueError("Message metadata exceeds the configured byte limit")
    return trimmed


def build_event_card(
    ev: Event,
    articles: Sequence[RawNews],
    *,
    color_scheme: str = "us",
) -> CommonMessage:
    origin = primary_article(articles)
    market = Market(ev.markets[0] if ev.markets else origin.market)
    notices = list(
        {article.url: article for article in articles if article.source == "juchao"}.values()
    )
    if ev.first_party and ev.rule_reason == "tier:high" and len(notices) > 1:
        notices = notices[:5]
        company = notices[0].title.split("\uff1a", 1)[0].split(":", 1)[0]
        if company == notices[0].title:
            company = ev.subject_tickers[0] if ev.subject_tickers else "公司"
        return trim_message(
            CommonMessage(
                title=f"{company} 发布 {len(notices)} 份公告",
                summary="",
                source_label="公告",
                source_url=origin.url,
                badges=[Badge(text="公告", color="blue")],
                chart_url=None,
                deeplinks=[],
                market=market,
                digest_items=[
                    DigestItem(
                        source_label="公告", url=notice.url, summary=headline(notice.title)[:60]
                    )
                    for notice in notices
                ],
            )
        )
    directions = {holding.get("direction") for holding in ev.holdings or []}
    direction = next(iter(directions)) if len(directions) == 1 else "neutral"
    positive, negative = ("green", "red") if color_scheme == "us" else ("red", "green")
    color = positive if direction == "positive" else negative if direction == "negative" else "gray"
    materiality = max(1, min(5, ev.materiality or 1))
    badges = [Badge(text=_EVENT_TYPES.get(ev.event_type or "other", "其他"), color=color)]
    if ev.assess_status != "done":
        badges.append(Badge(text="规则"))
    if ev.first_party:
        badges.append(Badge(text="SEC" if origin.source == "sec_edgar" else "公告"))
    badges.extend(
        [
            Badge(text="实质性 " + "★" * materiality + "☆" * (5 - materiality)),
            Badge(text=f"{ev.source_count} 家报道"),
            Badge(
                text="首发 "
                + (
                    ev.first_seen_at
                    if ev.first_seen_at.tzinfo
                    else ev.first_seen_at.replace(tzinfo=UTC)
                )
                .astimezone(ZoneInfo("Asia/Shanghai"))
                .strftime("%H:%M")
            ),
        ]
    )
    tickers = list(
        dict.fromkeys(
            [*ev.subject_tickers, *(h["ticker"] for h in ev.holdings or [] if h.get("ticker"))]
        )
    )
    badges.extend(Badge(text=ticker, color="blue") for ticker in tickers[:5])
    links = [Deeplink(label="原文", url=origin.url)]
    for ticker in tickers[:3]:
        if not (ticker.isascii() and ticker.isdigit() and len(ticker) == 6):
            url = f"https://finance.yahoo.com/quote/{ticker}"
        else:
            prefix = (
                "sh"
                if ticker.startswith(("6", "9"))
                else "bj"
                if ticker.startswith(("8", "4"))
                else "sz"
            )
            url = f"https://quote.eastmoney.com/{prefix}{ticker}.html"
        links.append(Deeplink(label=f"行情 {ticker}", url=url))
    return trim_message(
        CommonMessage(
            title=(
                ev.summary if ev.assess_status == "done" and ev.summary else headline(ev.headline)
            )[:60],
            summary=(ev.so_what or "")[:80],
            source_label=origin.source,
            source_url=origin.url,
            badges=badges,
            chart_url=None,
            deeplinks=links,
            market=market,
        )
    )
