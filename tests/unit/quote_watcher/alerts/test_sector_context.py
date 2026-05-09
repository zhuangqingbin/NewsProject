from quote_watcher.alerts.context import build_sector_context
from quote_watcher.feeds.sector import SectorSnapshot


def test_basic_sector_ctx():
    snap = SectorSnapshot(
        name="半导体", pct_change=3.5, turnover_rate=5.2,
    )
    ctx = build_sector_context("半导体", snap)
    assert ctx["sector_pct_change"] == 3.5
    assert ctx["sector_turnover_rate"] == 5.2
    assert ctx["sector_volume_ratio"] == 0.0


def test_sector_ctx_none_volume_ratio():
    snap = SectorSnapshot(
        name="新能源", pct_change=-2.0, volume_ratio=None,
    )
    ctx = build_sector_context("新能源", snap)
    assert ctx["sector_volume_ratio"] == 0.0
    assert ctx["sector_pct_change"] == -2.0


def test_sector_ctx_with_volume_ratio():
    snap = SectorSnapshot(
        name="半导体", pct_change=4.0, volume_ratio=1.8, turnover_rate=6.0,
    )
    ctx = build_sector_context("半导体", snap)
    assert ctx["sector_volume_ratio"] == 1.8
