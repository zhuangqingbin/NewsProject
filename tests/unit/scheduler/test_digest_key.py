# tests/unit/scheduler/test_digest_key.py
"""Unit tests for _choose_digest_key (C4) — correct morning/evening selection."""
from datetime import UTC, datetime

import pytest

from news_pipeline.common.enums import Market
from news_pipeline.scheduler.jobs import _choose_digest_key


# ---------------------------------------------------------------------------
# US market (America/New_York, UTC-4 in summer / UTC-5 in winter)
# ---------------------------------------------------------------------------
# We freeze UTC times and verify the key against expected ET local hour.


@pytest.mark.parametrize(
    "utc_hour, utc_minute, expected_key",
    [
        # 10:00 UTC = 06:00 ET (summer, UTC-4) → morning
        (10, 0, "morning_us"),
        # 15:00 UTC = 11:00 ET → morning
        (15, 0, "morning_us"),
        # 15:59 UTC = 11:59 ET → morning
        (15, 59, "morning_us"),
        # 16:00 UTC = 12:00 ET → evening (noon boundary)
        (16, 0, "evening_us"),
        # 20:00 UTC = 16:00 ET → evening
        (20, 0, "evening_us"),
        # 23:00 UTC = 19:00 ET → evening
        (23, 0, "evening_us"),
        # 02:00 UTC next day = 22:00 ET → evening
        (2, 0, "evening_us"),
    ],
)
def test_choose_digest_key_us_summer(utc_hour: int, utc_minute: int, expected_key: str) -> None:
    # Use a summer date (UTC-4: America/New_York is EDT)
    now_utc = datetime(2026, 7, 1, utc_hour, utc_minute, 0, tzinfo=UTC)
    assert _choose_digest_key(Market.US, now_utc) == expected_key


# ---------------------------------------------------------------------------
# CN market (Asia/Shanghai, UTC+8, no DST)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "utc_hour, utc_minute, expected_key",
    [
        # 00:00 UTC = 08:00 CST → morning
        (0, 0, "morning_cn"),
        # 01:00 UTC = 09:00 CST → morning
        (1, 0, "morning_cn"),
        # 03:59 UTC = 11:59 CST → morning
        (3, 59, "morning_cn"),
        # 04:00 UTC = 12:00 CST → evening (noon boundary)
        (4, 0, "evening_cn"),
        # 08:00 UTC = 16:00 CST → evening
        (8, 0, "evening_cn"),
        # 14:00 UTC = 22:00 CST → evening
        (14, 0, "evening_cn"),
    ],
)
def test_choose_digest_key_cn(utc_hour: int, utc_minute: int, expected_key: str) -> None:
    now_utc = datetime(2026, 4, 25, utc_hour, utc_minute, 0, tzinfo=UTC)
    assert _choose_digest_key(Market.CN, now_utc) == expected_key


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_midnight_utc_is_morning_cn() -> None:
    """00:00 UTC = 08:00 CST — should be morning."""
    now_utc = datetime(2026, 4, 25, 0, 0, 0, tzinfo=UTC)
    assert _choose_digest_key(Market.CN, now_utc) == "morning_cn"


def test_noon_boundary_is_evening() -> None:
    """Exactly 12:00 local → evening (hour == 12 >= 12)."""
    # 04:00 UTC = 12:00 CST
    now_utc = datetime(2026, 4, 25, 4, 0, 0, tzinfo=UTC)
    assert _choose_digest_key(Market.CN, now_utc) == "evening_cn"
