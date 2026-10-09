import httpx
import pytest
import respx

from quote_watcher.feeds.market_scan import MarketScanFeed
from quote_watcher.feeds.sector import SectorFeed

MARKET_URL = "https://proxy.finance.qq.com/cgi/cgi-bin/rank/hs/getBoardRankList"
SECTOR_URL = "https://proxy.finance.qq.com/cgi/cgi-bin/rank/pt/getRank"


def row(code="sh600519", name="贵州茅台", *, pct="0.57", ratio="1.18"):
    return {
        "code": code,
        "name": name,
        "zxj": "1263.00",
        "zdf": pct,
        "lb": ratio,
        "volume": "35111.00",
        "turnover": "445322",
        "hsl": "0.28",
    }


def response(rows, *, total=None):
    total = len(rows) if total is None else total
    return httpx.Response(200, json={"code": 0, "data": {"total": total, "rank_list": rows}})


@respx.mock
async def test_tencent_market_uses_three_rankings_and_preserves_market_units():
    quotes = [
        row("bj920157", pct="449.45", ratio="-"),
        row("sz300599", pct="-13.22"),
        row("sh600519"),
    ]
    route = respx.get(MARKET_URL).mock(
        side_effect=[
            response(quotes),
            response([quotes[1], quotes[2], quotes[0]]),
            response([quotes[2], quotes[1], quotes[0]]),
        ]
    )
    feed = MarketScanFeed(provider="tencent")
    rows = await feed.fetch()
    assert feed.source_id == "tencent_spot"
    assert len(rows) == 3
    assert [(r.ticker, r.market) for r in rows] == [
        ("920157", "BJ"),
        ("300599", "SZ"),
        ("600519", "SH"),
    ]
    assert rows[0].volume_ratio is None
    assert rows[-1].volume == 35111  # market rank contract remains lots
    assert rows[-1].amount == 4_453_220_000  # Tencent ranking turnover is 万元
    params = [c.request.url.params for c in route.calls]
    assert [(p["sort_type"], p["direct"]) for p in params] == [
        ("priceRatio", "down"),
        ("priceRatio", "up"),
        ("volumeRatio", "down"),
    ]
    assert all(
        p["board_code"] == "aStock" and p["count"] == "100" and p["offset"] == "0" for p in params
    )


@respx.mock
async def test_tencent_sector_paginates_shenwan_second_level_without_renaming():
    route = respx.get(SECTOR_URL).mock(
        side_effect=[
            response([row(f"pt{i:08d}", f"行业{i}") for i in range(100)], total=124),
            response([row(f"pt{i:08d}", f"行业{i}") for i in range(100, 124)], total=124),
        ]
    )
    feed = SectorFeed(provider="tencent")
    result = await feed.fetch_pct_changes()
    assert feed.source_id == "tencent_sector_sw2"
    assert len(result) == 124
    assert result["行业123"].pct_change == 0.57
    assert result["行业123"].volume_ratio == 1.18
    assert result["行业123"].turnover_rate == 0.28
    assert [c.request.url.params["offset"] for c in route.calls] == ["0", "100"]
    assert all(c.request.url.params["board_type"] == "hy2" for c in route.calls)


@respx.mock
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"code": 1, "data": {"total": 0, "rank_list": []}},
        {"code": 0, "data": None},
        {"code": 0, "data": {"total": "5573", "rank_list": []}},
        {"code": 0, "data": {"total": 1, "rank_list": []}},
        {"code": 0, "data": {"total": 1, "rank_list": [{}]}},
        {"code": 0, "data": {"total": 5573, "rank_list": [row()]}},
        {"code": 0, "data": {"total": 0, "rank_list": []}},
        {"code": 0, "data": {"total": 2, "rank_list": [row(), row()]}},
    ],
)
async def test_tencent_rank_rejects_upstream_errors_and_missing_pages(payload):
    respx.get(MARKET_URL).mock(return_value=httpx.Response(200, json=payload))
    with pytest.raises(ValueError):
        await MarketScanFeed(provider="tencent").fetch()


@respx.mock
async def test_tencent_market_raises_if_all_records_are_invalid():
    respx.get(MARKET_URL).mock(return_value=response([row(pct="inf")]))
    with pytest.raises(ValueError):
        await MarketScanFeed(provider="tencent").fetch()


@pytest.mark.parametrize("cls", [MarketScanFeed, SectorFeed])
def test_unknown_scan_provider_is_rejected(cls):
    with pytest.raises(ValueError, match="provider"):
        cls(provider="typo")


def test_scan_feeds_follow_the_explicit_deployment_environment(monkeypatch):
    monkeypatch.setenv("MARKET_SCAN_FEED", "tencent")
    monkeypatch.setenv("SECTOR_FEED", "tencent")
    assert MarketScanFeed().source_id == "tencent_spot"
    assert SectorFeed().source_id == "tencent_sector_sw2"


@respx.mock
async def test_market_rejects_code_market_mismatch():
    respx.get(MARKET_URL).mock(return_value=response([row("sh300750")]))
    with pytest.raises(ValueError):
        await MarketScanFeed(provider="tencent").fetch()


@respx.mock
async def test_industry_rejects_a_nonempty_but_truncated_collection():
    respx.get(SECTOR_URL).mock(return_value=response([row("pt123", "半导体")], total=3))
    with pytest.raises(ValueError):
        await SectorFeed(provider="tencent").fetch_pct_changes()
