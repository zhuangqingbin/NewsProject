# tests/unit/scrapers/test_factory.py
from news_pipeline.config.schema import (
    RulesSection,
    SecretsFile,
    SourceDef,
    SourcesFile,
    TickerEntry,
    WatchlistFile,
)
from news_pipeline.scrapers.factory import build_registry


def test_factory_builds_registry_for_enabled_sources():
    sources = SourcesFile(
        sources={
            "finnhub": SourceDef(enabled=True),
            "sec_edgar": SourceDef(
                enabled=True, options={"user_agent": "NewsProject contact@example.org"}
            ),
            "xueqiu": SourceDef(enabled=False),
        }
    )
    watchlist = WatchlistFile(
        rules=RulesSection(
            us=[TickerEntry(ticker="NVDA", name="NVIDIA")],
            cn=[TickerEntry(ticker="600519", name="贵州茅台")],
        )
    )
    secrets = SecretsFile(
        sources={
            "finnhub_token": "T",
            "xueqiu_cookie": "C",
            "ths_cookie": "C",
            "tushare_token": "X",
        }
    )
    reg = build_registry(sources, watchlist, secrets, sec_ciks={"NVDA": "1045810"})
    ids = reg.list_ids()
    assert "finnhub" in ids and "sec_edgar" in ids and "xueqiu" not in ids


def test_factory_registers_repaired_source_ids_and_sec_without_cik_argument():
    sources = SourcesFile(
        sources={
            "sec_edgar": SourceDef(options={"user_agent": "NewsProject contact@example.org"}),
            "cls_telegraph": SourceDef(),
            "em_stock_news": SourceDef(),
        }
    )
    watchlist = WatchlistFile(
        rules=RulesSection(
            us=[TickerEntry(ticker="NVDA", name="NVIDIA")],
            cn=[TickerEntry(ticker="300308", name="中际旭创")],
        )
    )
    reg = build_registry(sources, watchlist, SecretsFile())
    assert set(reg.list_ids()) == {"sec_edgar", "cls_telegraph", "em_stock_news"}


def test_factory_reports_missing_sec_user_agent_configuration():
    import pytest

    sources = SourcesFile(sources={"sec_edgar": SourceDef()})
    watchlist = WatchlistFile(rules=RulesSection(us=[TickerEntry(ticker="NVDA", name="NVIDIA")]))
    with pytest.raises(ValueError, match=r"sec_edgar.*user_agent"):
        build_registry(sources, watchlist, SecretsFile())
