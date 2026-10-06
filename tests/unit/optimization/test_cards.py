import json
from datetime import UTC, datetime

import pytest

from news_pipeline.storage.models import Event, RawNews
from shared.common.contracts import DigestItem
from shared.push.feishu import FeishuPusher

NOW = datetime(2026, 10, 6, 12, tzinfo=UTC)


def article(source="sina_global", *, body="正文", article_id=1):
    return RawNews(
        id=article_id,
        source=source,
        market="us",
        url=f"https://example.com/{article_id}",
        url_hash=str(article_id),
        title="英伟达回购",
        body=body,
        fetched_at=NOW,
        published_at=NOW,
    )


def event(**values):
    return Event(
        id=1,
        first_seen_at=NOW,
        last_seen_at=NOW,
        headline="【英伟达回购授权增加】评论",
        markets=["us"],
        subject_tickers=["NVDA"],
        **values,
    )


def card_size(msg):
    pusher = FeishuPusher(channel_id="test", webhook="https://example.com/", sign_secret="secret")
    card = pusher._build_card(msg)
    card.update(timestamp="1234567890", sign="x" * 44)
    return len(json.dumps(card, ensure_ascii=False).encode("utf-8"))


def test_event_card_prefers_first_party_and_rendered_so_what():
    from news_pipeline.deliver.cards import build_event_card

    ev = event(
        assess_status="done",
        summary="英伟达上调回购授权",
        so_what="每股价值获支持",
        event_type="buyback",
        materiality=4,
        source_count=3,
        first_party=True,
        holdings=[{"ticker": "NVDA", "direction": "positive", "relation": "subject"}],
    )
    msg = build_event_card(ev, [article(body="长" * 100), article("sec_edgar", article_id=2)])
    assert msg.title == ev.summary
    assert msg.summary == ev.so_what
    assert str(msg.source_url) == "https://example.com/2"
    texts = [badge.text for badge in msg.badges]
    assert "SEC" in texts
    assert "★★★★☆" in " ".join(texts)
    assert "3 家报道" in texts
    assert "NVDA" in texts
    assert "首发 20:00" in texts
    assert msg.badges[0].color == "green"
    assert any("NVDA" in str(link.url) for link in msg.deeplinks)
    rendered = FeishuPusher(channel_id="test", webhook="https://example.com/")._build_card(msg)
    assert "**每股价值获支持**" in rendered["card"]["elements"][0]["text"]["content"]


def test_rule_card_uses_headline_and_longest_origin():
    from news_pipeline.deliver.cards import build_event_card

    msg = build_event_card(
        event(assess_status="failed"), [article(), article(body="长" * 50, article_id=2)]
    )
    assert msg.title == "英伟达回购授权增加"
    assert "规则" in [badge.text for badge in msg.badges]
    assert str(msg.source_url) == "https://example.com/2"


@pytest.mark.parametrize(
    ("scheme", "direction", "color"),
    [
        ("us", "positive", "green"),
        ("us", "negative", "red"),
        ("cn", "positive", "red"),
        ("cn", "negative", "green"),
    ],
)
def test_card_direction_color_scheme(scheme, direction, color):
    from news_pipeline.deliver.cards import build_event_card

    msg = build_event_card(
        event(holdings=[{"ticker": "NVDA", "direction": direction}]),
        [article()],
        color_scheme=scheme,
    )
    assert msg.badges[0].color == color


def test_title_is_limited_to_sixty_characters():
    from news_pipeline.deliver.cards import build_event_card

    msg = build_event_card(event(assess_status="done", summary="长" * 120), [article()])
    assert len(msg.title) == 60


def test_trim_measures_rendered_utf8_with_signature_headroom():
    from news_pipeline.deliver.cards import build_event_card, trim_message

    msg = build_event_card(event(), [article()]).model_copy(update={"kind": "digest"})
    msg.digest_items = [
        DigestItem(source_label="来源" * 30, url=f"https://example.com/{n}", summary="汉字" * 1000)
        for n in range(20)
    ]
    assert card_size(msg) > 20_000
    trimmed = trim_message(msg)
    assert card_size(trimmed) <= 19_000
    assert 0 < len(trimmed.digest_items) < 20
    assert len(msg.digest_items) == 20


def test_multiple_cninfo_notices_render_as_one_card_with_original_links():
    from news_pipeline.deliver.cards import build_event_card

    notices = [
        article("juchao", article_id=n).model_copy(
            update={
                "title": f"宁德时代\uff1a回购公告{n}",
                "market": "cn",
            }
        )
        for n in range(1, 8)
    ]
    ev = event(first_party=True, rule_reason="tier:high").model_copy(
        update={
            "markets": ["cn"],
            "subject_tickers": ["300750"],
        }
    )
    msg = build_event_card(ev, notices)
    assert msg.title == "宁德时代 发布 5 份公告"
    assert len(msg.digest_items) == 5
    assert all(item.source_label == "公告" for item in msg.digest_items)
    assert [str(item.url) for item in msg.digest_items] == [
        f"https://example.com/{n}" for n in range(1, 6)
    ]


@pytest.mark.parametrize(
    "event_type",
    [
        "analyst_action",
        "capital_action",
        "contract_order",
        "regulatory_legal",
        "management_change",
        "product_tech",
        "macro_policy",
        "industry_trend",
        "insider_trade",
        "capacity",
        "market_color",
    ],
)
def test_all_assessment_types_have_specific_labels(event_type):
    from news_pipeline.deliver.cards import build_event_card

    msg = build_event_card(event(event_type=event_type), [article()])
    assert msg.badges[0].text != "其他"


def test_cross_market_card_quote_links_follow_each_ticker():
    from news_pipeline.deliver.cards import build_event_card

    ev = event().model_copy(update={"markets": ["us", "cn"], "subject_tickers": ["NVDA", "300750"]})
    links = {link.label: str(link.url) for link in build_event_card(ev, [article()]).deeplinks}
    assert links["行情 NVDA"] == "https://finance.yahoo.com/quote/NVDA"
    assert links["行情 300750"] == "https://quote.eastmoney.com/sz300750.html"


def test_byte_trimming_displays_omission_notice():
    from news_pipeline.deliver.cards import build_event_card, trim_message

    msg = build_event_card(event(), [article()])
    msg.digest_items = [
        DigestItem(source_label="原文", url=f"https://example.com/{n}", summary="汉字" * 1000)
        for n in range(20)
    ]
    trimmed = trim_message(msg)
    rendered = FeishuPusher(channel_id="test", webhook="https://example.com/")._build_card(trimmed)
    assert (
        f"另有 {20 - len(trimmed.digest_items)} 条未展示"
        in rendered["card"]["elements"][0]["text"]["content"]
    )
    assert card_size(trimmed) <= 19000
