"""MarketScanFeed: three sorted Eastmoney pages for top-N ranking."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import httpx

from quote_watcher.feeds.em_scan import fetch_clist_page, optional_number
from shared.observability.log import get_logger

log = get_logger(__name__)
_MARKET_FS = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048"
_FIELDS = "f12,f14,f2,f3,f5,f6,f10"


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
    source_id = "eastmoney_spot"

    def __init__(self, *, timeout_sec: float = 8.0) -> None:
        self._timeout = timeout_sec

    async def fetch(self) -> list[MarketRow]:
        """Fetch gainers, losers and volume leaders, deduplicated by ticker."""
        out: dict[str, MarketRow] = {}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                for fid, descending in (("f3", True), ("f3", False), ("f10", True)):
                    page = await fetch_clist_page(
                        client,
                        fs=_MARKET_FS,
                        fields=_FIELDS,
                        fid=fid,
                        descending=descending,
                    )
                    for row in page.rows:
                        mr = _row_to_market_row(
                            {
                                "代码": row["f12"],
                                "名称": row["f14"],
                                "最新价": row["f2"],
                                "涨跌幅": row["f3"],
                                "成交量": row["f5"],
                                "成交额": row["f6"],
                                "量比": optional_number(row["f10"]),
                            }
                        )
                        if mr is not None:
                            out.setdefault(mr.ticker, mr)
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("market_scan_fetch_failed", error=repr(exc))
            raise
        return list(out.values())
