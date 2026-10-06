# ruff: noqa: RUF001
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from news_pipeline.common.contracts import RawArticle
from news_pipeline.common.enums import Market
from news_pipeline.config.schema import FirstPartyConfig, ScoringConfig, WatchlistFile
from news_pipeline.events.similarity import features, same_event, within_event_window
from news_pipeline.rules.engine import RulesEngine
from news_pipeline.rules.headline import headline
from news_pipeline.rules.verdict import RulesVerdict

CONFIG = Path(__file__).parents[3] / "config" / "news_pipeline"
AT = datetime(2026, 10, 6, tzinfo=UTC)


def article(title: str, body: str = "", source: str = "wire", **meta: object) -> RawArticle:
    return RawArticle(
        source=source,
        market=Market.US,
        title=title,
        body=body,
        published_at=AT,
        fetched_at=AT,
        url="https://example.com/news",
        url_hash="hash",
        raw_meta=meta,
    )


@pytest.fixture
def engine() -> RulesEngine:
    watchlist = WatchlistFile.model_validate(yaml.safe_load((CONFIG / "watchlist.yml").read_text()))
    return RulesEngine(watchlist.rules)


@pytest.mark.parametrize(
    ("title", "body", "expected"),
    [
        (
            "截断标题",
            "【英伟达宣布回购1500亿美元】财联社10月6日电，正文",
            "英伟达宣布回购1500亿美元",
        ),
        ("【英伟达宣布回购】正文", "", "英伟达宣布回购"),
        ("英伟达发布", "英伟达发布新产品。后续正文", "英伟达发布新产品"),
        ("独立真标题", "别的正文", "独立真标题"),
        ("", "第一句正文；第二句正文", "第一句正文"),
    ],
)
def test_headline_shapes(title: str, body: str, expected: str) -> None:
    assert headline(title, body) == expected


@pytest.mark.parametrize(
    ("title", "decision", "reason", "subjects"),
    [
        ("英伟达：将股票回购授权规模增加1500亿美元", "push", "event:回购", ["NVDA"]),
        ("摩根大通下调特斯拉目标价至415美元", "push", "event:目标价", ["TSLA"]),
        ("Meta股价涨10.4%", "push", "big_move", ["META"]),
        ("惠誉首次给予特斯拉BBB评级", "push", "event:评级", ["TSLA"]),
        ("AMD 82亿美元收购World Labs", "push", "event:收购", ["AMD"]),
        ("港股医药股走强 药明巨诺涨9.77%", "drop", "no_match", []),
        ("博通集成涨停 安博通宣布回购", "drop", "no_match", []),
        ("其中芯片产能下降", "digest_lo", "keyword:芯片", []),
        ("黄仁勋谈新产品", "digest_lo", "mention", []),
        ("马斯克宣布SpaceX新发射计划", "digest_lo", "mention", []),
        ("NVDA推出新GPU", "digest_hi", "subject", ["NVDA"]),
        ("NVDAX回购", "drop", "no_match", []),
        ("英伟达签订新协议", "push", "lead:协议", ["NVDA"]),
        ("慧与拿下首份AMD Helios订单", "digest_hi", "subject", ["AMD"]),
        ("另一家公司拿下全球第一份AMD Helios订单", "digest_hi", "subject", ["AMD"]),
        ("英伟达投资100亿美元建厂", "push", "lead:建厂", ["NVDA"]),
        ("英伟达融资100亿美元", "push", "amount:融资", ["NVDA"]),
        ("英伟达投资新项目", "digest_hi", "subject", ["NVDA"]),
        ("英伟达融资买入额增加100亿元", "digest_hi", "roundup", ["NVDA"]),
        ("日本央行维持利率不变", "drop", "no_match", []),
        ("央行维持利率不变", "digest_lo", "keyword:re:(?<![一-龥])央行", []),
        ("美国国务院发言", "drop", "no_match", []),
    ],
)
def test_rules_v2_cases(
    engine: RulesEngine, title: str, decision: str, reason: str, subjects: list[str]
) -> None:
    verdict = engine.match(article(title))
    assert verdict.decision == decision
    assert verdict.reason == reason
    assert verdict.subject_tickers == subjects


def test_roundup_body_mentions_are_only_tags(engine: RulesEngine) -> None:
    verdict = engine.match(
        article("美股光通信股开盘普跌", "美股光通信股开盘普跌。博通涨0.07%，AMD跌1%，Meta跌2%")
    )
    assert verdict.decision == "digest_lo"
    assert verdict.reason == "mention"
    assert verdict.subject_tickers == []
    assert verdict.tagged_tickers == ["AMD", "AVGO", "META"]
    assert verdict.is_roundup is True


def test_subject_markets_take_precedence_over_body_tags(engine: RulesEngine) -> None:
    verdict = engine.match(article("英伟达发布新产品", "正文提及中际旭创"))
    assert verdict.markets == ["us"]
    assert verdict.tagged_tickers == ["300308", "NVDA"]


def test_keyword_only_uses_headline_and_does_not_expand_sector(engine: RulesEngine) -> None:
    assert engine.match(article("无关标题", "全文提到半导体行业")).decision == "drop"
    verdict = engine.match(article("半导体行业景气回升"))
    assert verdict.decision == "digest_lo"
    assert verdict.tagged_tickers == []
    assert verdict.related_tickers == []


@pytest.mark.parametrize(
    ("source", "title", "meta", "decision", "hint"),
    [
        ("juchao", "员工持股计划草案的法律意见书", {"code": "300750"}, "drop", 0),
        ("juchao", "关于员工持股计划草案", {"code": "300750"}, "push", 3),
        ("juchao", "董事会决议", {"code": "300750"}, "digest_hi", 1),
        (
            "sec_edgar",
            "8-K Current report",
            {"ticker": "TSLA", "form": "8-K", "items": "2.02,9.01"},
            "push",
            3,
        ),
        (
            "sec_edgar",
            "Current report",
            {"ticker": "NVDA", "form": "8-K", "items": "7.01,8.01"},
            "digest_hi",
            1,
        ),
        ("sec_edgar", "Annual report", {"ticker": "NVDA", "form": "10-K"}, "push", 3),
        ("sec_edgar", "Ownership", {"ticker": "NVDA", "form": "4"}, "drop", 0),
        (
            "sec_edgar",
            "Foreign issuer",
            {"ticker": "TSM", "form": "6-K", "primaryDocument": "tsm-revenue20260910.htm"},
            "push",
            3,
        ),
    ],
)
def test_first_party_tiers(
    engine: RulesEngine, source: str, title: str, meta: dict[str, object], decision: str, hint: int
) -> None:
    verdict = engine.match(article(title, source=source, **meta))
    assert verdict.decision == decision
    assert verdict.importance_hint == hint
    assert verdict.subject_tickers == [meta.get("code", meta.get("ticker"))]
    assert (
        verdict.reason == "tier:" + {"push": "high", "digest_hi": "normal", "drop": "low"}[decision]
    )


@pytest.mark.parametrize(
    ("source", "meta", "hint"),
    [
        ("cls_telegraph", {"level": "A"}, 3),
        ("cls_telegraph", {"level": "B"}, 2),
        ("wallstreetcn", {"score": 3}, 3),
        ("wallstreetcn", {"score": 2}, 2),
        ("wire", {}, 0),
    ],
)
def test_importance_hint_ranks_candidates(
    engine: RulesEngine, source: str, meta: dict[str, object], hint: int
) -> None:
    verdict = engine.match(article("半导体行业景气回升", source=source, **meta))
    assert verdict.importance_hint == hint
    assert verdict.rank_score == 30 + hint * 10


def test_verdict_v2_keeps_legacy_accessors() -> None:
    verdict = RulesVerdict(
        decision="push",
        reason="event:回购",
        subject_tickers=["NVDA"],
        tagged_tickers=["NVDA", "TSLA"],
    )
    assert verdict.matched is True
    assert verdict.tickers == ["NVDA"]
    assert verdict.related_tickers == ["TSLA"]


def test_optional_configs_have_initial_vocabulary() -> None:
    assert "回购" in ScoringConfig().strong_events
    assert "10-K" in FirstPartyConfig().sec.high.forms


@pytest.mark.parametrize(
    "other",
    [
        "英伟达宣布将股票回购授权规模提高1500亿美元",
        "英伟达将股票回购授权增加1500亿美元，使回购计划总额达到2350亿美元",
        "英伟达美股盘前拉升涨超1%，公司宣布将股票回购授权规模增加1500亿美元",
    ],
)
def test_similarity_merges_rewrites(other: str) -> None:
    first = features("英伟达：将股票回购授权规模增加1500亿美元", ["NVDA"], AT)
    assert same_event(first, features(other, ["NVDA"], AT))


@pytest.mark.parametrize(
    ("left", "right", "subjects"),
    [
        (
            "瑞银集团（UBS）对药明康德的多头持仓比例降至5.65%",
            "摩根大通（JPMorgan）对药明康德的多头持仓比例降至9.66%",
            ["603259"],
        ),
        (
            "TD Cowen将Meta目标股价从750美元上调至865美元",
            "德意志银行将META的目标价从750美元上调至820美元",
            ["META"],
        ),
    ],
)
def test_similarity_does_not_merge_different_numbers(
    left: str, right: str, subjects: list[str]
) -> None:
    assert not same_event(features(left, subjects, AT), features(right, subjects, AT))


def test_features_keep_decimal_percentage_numbers() -> None:
    f = features("市场消息：Meta（META.O）股价涨10.4%，目标价865美元", ["META"], AT)
    assert f.numbers == frozenset({"10.4%", "865美元"})
    assert "metao" not in f.norm


def test_similarity_does_not_merge_incompatible_subjects() -> None:
    assert not same_event(
        features("公司公告回购股票", ["NVDA"], AT), features("公司公告回购股票", ["TSLA"], AT)
    )


def test_event_window_checks_first_and_last_seen() -> None:
    assert within_event_window(AT, AT - timedelta(hours=12), AT - timedelta(hours=6))
    assert not within_event_window(AT, AT - timedelta(hours=12, seconds=1), AT)
    assert not within_event_window(AT, AT, AT - timedelta(hours=6, seconds=1))
