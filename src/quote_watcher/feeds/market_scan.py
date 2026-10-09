"""MarketScanFeed: three sorted Eastmoney pages for top-N ranking."""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass
from typing import Any

import httpx

from quote_watcher.feeds.em_scan import fetch_clist_page, optional_number
from quote_watcher.feeds.tencent_rank import fetch_rank_page
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

    def __init__(self, *, timeout_sec: float = 8.0, provider: str | None = None) -> None:
        self._timeout = timeout_sec
        self.provider = (
            provider if provider is not None else os.getenv("MARKET_SCAN_FEED", "eastmoney")
        )
        if self.provider not in {"eastmoney", "tencent"}:
            raise ValueError("market scan provider must be eastmoney or tencent")
        self.source_id = "tencent_spot" if self.provider == "tencent" else "eastmoney_spot"
        self.source_label = "腾讯沪深京榜单" if self.provider == "tencent" else "东财沪深京榜单"
        self.source_url = (
            "https://stockapp.finance.qq.com/mstats/"
            if self.provider == "tencent"
            else "https://quote.eastmoney.com/center/gridlist.html"
        )
        self.total: int | None = None

    async def fetch(self) -> list[MarketRow]:
        """Fetch gainers, losers and volume leaders, deduplicated by ticker."""
        if self.provider == "tencent":
            return await self._fetch_tencent()
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
                    self.total = page.total
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

    async def _fetch_tencent(self) -> list[MarketRow]:
        out: dict[str, MarketRow] = {}
        self.total = None
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            for sort, descending in (
                ("priceRatio", True),
                ("priceRatio", False),
                ("volumeRatio", True),
            ):
                page = await fetch_rank_page(client, sort=sort, descending=descending)
                if self.total is not None and self.total != page.total:
                    raise ValueError("Tencent market total changed between rankings")
                self.total = page.total
                valid = 0
                for row in page.rows:
                    code = str(row["code"])
                    if (
                        not re.fullmatch(r"(?:sh|sz|bj)\d{6}", code)
                        or _infer_market(code[2:]) != code[:2].upper()
                    ):
                        raise ValueError("Tencent ranking has an invalid market/code")
                    price, pct, volume, amount = (
                        optional_number(row[k]) for k in ("zxj", "zdf", "volume", "turnover")
                    )
                    if price is None or pct is None or volume is None or amount is None:
                        continue
                    if price <= 0 or volume < 0 or amount < 0:
                        continue
                    if not math.isfinite(amount * 10_000):
                        raise ValueError("Tencent ranking amount is out of range")
                    valid += 1
                    out.setdefault(
                        code[2:],
                        MarketRow(
                            ticker=code[2:],
                            name=str(row["name"]),
                            market=code[:2].upper(),
                            price=price,
                            pct_change=pct,
                            volume=int(volume),
                            amount=amount * 10_000,
                            volume_ratio=optional_number(row["lb"]),
                        ),
                    )
                if page.rows and not valid:
                    raise ValueError("Tencent ranking contains no valid stock quotes")
        return list(out.values())
