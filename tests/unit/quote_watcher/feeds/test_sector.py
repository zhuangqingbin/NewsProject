import httpx
import pytest
import respx

from quote_watcher.feeds.sector import SectorFeed, _row_to_snapshot

URL = "https://push2.eastmoney.com/api/qt/clist/get"


def sector_row(name="半导体", *, pct=3.5, turnover=5.2, ratio=1.36):
    return {"f14": name, "f3": pct, "f8": turnover, "f10": ratio}


@pytest.mark.asyncio
@respx.mock
async def test_fetch_pct_changes_normal():
    route = respx.get(URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "total": 3,
                    "diff": [
                        sector_row(),
                        sector_row("新能源", pct=-1.8),
                        sector_row("白酒", pct=0.5),
                    ],
                }
            },
        )
    )
    out = await SectorFeed().fetch_pct_changes()
    assert out["半导体"].pct_change == 3.5
    assert out["半导体"].turnover_rate == 5.2
    assert out["半导体"].volume_ratio == 1.36
    assert out["新能源"].pct_change == -1.8
    params = route.calls[0].request.url.params
    assert params["fs"] == "m:90+t:2+f:!50"
    assert params["fields"] == "f14,f3,f8,f10"
    assert params["pz"] == "100"
    assert route.calls[0].request.extensions["timeout"]["read"] == 8.0


@pytest.mark.asyncio
@respx.mock
async def test_fetch_paginates_by_total():
    route = respx.get(URL).mock(
        side_effect=[
            httpx.Response(
                200,
                json={"data": {"total": 201, "diff": [sector_row(f"板块{i}") for i in range(100)]}},
            ),
            httpx.Response(
                200,
                json={
                    "data": {
                        "total": 201,
                        "diff": [sector_row(f"板块{i}") for i in range(100, 200)],
                    }
                },
            ),
            httpx.Response(200, json={"data": {"total": 201, "diff": [sector_row("末页")]}}),
        ]
    )
    out = await SectorFeed().fetch_pct_changes()
    assert len(out) == 201
    assert "末页" in out
    assert [call.request.url.params["pn"] for call in route.calls] == ["1", "2", "3"]


@pytest.mark.asyncio
@respx.mock
async def test_fetch_pct_changes_drops_invalid_rows():
    respx.get(URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "total": 3,
                    "diff": [sector_row("OK"), sector_row(""), sector_row("halted", pct="-")],
                }
            },
        )
    )
    out = await SectorFeed().fetch_pct_changes()
    assert list(out) == ["OK"]


@pytest.mark.asyncio
@respx.mock
async def test_fetch_propagates_http_failure():
    respx.get(URL).mock(return_value=httpx.Response(503))
    with pytest.raises(httpx.HTTPStatusError):
        await SectorFeed().fetch_pct_changes()


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"data": None},
        {"data": {}},
        {"data": {"total": 1, "diff": {}}},
        {"data": {"total": -1, "diff": []}},
        {"data": {"total": 1, "diff": ["bad"]}},
    ],
)
async def test_fetch_rejects_invalid_response_contract(payload):
    respx.get(URL).mock(return_value=httpx.Response(200, json=payload))
    with pytest.raises(ValueError):
        await SectorFeed().fetch_pct_changes()


@pytest.mark.asyncio
@respx.mock
async def test_fetch_accepts_empty_sector_list():
    route = respx.get(URL).mock(
        return_value=httpx.Response(200, json={"data": {"total": 0, "diff": []}})
    )
    assert await SectorFeed().fetch_pct_changes() == {}
    assert route.call_count == 1


def test_row_converter_preserves_existing_akshare_columns():
    snap = _row_to_snapshot({"板块名称": "半导体", "涨跌幅": 3.5, "换手率": 5.2})
    assert snap is not None
    assert snap.name == "半导体"
    assert snap.pct_change == 3.5
    assert snap.turnover_rate == 5.2


@pytest.mark.parametrize(
    "row",
    [
        {"板块名称": "", "涨跌幅": 1.0},
        {"板块名称": "NaN涨跌幅", "涨跌幅": float("nan")},
        {"foo": "bar", "baz": 1.0},
    ],
)
def test_row_converter_drops_invalid_rows(row):
    assert _row_to_snapshot(row) is None
