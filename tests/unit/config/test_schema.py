# tests/unit/config/test_schema.py
import pytest
from pydantic import ValidationError

from news_pipeline.config.schema import (
    AppConfig,
)


def test_app_config_minimal():
    raw = {
        "runtime": {"daily_cost_ceiling_cny": 5.0, "hot_reload": True},
        "scheduler": {
            "scrape": {
                "market_hours_interval_sec": 180,
                "off_hours_interval_sec": 1800,
                "caixin_interval_sec": 60,
            },
            "llm": {"process_interval_sec": 120},
            "digest": {
                "morning_cn": "08:30",
                "evening_cn": "21:00",
                "morning_us": "21:00",
                "evening_us": "04:30",
            },
        },
        "llm": {
            "tier0_model": "deepseek-v3",
            "tier1_model": "deepseek-v3",
            "tier2_model": "claude-haiku-4-5-20251001",
            "tier3_model": "claude-sonnet-4-6",
            "prompt_versions": {
                "tier0_classify": "v1",
                "tier1_summarize": "v1",
                "tier2_extract": "v1",
                "tier3_deep_analysis": "v1",
            },
            "enable_prompt_cache": True,
            "enable_batch": True,
        },
        "classifier": {
            "rules": {
                "price_move_critical_pct": 5.0,
                "sources_always_critical": ["sec_edgar"],
                "sentiment_high_magnitude_critical": True,
            },
            "llm_fallback_when_score": [40, 70],
        },
        "dedup": {"url_strict": True, "title_simhash_distance": 4},
        "charts": {"auto_on_critical": True, "auto_on_earnings": True, "cache_ttl_days": 30},
        "push": {
            "per_channel_rate": "30/min",
            "same_ticker_burst_window_min": 5,
            "same_ticker_burst_threshold": 3,
            "digest_max_items_per_section": 30,
        },
        "dead_letter": {
            "auto_retry_kinds": ["scrape"],
            "notify_only_kinds": ["push_4xx"],
            "weekly_summary_day": "monday",
        },
        "retention": {"raw_news_hot_days": 30, "news_processed_hot_days": 365, "push_log_days": 90},
    }
    cfg = AppConfig.model_validate(raw)
    assert cfg.runtime.daily_cost_ceiling_cny == 5.0
    assert cfg.scheduler.digest.morning_cn == "08:30"


def test_app_config_rejects_bad_score_range():
    raw_bad = {"classifier": {"llm_fallback_when_score": [40]}}
    with pytest.raises(ValidationError):
        AppConfig.model_validate(raw_bad)
