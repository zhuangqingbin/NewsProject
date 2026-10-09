from datetime import date

import httpx
import pytest
import respx

from quote_watcher.feeds.tencent_daily import fetch_tencent_daily

URL = "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get"


def payload(code, volume):
    return {
        "code": 0,
        "data": {
            code: {
                "qfqday": [
                    [
                        "2026-09-30",
                        "200",
                        "192.35",
                        "200.77",
                        "192.05",
                        volume,
                        {},
                        "2.78",
                        "258290.11",
                        "",
                    ],
                    [
                        "2026-10-08",
                        "190.98",
                        "183.18",
                        "193.01",
                        "182.10",
                        volume,
                        {},
                        "3.46",
                        "307755.66",
                        "",
                    ],
                    ["2026-10-09", "180", "190", "200", "180", volume, {}, "1", "123", ""],
                ]
            }
        },
    }


@respx.mock
@pytest.mark.parametrize(
    ("ticker", "code", "volume", "lots"),
    [
        ("600519", "sh600519", "38331.00", 38331),
        ("300750", "sz300750", "296995.00", 296995),
        ("688525", "sh688525", "13276166.00", 132762),
    ],
)
async def test_tencent_daily_preserves_qfq_amount_and_completed_session(ticker, code, volume, lots):
    route = respx.get(URL).mock(return_value=httpx.Response(200, json=payload(code, volume)))
    result = await fetch_tencent_daily(
        ticker, start=date(2026, 9, 30), end=date(2026, 10, 8), days=2
    )
    rows = result.bars
    assert [r[0] for r in rows] == [date(2026, 9, 30), date(2026, 10, 8)]
    assert rows[-1] == (
        date(2026, 10, 8),
        190.98,
        193.01,
        182.1,
        183.18,
        192.35,
        lots,
        3_077_556_600,
    )
    assert result.volume_shares[date(2026, 10, 8)] == (
        int(float(volume)) if ticker.startswith("688") else int(float(volume) * 100)
    )
    assert route.calls[0].request.url.params["param"] == f"{code},day,2026-09-30,2026-10-08,3,qfq"


@respx.mock
@pytest.mark.parametrize(
    "bad",
    [
        {},
        {"code": 1},
        {"code": 0, "data": {}},
        {"code": 0, "data": {"sh600519": {"day": []}}},
        {"code": 0, "data": {"sh600519": {"qfqday": [["2026-10-08", "1", "2", "3", "0", "4"]]}}},
    ],
)
async def test_tencent_daily_rejects_missing_adjusted_history_or_amount(bad):
    respx.get(URL).mock(return_value=httpx.Response(200, json=bad))
    with pytest.raises(ValueError):
        await fetch_tencent_daily("600519", start=date(2026, 9, 30), end=date(2026, 10, 8), days=2)


@respx.mock
async def test_daily_fallback_persists_exact_star_shares(quote_db):
    from unittest.mock import patch

    from freezegun import freeze_time

    from quote_watcher.storage.dao.quote_bars import QuoteBarsDailyDAO
    from quote_watcher.store.kline import DailyKlineCache

    respx.get(URL).mock(return_value=httpx.Response(200, json=payload("sh688525", "16488424")))
    with (
        freeze_time("2026-10-09 02:00:00"),
        patch(
            "quote_watcher.store.kline.ak.stock_zh_a_hist",
            side_effect=RuntimeError("upstream disconnected"),
        ),
    ):
        cache = DailyKlineCache(quote_db)
        result = await cache.load_for(["688525"], days=2)
        assert result["688525"][-1].volume == 16_488_424
        assert (await cache.get_cached("688525"))[-1].volume == 16_488_424
        rows = await QuoteBarsDailyDAO(quote_db).list_recent("688525", 2)
        assert rows[-1].volume_shares == 16_488_424
        assert rows[-1].trade_date == date(2026, 10, 8)


@respx.mock
async def test_both_daily_sources_failing_hides_legacy_partial_bar(quote_db):
    from unittest.mock import patch

    from freezegun import freeze_time

    from quote_watcher.storage.dao.quote_bars import QuoteBarsDailyDAO
    from quote_watcher.store.kline import DailyKlineCache

    await QuoteBarsDailyDAO(quote_db).upsert_many(
        "600519", [(date(2026, 10, 8), 100, 102, 99, 101, 100, 10, 1e5)]
    )
    respx.get(URL).mock(return_value=httpx.Response(503))
    with (
        freeze_time("2026-10-09 02:00:00"),
        patch("quote_watcher.store.kline.ak.stock_zh_a_hist", side_effect=RuntimeError("net")),
    ):
        cache = DailyKlineCache(quote_db)
        assert await cache.load_for(["600519"], days=1) == {"600519": []}
        assert await cache.get_cached("600519") == []


@respx.mock
async def test_daily_rejects_amount_that_overflows_after_yuan_conversion():
    data = payload("sh600519", "100")
    data["data"]["sh600519"]["qfqday"][1][8] = "1e305"
    respx.get(URL).mock(return_value=httpx.Response(200, json=data))
    with pytest.raises(ValueError):
        await fetch_tencent_daily("600519", start=date(2026, 9, 30), end=date(2026, 10, 8), days=2)
