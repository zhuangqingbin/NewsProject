"""Shared contract for direct Eastmoney list requests."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import httpx

CLIST_URL = "https://push2.eastmoney.com/api/qt/clist/get"
PAGE_SIZE = 100


@dataclass(frozen=True)
class ClistPage:
    total: int
    rows: list[dict[str, Any]]


def optional_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (ValueError, TypeError):
        return None
    return number if math.isfinite(number) else None


async def fetch_clist_page(
    client: httpx.AsyncClient,
    *,
    fs: str,
    fields: str,
    page: int = 1,
    fid: str = "f3",
    descending: bool = True,
) -> ClistPage:
    response = await client.get(
        CLIST_URL,
        params={
            "pn": page,
            "pz": PAGE_SIZE,
            "np": 1,
            "fltt": 2,
            "invt": 2,
            "fs": fs,
            "fields": fields,
            "fid": fid,
            "po": int(descending),
        },
        follow_redirects=True,
    )
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise ValueError("Eastmoney response must contain a data object")
    total = data.get("total")
    rows = data.get("diff")
    required_fields = set(fields.split(","))
    if (
        type(total) is not int
        or total < 0
        or not isinstance(rows, list)
        or any(not isinstance(row, dict) or not required_fields.issubset(row) for row in rows)
    ):
        raise ValueError("Eastmoney response has invalid total or quote rows")
    if total > (page - 1) * PAGE_SIZE and not rows:
        raise ValueError("Eastmoney response is missing an expected page")
    return ClistPage(total=total, rows=rows)
