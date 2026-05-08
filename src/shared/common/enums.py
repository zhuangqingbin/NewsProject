# src/shared/common/enums.py
"""Cross-subsystem enums shared by news_pipeline and quote_watcher."""
from __future__ import annotations

from enum import StrEnum


class Market(StrEnum):
    US = "us"
    CN = "cn"
