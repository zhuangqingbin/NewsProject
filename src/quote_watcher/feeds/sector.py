"""SectorFeed: akshare 板块 quote wrapper."""
from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass

import akshare as ak
import pandas as pd

from shared.observability.log import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class SectorSnapshot:
    name: str
    pct_change: float
    volume_ratio: float | None = None
    turnover_rate: float | None = None


def _row_to_snapshot(d: dict[str, object]) -> SectorSnapshot | None:
    name_raw = d.get("板块名称")
    if not name_raw or not str(name_raw).strip():
        return None
    pct = d.get("涨跌幅")
    if pct is None or (isinstance(pct, float) and math.isnan(pct)):
        return None
    turnover = d.get("换手率")
    if isinstance(turnover, float) and math.isnan(turnover):
        turnover = None
    try:
        return SectorSnapshot(
            name=str(name_raw).strip(),
            pct_change=float(pct),  # type: ignore[arg-type]
            turnover_rate=float(turnover) if turnover is not None else None,  # type: ignore[arg-type]
        )
    except (ValueError, TypeError):
        return None


class SectorFeed:
    source_id = "akshare_sector"

    async def fetch_pct_changes(self) -> dict[str, SectorSnapshot]:
        try:
            df: pd.DataFrame = await asyncio.to_thread(
                ak.stock_board_industry_name_em,
            )
        except Exception as e:
            log.warning("sector_fetch_failed", error=str(e))
            return {}
        out: dict[str, SectorSnapshot] = {}
        for _, row in df.iterrows():
            snap = _row_to_snapshot(row.to_dict())
            if snap is not None:
                out[snap.name] = snap
        return out
