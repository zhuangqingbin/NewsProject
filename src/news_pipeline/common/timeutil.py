# src/news_pipeline/common/timeutil.py
"""Re-export shim. Prefer `from shared.common.timeutil import ...` in new code (R4)."""
from shared.common.timeutil import (
    ensure_utc,
    is_market_hours,
    to_market_local,
    utc_now,
)

__all__ = ["ensure_utc", "is_market_hours", "to_market_local", "utc_now"]
