"""Tencent's public stock and Shenwan second-level industry ranking contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

PAGE_SIZE = 100
MARKET_URL = "https://proxy.finance.qq.com/cgi/cgi-bin/rank/hs/getBoardRankList"
SECTOR_URL = "https://proxy.finance.qq.com/cgi/cgi-bin/rank/pt/getRank"


@dataclass(frozen=True)
class RankPage:
    total: int
    rows: list[dict[str, Any]]


async def fetch_rank_page(
    client: httpx.AsyncClient,
    *,
    sort: str = "priceRatio",
    descending: bool = True,
    offset: int = 0,
    sector: bool = False,
) -> RankPage:
    params: dict[str, str | int] = {
        "sort_type": sort,
        "direct": "down" if descending else "up",
        "offset": offset,
        "count": PAGE_SIZE,
    }
    if sector:
        params["board_type"] = "hy2"
    else:
        params.update({"_appver": "11.17.0", "board_code": "aStock"})
    response = await client.get(SECTOR_URL if sector else MARKET_URL, params=params)
    response.raise_for_status()
    payload = response.json()
    if (
        not isinstance(payload, dict)
        or type(payload.get("code")) is not int
        or payload["code"] != 0
    ):
        raise ValueError("Tencent ranking returned an invalid response or upstream error")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("Tencent ranking must contain a data object")
    total, rows = data.get("total"), data.get("rank_list")
    required = (
        {"code", "name", "zdf", "lb", "hsl"}
        if sector
        else {
            "code",
            "name",
            "zxj",
            "zdf",
            "lb",
            "volume",
            "turnover",
        }
    )
    if (
        type(total) is not int
        or total <= 0
        or not isinstance(rows, list)
        or len(rows) > PAGE_SIZE
        or any(not isinstance(row, dict) or not required.issubset(row) for row in rows)
        or len(rows) != min(PAGE_SIZE, max(total - offset, 0))
        or any(
            not isinstance(row["code"], str)
            or not isinstance(row["name"], str)
            or not row["name"].strip()
            for row in rows
        )
        or len({row["code"] for row in rows}) != len(rows)
    ):
        raise ValueError("Tencent ranking has invalid total or quote rows")
    return RankPage(total=total, rows=rows)
