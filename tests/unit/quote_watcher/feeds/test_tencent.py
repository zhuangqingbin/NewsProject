"""Tencent fixtures recorded in the pipeline optimization design, appendix A.6."""

from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest
import respx

SAMPLE_SH = (
    'v_sh600519="1~贵州茅台~600519~1258.62~1235.58~1239.53~38331~21633~16698~'
    "1258.62~14~1258.44~1~1258.16~1~1258.05~2~1258.00~41~1258.65~2~1258.66~3~"
    "1258.68~1~1258.69~2~1258.75~80~~20260930161458~23.04~1.86~1268.00~1236.05~"
    "1258.62/38331/4797246636~38331~479725~0.31~19.32~~1268.00~1236.05~2.59~"
    '15733.78~15733.78~6.26~1359.14~1112.02~1.36~…";'
)
SAMPLE_SZ = (
    'v_sz300750="51~宁德时代~300750~291.11~286.80~290.00~296995~169839~127156~'
    "291.10~283~291.09~18~291.08~5~291.07~2~291.06~9~291.11~15~291.12~31~291.13~5~"
    "291.14~7~291.15~59~~20260930161418~4.31~1.50~292.70~285.80~"
    "291.11/296995/8613929784~296995~861393~0.70~15.85~~292.70~285.80~2.41~"
    '12403.08~13470.39~3.61~344.16~229.44~0.91~…";'
)
SAMPLE_STAR = (
    'v_sh688525="1~佰维存储~688525~192.35~198.60~200.00~13276166~6084549~7191617~'
    "192.35~139~192.34~16~192.33~58~192.32~43~192.31~358~192.36~293~192.38~5~"
    "192.39~13~192.40~12~192.41~3~~20260930161449~-6.25~-3.15~200.77~192.05~"
    "192.35/13276166/2582901089~13276166~258290~2.78~11.12~~200.77~192.05~4.39~"
    '917.19~917.19~7.29~238.32~158.88~0.69~…";'
)


def changed_field(sample: str, index: int, value: str) -> str:
    prefix, payload = sample.split('="', 1)
    fields = payload.removesuffix('";').split("~")
    fields[index] = value
    return prefix + '="' + "~".join(fields) + '";'


def test_parse_recorded_mainboard_sample():
    from quote_watcher.feeds.tencent import parse_tencent_response

    snap = parse_tencent_response(SAMPLE_SH)[0]
    assert snap.ticker == "600519"
    assert snap.market == "SH"
    assert snap.name == "贵州茅台"
    assert snap.price == 1258.62
    assert snap.prev_close == 1235.58
    assert snap.open == 1239.53
    assert snap.high == 1268.0
    assert snap.low == 1236.05
    assert snap.bid1 == 1258.62
    assert snap.ask1 == 1258.65
    assert snap.ts == datetime(2026, 9, 30, 16, 14, 58, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert snap.volume == 3_833_100
    assert snap.amount == 4_797_246_636
    assert snap.limit_up == 1359.14
    assert snap.limit_down == 1112.02
    assert snap.volume_ratio == 1.36


@pytest.mark.parametrize(
    ("sample", "volume", "amount", "ratio"),
    [(SAMPLE_SZ, 29_699_500, 8_613_929_784, 0.91), (SAMPLE_STAR, 13_276_166, 2_582_901_089, 0.69)],
)
def test_parse_chinext_and_star_volume_units(sample, volume, amount, ratio):
    from quote_watcher.feeds.tencent import parse_tencent_response

    snap = parse_tencent_response(sample)[0]
    assert snap.volume == volume
    assert snap.amount == amount
    assert snap.volume_ratio == ratio


def test_689_star_volume_is_already_shares():
    from quote_watcher.feeds.tencent import parse_tencent_response

    sample = SAMPLE_STAR.replace("688525", "689009")
    assert parse_tencent_response(sample)[0].volume == 13_276_166


@pytest.mark.parametrize(
    ("index", "value"),
    [(3, "-"), (3, "nan"), (6, "oops"), (30, "bad-date"), (35, "1/2"), (35, "1/2/inf")],
)
def test_parse_drops_malformed_required_fields(index, value):
    from quote_watcher.feeds.tencent import parse_tencent_response

    bad = changed_field(SAMPLE_SH, index, value)
    assert parse_tencent_response(bad + SAMPLE_SZ)[0].ticker == "300750"
    assert len(parse_tencent_response(bad + SAMPLE_SZ)) == 1


def test_parse_empty_and_short_payloads():
    from quote_watcher.feeds.tencent import parse_tencent_response

    assert parse_tencent_response('v_sh600519=""; v_sz300750="1~short";') == []


@pytest.mark.parametrize("value", ["", "-", "bad", "nan", "inf"])
def test_invalid_optional_fields_are_none(value):
    from quote_watcher.feeds.tencent import parse_tencent_response

    sample = SAMPLE_SH
    for index in (47, 48, 49):
        sample = changed_field(sample, index, value)
    snap = parse_tencent_response(sample)[0]
    assert snap.limit_up is None
    assert snap.limit_down is None
    assert snap.volume_ratio is None


def test_snapshot_optional_fields_remain_backwards_compatible():
    from quote_watcher.feeds.sina import parse_sina_response
    from tests.unit.quote_watcher.feeds.test_sina_parse import SAMPLE_SH as SINA_SAMPLE

    snap = parse_sina_response(SINA_SAMPLE)[0]
    assert snap.volume_ratio is None
    assert snap.limit_up is None
    assert snap.limit_down is None
    assert replace(snap, volume_ratio=0.0).volume_ratio == 0.0


@pytest.mark.asyncio
@respx.mock
async def test_fetch_builds_batch_url_and_decodes_gbk():
    from quote_watcher.feeds.tencent import TencentFeed

    route = respx.get("https://qt.gtimg.cn/q=sh600519,sz300750").mock(
        return_value=httpx.Response(200, content=(SAMPLE_SH + SAMPLE_SZ).encode("gbk"))
    )
    snaps = await TencentFeed().fetch([("SH", "600519"), ("SZ", "300750")])
    assert [snap.name for snap in snaps] == ["贵州茅台", "宁德时代"]
    assert route.calls[0].request.extensions["timeout"]["read"] == 8.0


@pytest.mark.asyncio
@respx.mock
async def test_fetch_empty_tickers_does_not_request():
    from quote_watcher.feeds.tencent import TencentFeed

    assert await TencentFeed().fetch([]) == []
    assert not respx.calls


@pytest.mark.asyncio
@respx.mock
async def test_fetch_retries_server_error():
    from quote_watcher.feeds.tencent import TencentFeed

    route = respx.get("https://qt.gtimg.cn/q=sh600519").mock(
        side_effect=[httpx.Response(503), httpx.Response(200, content=SAMPLE_SH.encode("gbk"))]
    )
    assert len(await TencentFeed().fetch([("SH", "600519")])) == 1
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_fetch_propagates_exhausted_http_failure():
    from quote_watcher.feeds.tencent import TencentFeed

    route = respx.get("https://qt.gtimg.cn/q=sh600519").mock(return_value=httpx.Response(503))
    with pytest.raises(httpx.HTTPStatusError):
        await TencentFeed(max_retries=1).fetch([("SH", "600519")])
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_fetch_rejects_unrecognizable_contract():
    from quote_watcher.feeds.tencent import TencentFeed

    respx.get("https://qt.gtimg.cn/q=sh600519").mock(
        return_value=httpx.Response(200, text="upstream maintenance")
    )
    with pytest.raises(ValueError):
        await TencentFeed().fetch([("SH", "600519")])
