# tests/unit/config/test_loader.py
import asyncio
from pathlib import Path

import pytest

from news_pipeline.config.loader import ConfigLoader


@pytest.fixture
def cfg_dir(tmp_path: Path) -> Path:
    common = tmp_path / "common"
    common.mkdir()
    news = tmp_path / "news_pipeline"
    news.mkdir()
    qw = tmp_path / "quote_watcher"
    qw.mkdir()

    (common / "app.yml").write_text(_minimal_app_yml())
    (common / "channels.yml").write_text("channels: {}\n")
    (common / "secrets.yml").write_text(
        "llm: {}\npush: {}\nstorage: {}\noss: {}\nsources: {}\nalert: {}\n"
    )
    (news / "watchlist.yml").write_text(
        "rules:\n  enable: true\n  us: []\n  cn: []\nllm:\n  enable: false\n  us: []\n  cn: []\n  macro: []\n  sectors: []\n"
    )
    (news / "sources.yml").write_text("sources: {}\n")
    return tmp_path


def _minimal_app_yml() -> str:
    return """
runtime: {daily_cost_ceiling_cny: 5.0, hot_reload: true}
scheduler:
  scrape: {market_hours_interval_sec: 180, off_hours_interval_sec: 1800, caixin_interval_sec: 60}
  llm: {process_interval_sec: 120}
  digest: {morning_cn: "08:30", evening_cn: "21:00", morning_us: "21:00", evening_us: "04:30"}
llm:
  tier0_model: deepseek-v3
  tier1_model: deepseek-v3
  tier2_model: claude-haiku-4-5-20251001
  tier3_model: claude-sonnet-4-6
  prompt_versions: {tier0_classify: v1, tier1_summarize: v1, tier2_extract: v1, tier3_deep_analysis: v1}
  enable_prompt_cache: true
  enable_batch: true
classifier:
  rules: {price_move_critical_pct: 5.0, sources_always_critical: [sec_edgar], sentiment_high_magnitude_critical: true}
  llm_fallback_when_score: [40, 70]
dedup: {url_strict: true, title_simhash_distance: 4}
charts: {auto_on_critical: true, auto_on_earnings: true, cache_ttl_days: 30}
push: {per_channel_rate: "30/min", same_ticker_burst_window_min: 5, same_ticker_burst_threshold: 3, digest_max_items_per_section: 30}
dead_letter: {auto_retry_kinds: [scrape], notify_only_kinds: [push_4xx], weekly_summary_day: monday}
retention: {raw_news_hot_days: 30, news_processed_hot_days: 365, push_log_days: 90}
"""


def test_loader_loads_all(cfg_dir: Path) -> None:
    loader = ConfigLoader(cfg_dir)
    snap = loader.load()
    assert snap.app.runtime.daily_cost_ceiling_cny == 5.0
    assert snap.watchlist.rules.us == []
    assert snap.watchlist.llm.us == []
    assert snap.channels.channels == {}


@pytest.mark.asyncio
async def test_loader_hot_reload_emits_event(cfg_dir: Path) -> None:
    loader = ConfigLoader(cfg_dir, debounce_ms=50)
    loader.load()
    seen: list[str] = []

    def on_change(snap):  # type: ignore[no-untyped-def]
        seen.append(snap.app.runtime.daily_cost_ceiling_cny)

    loader.start_watching(on_change)
    try:
        await asyncio.sleep(0.1)
        new = _minimal_app_yml().replace(
            "daily_cost_ceiling_cny: 5.0", "daily_cost_ceiling_cny: 7.5"
        )
        (cfg_dir / "common" / "app.yml").write_text(new)
        for _ in range(20):
            await asyncio.sleep(0.1)
            if seen:
                break
        assert seen and seen[-1] == 7.5
    finally:
        loader.stop_watching()
