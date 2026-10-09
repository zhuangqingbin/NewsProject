"""SectorFeed: paginated Eastmoney industry quotes."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass

import httpx

from quote_watcher.feeds.em_scan import PAGE_SIZE, fetch_clist_page, optional_number
from quote_watcher.feeds.tencent_rank import fetch_rank_page
from shared.observability.log import get_logger

log = get_logger(__name__)
_SECTOR_FS = "m:90+t:2+f:!50"
_FIELDS = "f14,f3,f8,f10"


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
            volume_ratio=optional_number(d.get("量比")),
        )
    except (ValueError, TypeError):
        return None


class SectorFeed:
    source_id = "eastmoney_sector"

    def __init__(self, *, timeout_sec: float = 8.0, provider: str | None = None) -> None:
        self._timeout = timeout_sec
        self.provider = provider if provider is not None else os.getenv("SECTOR_FEED", "eastmoney")
        if self.provider not in {"eastmoney", "tencent"}:
            raise ValueError("sector provider must be eastmoney or tencent")
        self.source_id = "tencent_sector_sw2" if self.provider == "tencent" else "eastmoney_sector"
        self.source_label = "腾讯申万二级行业" if self.provider == "tencent" else "东财行业板块"
        self.source_url = (
            "https://stockapp.finance.qq.com/mstats/#mod=list&id=hy_second"
            if self.provider == "tencent"
            else "https://quote.eastmoney.com/center/gridlist.html#industry_board"
        )
        self.total: int | None = None

    async def fetch_pct_changes(self) -> dict[str, SectorSnapshot]:
        if self.provider == "tencent":
            return await self._fetch_tencent()
        out: dict[str, SectorSnapshot] = {}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                first = await fetch_clist_page(client, fs=_SECTOR_FS, fields=_FIELDS)
                self.total = first.total
                rows = list(first.rows)
                for page in range(2, (first.total + PAGE_SIZE - 1) // PAGE_SIZE + 1):
                    result = await fetch_clist_page(
                        client,
                        fs=_SECTOR_FS,
                        fields=_FIELDS,
                        page=page,
                    )
                    rows.extend(result.rows)
                for row in rows:
                    snap = _row_to_snapshot(
                        {
                            "板块名称": row["f14"],
                            "涨跌幅": row["f3"],
                            "换手率": optional_number(row["f8"]),
                            "量比": optional_number(row["f10"]),
                        }
                    )
                    if snap is not None:
                        out[snap.name] = snap
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("sector_fetch_failed", error=repr(exc))
            raise
        return out

    async def _fetch_tencent(self) -> dict[str, SectorSnapshot]:
        out: dict[str, SectorSnapshot] = {}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            first = await fetch_rank_page(client, sector=True)
            self.total = first.total
            rows = list(first.rows)
            for offset in range(PAGE_SIZE, first.total, PAGE_SIZE):
                page = await fetch_rank_page(client, sector=True, offset=offset)
                if page.total != first.total:
                    raise ValueError("Tencent industry total changed while paginating")
                rows.extend(page.rows)
            for row in rows:
                pct = optional_number(row["zdf"])
                name = str(row["name"]).strip()
                if not name or pct is None:
                    raise ValueError("Tencent industry contains an invalid name or percentage")
                if name in out:
                    raise ValueError("Tencent industry contains duplicate names")
                out[name] = SectorSnapshot(
                    name=name,
                    pct_change=pct,
                    volume_ratio=optional_number(row["lb"]),
                    turnover_rate=optional_number(row["hsl"]),
                )
            if len(out) != first.total:
                raise ValueError("Tencent industry is missing expected rows")
        return out
