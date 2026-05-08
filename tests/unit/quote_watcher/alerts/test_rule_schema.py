import pytest
from pydantic import ValidationError

from quote_watcher.alerts.rule import AlertKind, AlertRule, AlertsFile


def test_threshold_minimal():
    r = AlertRule(
        id="t1", kind=AlertKind.THRESHOLD,
        ticker="600519", expr="pct_change_intraday <= -3.0",
    )
    assert r.cooldown_min == 30
    assert r.severity == "warning"


def test_threshold_requires_ticker():
    with pytest.raises(ValidationError, match="ticker"):
        AlertRule(id="t1", kind=AlertKind.THRESHOLD, expr="x > 0")


def test_indicator_requires_ticker():
    with pytest.raises(ValidationError, match="ticker"):
        AlertRule(id="i1", kind=AlertKind.INDICATOR, expr="rsi(14) < 25")


def test_event_sector_target():
    r = AlertRule(
        id="e1", kind=AlertKind.EVENT,
        target_kind="sector", sector="半导体",
        expr="sector_pct_change >= 3.0",
    )
    assert r.sector == "半导体"


def test_event_ticker_target_requires_ticker():
    with pytest.raises(ValidationError, match="ticker"):
        AlertRule(id="e2", kind=AlertKind.EVENT, target_kind="ticker", expr="is_limit_up")


def test_event_sector_target_requires_sector():
    with pytest.raises(ValidationError, match="sector"):
        AlertRule(id="e3", kind=AlertKind.EVENT, target_kind="sector", expr="x > 0")


def test_composite_requires_holding_or_portfolio():
    with pytest.raises(ValidationError, match=r"holding|portfolio"):
        AlertRule(id="c1", kind=AlertKind.COMPOSITE, expr="x > 0")


def test_composite_with_holding():
    r = AlertRule(
        id="c1", kind=AlertKind.COMPOSITE,
        holding="600519", expr="pct_change_from_cost <= -8",
    )
    assert r.holding == "600519"


def test_composite_with_portfolio():
    r = AlertRule(
        id="c2", kind=AlertKind.COMPOSITE,
        portfolio=True, expr="total_unrealized_pnl_pct <= -3",
    )
    assert r.portfolio is True


def test_alerts_file_unique_ids():
    with pytest.raises(ValidationError, match="duplicate"):
        AlertsFile(alerts=[
            AlertRule(id="dup", kind=AlertKind.THRESHOLD, ticker="A", expr="1"),
            AlertRule(id="dup", kind=AlertKind.THRESHOLD, ticker="B", expr="1"),
        ])


def test_alerts_file_invalid_expr_rejected():
    with pytest.raises(ValidationError, match="syntax"):
        AlertsFile(alerts=[
            AlertRule(id="bad", kind=AlertKind.THRESHOLD, ticker="A", expr="if if"),
        ])


def test_alerts_file_empty_ok():
    f = AlertsFile()
    assert f.alerts == []
