from datetime import datetime
from zoneinfo import ZoneInfo

from quote_watcher.alerts.rule import AlertKind, AlertRule
from quote_watcher.alerts.verdict import AlertVerdict
from quote_watcher.emit.message import build_alert_message, build_burst_message
from quote_watcher.feeds.base import QuoteSnapshot

BJ = ZoneInfo("Asia/Shanghai")


def _v(rule_id: str, expr: str, ctx: dict) -> AlertVerdict:
    rule = AlertRule(id=rule_id, kind=AlertKind.THRESHOLD, ticker="600519", expr=expr)
    snap = QuoteSnapshot(
        ticker="600519", market="SH", name="贵州茅台",
        ts=datetime(2026, 5, 8, 14, 30, 25, tzinfo=BJ),
        price=1789.5, open=1820, high=1825, low=1788, prev_close=1845.36,
        volume=2823100, amount=5.04e9, bid1=1789.5, ask1=1789.51,
    )
    return AlertVerdict(rule=rule, snapshot=snap, ctx_dump=ctx)


def test_single_alert_message_drop():
    v = _v(
        "maotai_drop_3pct", "pct_change_intraday <= -3.0",
        {"price_now": 1789.5, "pct_change_intraday": -3.03, "volume_ratio": 2.1},
    )
    msg = build_alert_message(v)
    assert msg.kind == "alert"
    assert "贵州茅台" in msg.title
    assert "600519" in msg.title
    assert any(b.text == "alert" for b in msg.badges)
    assert any("600519" in b.text for b in msg.badges)
    assert "1789.5" in msg.summary
    # Down arrow for negative pct
    assert msg.title.startswith("🔻") or "🔻" in msg.title


def test_single_alert_message_up():
    v = _v(
        "x_jump", "pct_change_intraday >= 3.0",
        {"price_now": 1900, "pct_change_intraday": 3.0},
    )
    snap = v.snapshot
    # patch snap to be positive — easiest: re-create
    new_snap = QuoteSnapshot(
        ticker=snap.ticker, market=snap.market, name=snap.name,
        ts=snap.ts, price=1900, open=1850, high=1900, low=1850, prev_close=1845.36,
        volume=snap.volume, amount=snap.amount, bid1=1900, ask1=1900.01,
    )
    v = AlertVerdict(rule=v.rule, snapshot=new_snap, ctx_dump=v.ctx_dump)
    msg = build_alert_message(v)
    assert msg.kind == "alert"
    # Up arrow
    assert "🚀" in msg.title or msg.title.startswith("🚀")


def test_burst_merge_combines_verdicts():
    v1 = _v("a", "x<-1", {"price_now": 1789.5})
    v2 = _v("b", "y>2", {"price_now": 1789.5})
    msg = build_burst_message([v1, v2])
    assert msg.kind == "alert_burst"
    assert "多规则触发" in msg.title or "(2)" in msg.title or "x2" in msg.title
    assert "a" in msg.summary
    assert "b" in msg.summary


def test_burst_message_empty_raises():
    import pytest
    with pytest.raises(AssertionError):
        build_burst_message([])


def test_alert_message_includes_deeplinks():
    v = _v("r1", "x", {"price_now": 1789.5})
    msg = build_alert_message(v)
    assert any("eastmoney" in str(d.url) for d in msg.deeplinks)
    assert any("xueqiu" in str(d.url) for d in msg.deeplinks)
