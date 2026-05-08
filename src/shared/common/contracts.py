# src/shared/common/contracts.py
"""Push-layer data contracts shared between news_pipeline and quote_watcher."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from shared.common.enums import Market


class _Base(BaseModel):
    model_config = ConfigDict(use_enum_values=False, extra="forbid")


class Badge(_Base):
    text: str
    color: str = "gray"  # gray|green|red|yellow|blue


class Deeplink(_Base):
    label: str
    url: HttpUrl


class DigestItem(_Base):
    """One bullet inside a digest message — a clickable source label + summary."""

    source_label: str
    url: HttpUrl
    summary: str


class CommonMessage(_Base):
    title: str
    summary: str
    source_label: str
    source_url: HttpUrl
    badges: list[Badge]
    chart_url: HttpUrl | None  # deprecated: prefer chart_image
    # PNG bytes for inline embedding (TG sendPhoto / Feishu img_key)
    chart_image: bytes | None = None
    deeplinks: list[Deeplink]
    market: Market
    # Non-empty for digest messages: each item rendered as `[label](url) summary`.
    digest_items: list[DigestItem] = Field(default_factory=list)
    kind: Literal["news", "alert", "alert_burst", "market_scan", "digest"] = "news"
