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
            "sec_edgar": SourceDef(enabled=True),
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
