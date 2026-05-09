"""MarketScanFeed: akshare 全市场 spot wrapper for top-N ranking."""
from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from typing import Any

import akshare as ak
import pandas as pd

from shared.observability.log import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class MarketRow:
    ticker: str
    name: str
    market: str  # SH | SZ | BJ
    price: float
    pct_change: float
    volume: int
    amount: float
    volume_ratio: float | None


def _infer_market(code: str) -> str:
    """Sina-style ticker prefix → market."""
    if code.startswith(("60", "68")):
        return "SH"
    if code.startswith(("00", "30")):
        return "SZ"
    if code.startswith(("8", "4", "9")):
        return "BJ"
    return "SH"  # safe default


def _row_to_market_row(d: dict[str, Any]) -> MarketRow | None:
    code = str(d.get("代码", "")).strip()
    if not code or len(code) != 6:
        return None
    price = d.get("最新价")
    if price is None or (isinstance(price, float) and math.isnan(price)):
        return None
    pct = d.get("涨跌幅")
    if pct is None or (isinstance(pct, float) and math.isnan(pct)):
        return None
    vol_ratio = d.get("量比")
    if isinstance(vol_ratio, float) and math.isnan(vol_ratio):
        vol_ratio = None
    try:
        return MarketRow(
            ticker=code,
            name=str(d.get("名称", "")),
            market=_infer_market(code),
            price=float(price),
            pct_change=float(pct),
            volume=int(d.get("成交量", 0) or 0),
            amount=float(d.get("成交额", 0.0) or 0.0),
            volume_ratio=float(vol_ratio) if vol_ratio is not None else None,
        )
    except (ValueError, TypeError):
        return None


class MarketScanFeed:
    source_id = "akshare_spot"

    async def fetch(self) -> list[MarketRow]:
        """Fetch entire A-share spot snapshot. Returns [] on any error."""
        try:
            df: pd.DataFrame = await asyncio.to_thread(ak.stock_zh_a_spot_em)
        except Exception as e:  # akshare can raise anything
            log.warning("market_scan_fetch_failed", error=str(e))
            return []
        out: list[MarketRow] = []
        for _, row in df.iterrows():
            mr = _row_to_market_row(row.to_dict())
            if mr is not None:
                out.append(mr)
        return out
