"""SectorFeed: paginated Eastmoney industry quotes."""

from __future__ import annotations

import math
from dataclasses import dataclass

import httpx

from quote_watcher.feeds.em_scan import PAGE_SIZE, fetch_clist_page, optional_number
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

    def __init__(self, *, timeout_sec: float = 8.0) -> None:
        self._timeout = timeout_sec

    async def fetch_pct_changes(self) -> dict[str, SectorSnapshot]:
        out: dict[str, SectorSnapshot] = {}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                first = await fetch_clist_page(client, fs=_SECTOR_FS, fields=_FIELDS)
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
